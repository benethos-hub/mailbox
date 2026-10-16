"""The repository of links to attachments: one contract, the same tests
for the in-memory and the SQLite implementation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import Account, ApiToken, ProviderType, User
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryLinkRepository,
    LinkRepository,
    SqliteAccountRepository,
    SqliteLinkRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
    StoredLink,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def link(name: str, seconds: int = 120) -> StoredLink:
    return StoredLink(
        id=f"lnk_{name}",
        secret_hash=f"hash-{name}",
        account_id="acc_1",
        message_id="msg_1",
        attachment_id="att_1",
        token_id="tok_1",
        expires_at=NOW + timedelta(seconds=seconds),
    )


@pytest.fixture(params=["memory", "sqlite"])
def links(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LinkRepository]:
    if request.param == "memory":
        yield InMemoryLinkRepository()
        return
    db = Database(tmp_path / "links.db")
    SqliteAccountRepository(db).add(
        Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
    )
    SqliteUserRepository(db).save(User(id="usr_1", name="u"))
    SqliteTokenRepository(db).save(
        ApiToken(id="tok_1", user_id="usr_1", name="t", token_hash="h", created_at=NOW)
    )
    yield SqliteLinkRepository(db)
    db.close()


def test_a_link_is_found_by_the_digest_of_its_secret(links: LinkRepository) -> None:
    links.add(link("a"))
    assert links.find("hash-a") == link("a")
    assert links.find("hash-b") is None


def test_a_link_is_used_once(links: LinkRepository) -> None:
    links.add(link("a"))
    assert links.redeem("lnk_a", NOW, "203.0.113.1") is True
    assert links.redeem("lnk_a", NOW, "203.0.113.2") is False
    found = links.find("hash-a")
    assert found is not None
    assert found.redeemed_at == NOW and found.redeemed_by == "203.0.113.1"


def test_a_link_released_holds_again(links: LinkRepository) -> None:
    links.add(link("a"))
    links.redeem("lnk_a", NOW, "203.0.113.1")
    links.release("lnk_a")
    assert links.find("hash-a") == link("a")
    assert links.redeem("lnk_a", NOW, "203.0.113.2") is True
    links.release("lnk_unknown")


def test_a_link_cannot_be_used_once_it_ended(links: LinkRepository) -> None:
    links.add(link("a", seconds=60))
    assert links.redeem("lnk_a", NOW + timedelta(seconds=60), "x") is False
    assert links.redeem("lnk_unknown", NOW, "x") is False


def test_the_purge_takes_the_links_used_and_ended(links: LinkRepository) -> None:
    for name, seconds in (("used", 120), ("ended", 60), ("kept", 120)):
        links.add(link(name, seconds))
    links.redeem("lnk_used", NOW, "x")
    assert links.purge(NOW + timedelta(seconds=60)) == 2
    assert links.find("hash-kept") is not None
    assert links.find("hash-used") is None and links.find("hash-ended") is None
