from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.data.models import Grant, Role, User
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import ForbiddenError, NotFoundError

from ...conftest import admin_access


def access(*grants: Grant, service: tuple[str, ...] = ()) -> Access:
    return Access("usr_1", "test", grants, service=service)


def test_grant_on_one_account() -> None:
    a = access(Grant(accounts=["acc_a"], allow=["mail.read"]))
    assert a.allows("list_messages", "acc_a")
    assert not a.allows("list_messages", "acc_b")
    assert not a.allows("delete_account", "acc_a")


def test_star_covers_every_account() -> None:
    a = access(Grant(accounts=["*"], allow=["accounts.read"]))
    assert a.allows("get_account", "acc_anything")
    assert not a.allows("list_messages", "acc_anything")


def test_single_operation_as_right() -> None:
    a = access(Grant(accounts=["acc_a"], allow=["get_message"]))
    assert a.allows("get_message", "acc_a")
    assert not a.allows("list_messages", "acc_a")


def test_union_of_grants() -> None:
    a = access(
        Grant(accounts=["acc_a"], allow=["mail.read"]),
        Grant(accounts=["acc_b"], allow=["accounts.read"]),
    )
    assert a.allows("list_messages", "acc_a")
    assert a.allows("get_account", "acc_b")
    assert not a.allows("list_messages", "acc_b")


def test_account_bound_operation_needs_an_account() -> None:
    a = access(Grant(accounts=["*"], allow=["mail.read"]))
    assert not a.allows("list_messages")


def test_connecting_is_a_right_of_the_service() -> None:
    assert access(service=("accounts.connect",)).allows("create_account")
    assert not access(Grant(accounts=["*"], allow=["accounts.manage"])).allows(
        "create_account"
    )


def test_a_grant_gives_no_right_of_the_service() -> None:
    """Even one stored before the move: a grant is about accounts."""
    a = access(Grant(accounts=["*"], allow=["admin", "users.manage"]))
    assert a.allows("delete_account", "acc_a")
    assert not a.allows("list_users")
    assert not a.is_admin()


def test_a_service_list_gives_no_right_on_accounts() -> None:
    a = access(service=("users.manage", "mail.read"))
    assert a.allows("create_user")
    assert not a.allows("list_messages", "acc_a")
    assert not a.sees("acc_a")


def test_users_read_reads_and_changes_nothing() -> None:
    a = access(service=("users.read",))
    assert all(a.allows(op) for op in ("list_users", "get_user", "list_tokens"))
    assert all(a.allows(op) for op in ("list_roles", "get_role"))
    assert not a.allows("create_token") and not a.allows("update_user")


def test_admin_allows_everything() -> None:
    a = admin_access("usr_admin", "admin")
    assert a.allows("delete_account", "acc_x")
    assert a.allows("create_account")


def test_require_hides_unseen_accounts_as_not_found() -> None:
    a = access(Grant(accounts=["acc_a"], allow=["accounts.read"]))
    with pytest.raises(NotFoundError):
        a.require("list_messages", "acc_b")


def test_a_right_on_accounts_to_come_shows_no_account() -> None:
    a = access(service=("discover_account", "create_account"))
    assert not a.sees("acc_a")
    with pytest.raises(NotFoundError):
        a.require("list_messages", "acc_a")
    assert a.allows("create_account")


def test_require_names_the_missing_right() -> None:
    a = access(Grant(accounts=["acc_a"], allow=["accounts.read"]))
    with pytest.raises(ForbiddenError, match="list_messages on account acc_a"):
        a.require("list_messages", "acc_a")


def test_require_without_account() -> None:
    a = access(Grant(accounts=["acc_a"], allow=["accounts.manage"]))
    with pytest.raises(ForbiddenError, match="missing right: create_account$"):
        a.require("create_account")
    a.require("delete_account", "acc_a")


def test_roles_add_their_grants() -> None:
    user = User(
        id="usr_1",
        name="dashboard",
        roles=["reader", "gone"],
        grants=[Grant(accounts=["acc_a"], allow=["accounts.manage"])],
    )
    roles = {
        "reader": Role(id="reader", grants=[Grant(accounts=["*"], allow=["mail.read"])])
    }
    a = Access.for_user(user, roles)
    assert a.allows("list_messages", "acc_z")
    assert a.allows("delete_account", "acc_a")
    assert a.user_id == "usr_1"
    assert a.name == "dashboard"


