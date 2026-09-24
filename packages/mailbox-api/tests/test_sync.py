"""Stable ids for IMAP: the id mapping and the sync that keeps it, through
the real adapter against a fake server."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.models import ProviderType
from benethos_mailbox_api.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_api.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_api.data.providers.imap.client import ImapSession
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
from benethos_mailbox_api.errors import NotFoundError, ProviderUnavailableError
from benethos_mailbox_api.main import Services, build_services

from .conftest import ADMIN, create_account
from .imap_fake import FakeFolder, FakeMailBox, make_message

ARCHIVE = mappers.folder_id("Archive")


@pytest.fixture
def server() -> FakeMailBox:
    box = FakeMailBox()
    box.folders = {"INBOX": FakeFolder(uidvalidity=7), "Archive": FakeFolder()}
    for uid in range(1, 5):
        box.add(
            "INBOX",
            uid,
            make_message(f"Mail {uid}", date=datetime(2026, 9, uid, tzinfo=UTC)),
        )
    return box


@pytest.fixture
def services(server: FakeMailBox, monkeypatch: pytest.MonkeyPatch) -> Services:
    monkeypatch.setenv("MAILBOX_API_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> ImapProvider:
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, mailbox_factory=server),
            sleep=lambda seconds: None,
        )

    services = build_services(Settings(storage="memory"), provider_factory=factory)
    services.vault.initialize()
    return services


@pytest.fixture
def account_id(services: Services) -> str:
    return create_account(
        services.accounts,
        ProviderType.IMAP,
        "me@example.com",
        settings={"host": "imap.example.com", "username": "me@example.com"},
        credentials={"password": SecretStr("secret")},
    ).id


async def ids_by_subject(services: Services, account_id: str) -> dict[str, str]:
    page = await services.mailbox.list_messages(
        ADMIN,
        account_id,
        folder_id=None,
        query=None,
        unread=None,
        limit=50,
        cursor=None,
    )
    return {m.subject or "": m.id for m in page.items}


async def subject(services: Services, account_id: str, message_id: str) -> str | None:
    message = await services.mailbox.get_message(ADMIN, account_id, message_id)
    assert message.id == message_id
    return message.subject


def contents_calls(server: FakeMailBox) -> int:
    return sum(1 for c in server.calls if c[0] == "search")


async def test_ids_are_ours_and_stay_the_same(
    services: Services, account_id: str
) -> None:
    first = await ids_by_subject(services, account_id)
    assert all(i.startswith("msg_") for i in first.values())
    assert await ids_by_subject(services, account_id) == first
    assert await subject(services, account_id, first["Mail 2"]) == "Mail 2"
    raw = await services.mailbox.get_raw(ADMIN, account_id, first["Mail 2"])
    assert b"Subject: Mail 2" in raw


async def test_the_providers_own_id_is_not_accepted(
    services: Services, account_id: str
) -> None:
    with pytest.raises(NotFoundError):
        await services.mailbox.get_message(
            ADMIN, account_id, mappers.message_id("INBOX", 7, 1)
        )


async def test_a_move_by_another_client_keeps_the_id(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    server.move("INBOX", 3, "Archive", 1)
    # The lookup misses, syncs once and finds the message in its new folder.
    message = await services.mailbox.get_message(ADMIN, account_id, ids["Mail 3"])
    assert message.subject == "Mail 3"
    assert message.folder_ids == [ARCHIVE]
    assert "Mail 3" not in await ids_by_subject(services, account_id)


async def test_a_move_found_by_the_sync(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    ids = await ids_by_subject(services, account_id)  # before any sync
    await services.sync.sync_account(account_id)
    server.move("INBOX", 1, "Archive", 5)
    await services.sync.sync_account(account_id)
    assert await subject(services, account_id, ids["Mail 1"]) == "Mail 1"


async def test_a_new_uidvalidity_keeps_every_id(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    inbox = server.folders["INBOX"]
    inbox.uidvalidity = 8
    inbox.messages = {uid + 100: entry for uid, entry in inbox.messages.items()}
    await services.sync.sync_account(account_id)
    assert await ids_by_subject(services, account_id) == ids


async def test_a_deleted_message_is_gone(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    del server.folders["INBOX"].messages[2]
    with pytest.raises(NotFoundError):
        await services.mailbox.get_message(ADMIN, account_id, ids["Mail 2"])


async def test_an_ambiguous_move_is_not_guessed(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    raw = server.folders["INBOX"].messages[4][0]
    server.move("INBOX", 4, "Archive", 1)
    server.add("Archive", 2, raw)  # a second copy with the same Message-ID
    with pytest.raises(NotFoundError):
        await services.mailbox.get_message(ADMIN, account_id, ids["Mail 4"])


async def test_a_message_without_message_id_cannot_be_followed(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    server.add("INBOX", 9, make_message("No id").replace(b"Message-ID:", b"X-Id:", 1))
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    server.move("INBOX", 9, "Archive", 1)
    with pytest.raises(NotFoundError):
        await services.mailbox.get_message(ADMIN, account_id, ids["No id"])


async def test_only_changed_folders_are_read(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    assert contents_calls(server) == 2
    await services.sync.sync_account(account_id)
    assert contents_calls(server) == 2
    server.add("Archive", 1, make_message("Filed"))
    await services.sync.sync_account(account_id)
    assert contents_calls(server) == 3


async def test_the_sync_reads_only_the_headers_it_lacks(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    server.calls.clear()
    server.add("INBOX", 5, make_message("Mail 5"))
    await services.sync.sync_account(account_id)
    header_fetches = [c for c in server.calls if c[0] == "uid"]
    assert [c[2] for c in header_fetches] == ["5"]


async def test_a_failed_sync_changes_nothing(
    services: Services, account_id: str, server: FakeMailBox
) -> None:
    await services.sync.sync_account(account_id)
    ids = await ids_by_subject(services, account_id)
    server.move("INBOX", 1, "Archive", 1)
    server.failures = [OSError("gone")] * 3
    with pytest.raises(ProviderUnavailableError):
        await services.sync.sync_account(account_id)
    server.failures = []
    # Ends the adapter's pause after the failure.
    await services.accounts.verify(ADMIN, account_id)
    # The earlier state is kept, so the next pass still sees the move.
    await services.sync.sync_account(account_id)
    assert await subject(services, account_id, ids["Mail 1"]) == "Mail 1"


async def test_deleting_the_account_forgets_its_ids(
    services: Services, account_id: str
) -> None:
    await services.sync.sync_account(account_id)
    await services.accounts.delete(ADMIN, account_id)
    index = services.sync._index  # the store behind the service
    assert index.folder_states(account_id) == {}
    assert index.in_folders(account_id, [mappers.folder_id("INBOX")]) == []
