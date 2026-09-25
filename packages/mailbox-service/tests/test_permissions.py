from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI

from benethos_mailbox_service.domain import permissions
from benethos_mailbox_service.errors import BadRequestError
from benethos_mailbox_service.main import create_app
from benethos_mailbox_service.web import api
from benethos_mailbox_service.web.api import PREFIX as API_PREFIX

from .conftest import METHODS


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
    assert permissions.expand(["admin"]) == frozenset(permissions.GROUP_OF)


def test_expand_rejects_unknown_names() -> None:
    with pytest.raises(BadRequestError, match="unknown right"):
        permissions.expand(["mail.everything"])


def test_a_stored_right_that_no_longer_exists_grants_nothing() -> None:
    operations, unknown = permissions.expand_known(["get_account", "mail.gone"])
    assert operations == {"get_account"}
    assert unknown == ["mail.gone"]


def test_every_operation_has_exactly_one_group() -> None:
    seen = [op for ops in permissions.GROUPS.values() for op in ops]
    assert len(seen) == len(set(seen))


def test_known_names_cover_groups_operations_and_admin() -> None:
    names = permissions.known_names()
    assert "admin" in names
    assert "mail.read" in names
    assert "list_messages" in names
