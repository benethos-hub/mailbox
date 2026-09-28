from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import Grant, Role, User
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import ForbiddenError, NotFoundError


def access(*grants: Grant) -> Access:
    return Access("usr_1", "test", grants)


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


def test_create_account_needs_every_account() -> None:
    assert access(Grant(accounts=["*"], allow=["accounts.manage"])).allows(
        "create_account"
    )
    assert not access(Grant(accounts=["acc_a"], allow=["accounts.manage"])).allows(
        "create_account"
    )


def test_admin_allows_everything() -> None:
    a = Access.admin("usr_admin", "admin")
    assert a.allows("delete_account", "acc_x")
    assert a.allows("create_account")


def test_require_hides_unseen_accounts_as_not_found() -> None:
    a = access(Grant(accounts=["acc_a"], allow=["accounts.read"]))
    with pytest.raises(NotFoundError):
        a.require("list_messages", "acc_b")


def test_a_right_on_accounts_to_come_shows_no_account() -> None:
    a = access(Grant(accounts=["*"], allow=["discover_account", "create_account"]))
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


@pytest.mark.parametrize("right", ["accounts.manage", "admin"])
def test_covers_what_the_caller_holds_on_named_accounts(right: str) -> None:
    # accounts.manage and admin name create_account and the like, which a
    # grant on named accounts grants nowhere.
    held = Grant(accounts=["acc_a"], allow=[right])
    a = access(held)
    assert a.covers([held])
    assert not a.allows("create_account")
    assert not a.covers([Grant(accounts=["*"], allow=["accounts.manage"])])


def test_covers_star_needs_star() -> None:
    a = access(Grant(accounts=["*"], allow=["mail.read"]))
    assert a.covers([Grant(accounts=["*"], allow=["list_messages"])])
    assert Access.admin("x", "x").covers([Grant(accounts=["*"], allow=["admin"])])


def test_operations_on_an_account() -> None:
    a = access(
        Grant(accounts=["acc_a"], allow=["accounts.read"]),
        Grant(accounts=["*"], allow=["accounts.manage"]),
    )
    assert a.operations_on("acc_a") == {
        "list_accounts",
        "get_account",
        "update_account",
        "delete_account",
        "verify_account",
    }
    assert a.general_operations() == {
        "create_account",
        "discover_account",
        "start_oauth",
    }


def test_anywhere_finds_a_right_on_some_account() -> None:
    a = access(
        Grant(accounts=["acc_a"], allow=["audit"]),
        Grant(accounts=["acc_b"], allow=["accounts.manage"]),
    )
    assert a.anywhere("list_sends")
    assert not a.anywhere("send_message")
    # Connecting needs every account, a grant on one does not count.
    assert not a.anywhere("create_account")
    assert access(Grant(accounts=[], allow=["users.manage"])).anywhere("list_users")


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


def test_the_status_is_for_who_may_list_some_account() -> None:
    assert access(Grant(accounts=["acc_a"], allow=["list_accounts"])).sees_status()
    assert not access(Grant(accounts=["acc_a"], allow=["list_messages"])).sees_status()
