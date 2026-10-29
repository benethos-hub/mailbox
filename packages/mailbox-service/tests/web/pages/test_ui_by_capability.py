"""The mail pages by what an account can do, never by its kind (UNIFORM
U5): the memory adapter answers the capabilities a test gives it, and
each action follows the one that guards it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Abilities, Capability, Mark

from ...conftest import memory_of, relearn

EVERY = frozenset(Capability)


def page_with(
    ui: TestClient, services: Services, account_id: str, abilities: Abilities
) -> str:
    memory = memory_of(services, account_id)
    memory.given = abilities
    relearn(services, account_id)
    return ui.get(f"/ui/accounts/{account_id}/mail/m3").text


@pytest.mark.parametrize(
    ("capability", "shown"),
    [
        (Capability.READ_STATE, 'name="unread"'),
        (Capability.STARS, 'name="starred"'),
        (Capability.MOVE, "move-message"),
        (Capability.TRASH, "Move to the trash"),
        (Capability.PURGE, "Delete for good"),
        (Capability.KEYWORDS, 'aria-label="New keyword"'),
    ],
)
def test_an_action_follows_its_capability(
    ui: TestClient,
    services: Services,
    account_id: str,
    capability: Capability,
    shown: str,
) -> None:
    every = Abilities.of(EVERY, written=set(Mark))
    assert shown in page_with(ui, services, account_id, every)
    lacking = Abilities.of(EVERY - {capability}, written=set(Mark))
    assert shown not in page_with(ui, services, account_id, lacking)


def test_writing_follows_drafts_and_sending(
    ui: TestClient, services: Services, account_id: str
) -> None:
    neither = Abilities.of(EVERY - {Capability.DRAFTS, Capability.SEND})
    page = page_with(ui, services, account_id, neither)
    assert "Reply to all" not in page and "Forward" not in page
    drafts_only = Abilities.of(EVERY - {Capability.SEND})
    assert "Reply to all" in page_with(ui, services, account_id, drafts_only)


def test_marks_read_only_show_and_change_nothing(
    ui: TestClient, services: Services, account_id: str
) -> None:
    """An account that reads its marks but writes none: the mark shows,
    in words, and nothing offers to set one."""
    memory = memory_of(services, account_id)
    message = next(m for m in memory.messages if m.id == "m3")
    message.keywords.append("$answered")
    read_only = Abilities.of(EVERY, read=set(Mark))
    page = page_with(ui, services, account_id, read_only)
    assert '<span class="tag">answered</span>' in page
    assert "$answered" not in page


def test_the_account_page_says_what_the_account_can(
    ui: TestClient, services: Services, account_id: str
) -> None:
    """Why a button is missing on its mail pages, in words."""
    memory = memory_of(services, account_id)
    memory.given = Abilities.of(EVERY, written={Mark.ANSWERED})
    relearn(services, account_id)
    page = ui.get(f"/ui/accounts/{account_id}").text
    assert '<span class="tag">conversations</span>' in page
    assert '<span class="tag">answered</span>' in page
    memory.given = Abilities.of(EVERY - {Capability.THREADS})
    relearn(services, account_id)
    page = ui.get(f"/ui/accounts/{account_id}").text
    assert '<span class="tag">conversations</span>' not in page
    assert "Sets marks" not in page
