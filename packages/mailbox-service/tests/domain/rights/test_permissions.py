from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import BadRequestError
from benethos_mailbox_service.main import create_app
from benethos_mailbox_service.web import api
from benethos_mailbox_service.web.api import PREFIX as API_PREFIX

from ...conftest import METHODS


def test_every_v1_operation_declares_its_right() -> None:
    schema = create_app().openapi()
    for path, operations in schema["paths"].items():
        if not path.startswith(API_PREFIX):
            continue
        for method, operation in operations.items():
            if method not in METHODS:
                continue
            expected = permissions.permission_of(operation["operationId"])
            assert expected is not None, operation["operationId"]
            assert operation["x-permission"] == expected


def test_health_carries_no_right() -> None:
    schema = create_app().openapi()
    assert "x-permission" not in schema["paths"]["/health"]["get"]


def test_a_route_missing_from_the_catalogue_stops_the_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benethos_mailbox_service.web.api.routes import accounts

    stray = APIRouter()

    @stray.get("/stray")
    async def stray_operation() -> None:
        return None

    monkeypatch.setattr(accounts, "router", stray)
    with pytest.raises(RuntimeError, match="stray_operation"):
        api.install(FastAPI())


def test_expand_groups_operations_and_admin() -> None:
    assert permissions.expand(["mail.read"]) == frozenset(
        permissions.GROUPS["mail.read"]
    )
    assert permissions.expand(["get_account"]) == {"get_account"}
    assert permissions.expand(["admin"]) == (
        frozenset(permissions.GROUP_OF) | permissions.ADMIN_ONLY
    )


def test_expand_rejects_unknown_names() -> None:
    with pytest.raises(BadRequestError, match="unknown right"):
        permissions.expand(["mail.everything"])


def test_a_stored_right_that_no_longer_exists_grants_nothing() -> None:
    operations, unknown = permissions.expand_known(["get_account", "mail.gone"])
    assert operations == {"get_account"}
    assert unknown == ["mail.gone"]


def test_every_operation_has_exactly_one_group_but_users_read() -> None:
    """users.read is a part of users.manage, the one group inside another."""
    groups = {g: ops for g, ops in permissions.GROUPS.items() if g != "users.read"}
    seen = [op for ops in groups.values() for op in ops]
    assert len(seen) == len(set(seen))
    assert set(permissions.GROUPS["users.read"]) < set(
        permissions.GROUPS["users.manage"]
    )
    assert permissions.permission_of("list_users") == "users.read"
    assert permissions.permission_of("create_user") == "users.manage"


def test_summarize_names_the_larger_group_alone() -> None:
    groups, rest = permissions.summarize(
        permissions.GROUPS["users.manage"], permissions.SERVICE
    )
    assert groups == ["users.manage"] and rest == []
    groups, rest = permissions.summarize(
        [*permissions.GROUPS["users.read"], "create_token"], permissions.SERVICE
    )
    assert groups == ["users.read"] and rest == ["create_token"]


@pytest.mark.parametrize(
    "name", ["admin", "users.manage", "accounts.connect", "create_user"]
)
def test_a_grant_refuses_a_right_of_the_service(name: str) -> None:
    with pytest.raises(BadRequestError, match="name it in service"):
        permissions.check_grant(["mail.read", name])


@pytest.mark.parametrize("name", ["mail.read", "accounts.manage", "get_message"])
def test_the_service_list_refuses_a_right_on_accounts(name: str) -> None:
    with pytest.raises(BadRequestError, match="name it in a grant"):
        permissions.check_service(["users.read", name])


def test_both_lists_refuse_an_unknown_name() -> None:
    with pytest.raises(BadRequestError, match="unknown right"):
        permissions.check_grant(["mail.everything"])
    with pytest.raises(BadRequestError, match="unknown right"):
        permissions.check_service(["users.everything"])


def test_known_names_cover_groups_operations_and_admin() -> None:
    names = permissions.known_names()
    assert "admin" in names
    assert "mail.read" in names
    assert "list_messages" in names


@pytest.mark.parametrize("operation", ["show_recovery_key", "read_service_log"])
def test_admin_alone(operation: str) -> None:
    """The recovery key opens every secret, the log names users and
    addresses: no name but admin gives them."""
    assert operation not in permissions.known_names()
    with pytest.raises(BadRequestError):
        permissions.expand([operation])
    assert Access("u", "u", [], service=["admin"]).allows(operation)
    every_group = [*permissions.SERVICE_GROUPS]
    assert not Access("u", "u", [], service=every_group).allows(operation)
    stored = Access("u", "u", [Grant(accounts=["*"], allow=["admin"])])
    assert not stored.allows(operation)
