"""A batch of the users list: one change to several users, all or none."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ActivityFilter
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import BadRequestError, ConflictError

from ...conftest import ADMIN


def test_a_batch_changes_every_user_or_none_and_names_the_refused(
    services: Services,
) -> None:
    one = services.users.create_user(ADMIN, "one", [], [])
    narrow = Access("usr_n", "narrow", [], service=["users.manage"])
    wide = services.users.create_user(ADMIN, "wide", [], [], service=["admin"])
    done = services.users.change_users(narrow, [one.id, wide.id], "disable")
    assert done.changed == []
    [(name, why)] = done.refused
    assert name == "wide" and "lacks" in why
    assert not services.users.get_user(ADMIN, one.id).disabled
    alone = services.users.change_users(narrow, [one.id], "disable")
    assert [u.name for u in alone.changed] == ["one"]
    with pytest.raises(BadRequestError):
        services.users.change_users(ADMIN, [one.id], "promote")
    with pytest.raises(BadRequestError):
        services.users.change_users(ADMIN, [one.id], "give_role")
    unknown = services.users.change_users(ADMIN, [one.id], "give_role", "nobody")
    assert unknown.refused == [("one", "unknown role: nobody")]


def test_each_user_a_batch_refused_is_audited(services: Services) -> None:
    one = services.users.create_user(ADMIN, "one", [], [])
    narrow = Access("usr_n", "narrow", [], service=["users.manage"])
    wide = services.users.create_user(ADMIN, "wide", [], [], service=["admin"])
    batch = [one.id, wide.id, "usr_gone"]
    [(_, lacks), (_, gone)] = services.users.change_users(
        narrow, batch, "disable"
    ).refused
    services.users.change_users(ADMIN, [one.id], "give_role", "nobody")
    matching = ActivityFilter(activity="users.change_refused")
    records = services.audit.list_activity(ADMIN, limit=10, matching=matching)
    said = {r.record: (r.outcome, r.detail) for r in records.items}
    assert said == {
        wide.id: (
            "refused",
            f"could not disable user wide ({wide.id}) in a batch: {lacks}",
        ),
        "usr_gone": (
            "refused",
            f"could not disable user usr_gone (usr_gone) in a batch: {gone}",
        ),
        one.id: (
            "refused",
            f"could not give role nobody to user one ({one.id}) in a batch: "
            "unknown role: nobody",
        ),
    }


def test_a_batch_counts_only_the_users_it_changed(services: Services) -> None:
    one = services.users.create_user(ADMIN, "one", [], [])
    two = services.users.create_user(ADMIN, "two", [], [])
    services.users.update_user(ADMIN, two.id, disabled=True)
    services.roles.create_role(ADMIN, "helper", [])
    disabled = services.users.change_users(ADMIN, [one.id, two.id], "disable")
    assert [u.name for u in disabled.changed] == ["one"]
    taken = services.users.change_users(ADMIN, [one.id, two.id], "take_role", "helper")
    assert taken.changed == [] and taken.refused == []


def test_a_batch_leaves_an_administrator_counting_every_user() -> None:
    """Each of two administrators could be disabled alone, not both."""
    services = build_services(Settings(storage="memory"))
    first = services.users.create_user(
        ADMIN, "first", [], [], service=["admin"], ui_sign_in=True
    )
    second = services.users.create_user(
        ADMIN, "second", [], [], service=["admin"], ui_sign_in=True
    )
    with pytest.raises(ConflictError, match="no enabled administrator"):
        services.users.change_users(ADMIN, [first.id, second.id], "disable")
    assert not services.users.get_user(ADMIN, first.id).disabled
    assert not services.users.get_user(ADMIN, second.id).disabled