def test_covers_blocks_escalation() -> None:
    a = access(Grant(accounts=["acc_a"], allow=["mail.read", "accounts.read"]))
    assert a.covers([Grant(accounts=["acc_a"], allow=["mail.read"])])
    assert not a.covers([Grant(accounts=["acc_b"], allow=["mail.read"])])
    assert not a.covers([Grant(accounts=["*"], allow=["mail.read"])])
    assert not a.covers([Grant(accounts=["acc_a"], allow=["accounts.manage"])])


def test_a_right_that_no_longer_exists_does_not_block_covers() -> None:
    renamed = Grant(accounts=["acc_a"], allow=["mail.read", "mail.renamed"])
    a = access(Grant(accounts=["acc_a"], allow=["mail.read"]))
    assert a.covers([renamed])


def test_covers_what_the_caller_holds_on_named_accounts() -> None:
    held = Grant(accounts=["acc_a"], allow=["accounts.manage"])
    a = access(held)
    assert a.covers([held])
    assert not a.allows("create_account")
    assert not a.covers([Grant(accounts=["*"], allow=["accounts.manage"])])


def test_covers_star_needs_star() -> None:
    a = access(Grant(accounts=["*"], allow=["mail.read"]))
    assert a.covers([Grant(accounts=["*"], allow=["list_messages"])])
    assert admin_access("x", "x").covers([], ["admin"])


def test_covers_the_service_rights_the_caller_holds() -> None:
    a = access(service=("users.manage",))
    assert a.covers([], ["users.read", "create_user"])
    assert not a.covers([], ["webhooks.manage"])
    # admin is every right: only an administrator hands it out.
    every = access(
        Grant(accounts=["*"], allow=["mail.read"]),
        service=("users.manage", "webhooks.manage", "accounts.connect"),
    )
    assert not every.covers([], ["admin"])


def test_operations_on_an_account() -> None:
    a = access(
        Grant(accounts=["acc_a"], allow=["accounts.read"]),
        Grant(accounts=["*"], allow=["accounts.manage"]),
        service=("accounts.connect",),
    )
    assert a.operations_on("acc_a") == {
        "list_accounts",
        "get_account",
        "get_status",
        "update_account",
        "delete_account",
        "verify_account",
    }
    assert a.general_operations() == {
        "create_account",
        "discover_account",
        "start_device_oauth",
        "poll_device_oauth",
    }


def test_anywhere_finds_a_right_on_some_account() -> None:
    a = access(
        Grant(accounts=["acc_a"], allow=["audit"]),
        Grant(accounts=["acc_b"], allow=["accounts.manage"]),
    )
    assert a.anywhere("list_sends")
    assert not a.anywhere("send_message")
    assert not a.anywhere("create_account")
    assert access(service=("users.manage",)).anywhere("list_users")


def test_filter_keeps_the_accounts_the_operation_is_allowed_on() -> None:
    access = Access(
        "usr_1", "u", [Grant(accounts=["acc_1", "acc_3"], allow=["list_messages"])]
    )
    ids = ["acc_3", "acc_2", "acc_1", "acc_3"]
    assert access.filter("list_messages", ids) == ["acc_3", "acc_1"]
    assert access.filter("send_message", ids) == []


def test_a_batch_needs_its_right_and_the_operation() -> None:
    both = access(Grant(accounts=["acc_a"], allow=["batch_messages", "update_message"]))
    assert both.batches("update_message", "acc_a")
    assert not both.batches("delete_message", "acc_a")
    only = access(Grant(accounts=["acc_a"], allow=["update_message"]))
    assert not only.batches("update_message", "acc_a")


def test_the_status_is_for_who_may_see_it_of_some_account() -> None:
    assert access(Grant(accounts=["acc_a"], allow=["accounts.read"])).sees_status()
    assert access(Grant(accounts=["acc_a"], allow=["get_status"])).sees_status()
    assert not access(Grant(accounts=["acc_a"], allow=["list_accounts"])).sees_status()
    assert not access(Grant(accounts=["acc_a"], allow=["list_messages"])).sees_status()


NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_a_grant_ends_at_its_expiry() -> None:
    grant = Grant(accounts=["acc_a"], allow=["mail.read"], expires_at=NOW)
    before = Access("u", "u", [grant], now=NOW - timedelta(seconds=1))
    assert before.allows("list_messages", "acc_a")
    at = Access("u", "u", [grant], now=NOW)
    assert not at.allows("list_messages", "acc_a")
    assert not at.sees("acc_a")


def test_an_expired_grant_asks_nothing_of_a_manager() -> None:
    """A manager may change a user whose expired grant it does not hold:
    that grant grants nothing."""
    manager = Access("u", "u", [], now=NOW)
    expired = Grant(accounts=["*"], allow=["send"], expires_at=NOW)
    assert manager.covers([expired])
