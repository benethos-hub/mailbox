"""Stable ids for IMAP: the id mapping and the sync that keeps it, through
the real adapter against a fake server."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    FolderUpdate,
    MessageBatch,
    MessageUpdate,
    ProviderType,
)
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    MailProvider,
    ProviderSettings,
)
from benethos_mailbox_service.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.providers.protocols.imap import ImapSession
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.errors import NotFoundError, ProviderUnavailableError
from benethos_mailbox_service.main import Services, build_services

from ...conftest import ADMIN, create_account
from ...imap_fake import FakeFolder, FakeMailBox, make_message

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
def imap_services(server: FakeMailBox, monkeypatch: pytest.MonkeyPatch) -> Services:
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> MailProvider:
        if kind is ProviderType.MEMORY:
            return MemoryProvider()
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=server),
            sleep=lambda seconds: None,
        )

    imap_services = build_services(Settings(storage="memory"), provider_factory=factory)
    imap_services.vault.initialize()
    return imap_services


@pytest.fixture
def imap_account_id(imap_services: Services) -> str:
    return create_account(
        imap_services.accounts,
        ProviderType.IMAP,
        "me@example.com",
        settings={"host": "imap.example.com", "username": "me@example.com"},
        credentials={"password": SecretStr("secret")},
    ).id


async def ids_by_subject(
    imap_services: Services, imap_account_id: str
) -> dict[str, str]:
    page = await imap_services.mailbox.list_messages(
        ADMIN,
        imap_account_id,
        folder_id=None,
        limit=50,
        cursor=None,
    )
    return {m.subject or "": m.id for m in page.items}


async def subject(
    imap_services: Services, imap_account_id: str, message_id: str
) -> str | None:
    message = await imap_services.mailbox.get_message(
        ADMIN, imap_account_id, message_id
    )
    assert message.id == message_id
    return message.subject


def contents_calls(server: FakeMailBox) -> int:
    return sum(1 for c in server.calls if c[0] == "search")


async def test_a_deleted_account_leaves_no_sync_state(
    imap_services: Services, imap_account_id: str
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    assert imap_services.sync.state(imap_account_id).last_sync_at is not None
    await imap_services.accounts.delete(ADMIN, imap_account_id)
    assert imap_services.sync.state(imap_account_id).last_sync_at is None
    assert imap_services.index.folder_states(imap_account_id) == {}


async def test_a_missing_attachment_is_not_a_moved_message(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    message_id = (await ids_by_subject(imap_services, imap_account_id))["Mail 1"]
    before = contents_calls(server)
    with pytest.raises(NotFoundError, match="attachment att_9 not found"):
        await imap_services.mailbox.get_attachment(
            ADMIN, imap_account_id, message_id, "att_9"
        )
    # No sync was triggered: the message is where the index says.
    assert contents_calls(server) == before


async def test_ids_are_ours_and_stay_the_same(
    imap_services: Services, imap_account_id: str
) -> None:
    first = await ids_by_subject(imap_services, imap_account_id)
    assert all(i.startswith("msg_") for i in first.values())
    assert await ids_by_subject(imap_services, imap_account_id) == first
    assert await subject(imap_services, imap_account_id, first["Mail 2"]) == "Mail 2"
    raw = await imap_services.mailbox.get_raw(ADMIN, imap_account_id, first["Mail 2"])
    assert b"Subject: Mail 2" in raw


async def test_the_providers_own_id_is_not_accepted(
    imap_services: Services, imap_account_id: str
) -> None:
    with pytest.raises(NotFoundError):
        await imap_services.mailbox.get_message(
            ADMIN, imap_account_id, mappers.message_id("INBOX", 7, 1)
        )


async def test_a_move_by_another_client_keeps_the_id(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    server.other_client_moves("INBOX", 3, "Archive", 1)
    # The lookup misses, syncs once and finds the message in its new folder.
    message = await imap_services.mailbox.get_message(
        ADMIN, imap_account_id, ids["Mail 3"]
    )
    assert message.subject == "Mail 3"
    assert message.folder_ids == [ARCHIVE]
    assert "Mail 3" not in await ids_by_subject(imap_services, imap_account_id)


async def test_a_move_found_by_the_sync(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    ids = await ids_by_subject(imap_services, imap_account_id)  # before any sync
    await imap_services.sync.sync_account(imap_account_id)
    server.other_client_moves("INBOX", 1, "Archive", 5)
    await imap_services.sync.sync_account(imap_account_id)
    assert await subject(imap_services, imap_account_id, ids["Mail 1"]) == "Mail 1"


async def test_a_new_uidvalidity_keeps_every_id(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    inbox = server.folders["INBOX"]
    inbox.uidvalidity = 8
    inbox.messages = {uid + 100: entry for uid, entry in inbox.messages.items()}
    await imap_services.sync.sync_account(imap_account_id)
    assert await ids_by_subject(imap_services, imap_account_id) == ids


async def test_a_deleted_message_is_gone(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    del server.folders["INBOX"].messages[2]
    with pytest.raises(NotFoundError):
        await imap_services.mailbox.get_message(ADMIN, imap_account_id, ids["Mail 2"])


async def test_an_ambiguous_move_is_not_guessed(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    raw = server.folders["INBOX"].messages[4][0]
    server.other_client_moves("INBOX", 4, "Archive", 1)
    server.add("Archive", 2, raw)  # a second copy with the same Message-ID
    with pytest.raises(NotFoundError):
        await imap_services.mailbox.get_message(ADMIN, imap_account_id, ids["Mail 4"])


async def test_a_message_without_message_id_cannot_be_followed(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    server.add("INBOX", 9, make_message("No id").replace(b"Message-ID:", b"X-Id:", 1))
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    server.other_client_moves("INBOX", 9, "Archive", 1)
    with pytest.raises(NotFoundError):
        await imap_services.mailbox.get_message(ADMIN, imap_account_id, ids["No id"])


async def test_only_changed_folders_are_read(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    assert contents_calls(server) == 2
    await imap_services.sync.sync_account(imap_account_id)
    assert contents_calls(server) == 2
    server.add("Archive", 1, make_message("Filed"))
    await imap_services.sync.sync_account(imap_account_id)
    assert contents_calls(server) == 3


async def test_the_sync_reads_only_the_headers_it_lacks(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    server.calls.clear()
    server.add("INBOX", 5, make_message("Mail 5"))
    await imap_services.sync.sync_account(imap_account_id)
    header_fetches = [
        c for c in server.calls if c[0] == "fetch" and c[2] == "message-id"
    ]
    assert [c[1] for c in header_fetches] == [("5",)]


async def test_a_failed_sync_changes_nothing(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    server.other_client_moves("INBOX", 1, "Archive", 1)
    server.failures = [OSError("gone")] * 3
    with pytest.raises(ProviderUnavailableError):
        await imap_services.sync.sync_account(imap_account_id)
    server.failures = []
    # Ends the adapter's pause after the failure.
    await imap_services.accounts.verify(ADMIN, imap_account_id)
    # The earlier state is kept, so the next pass still sees the move.
    await imap_services.sync.sync_account(imap_account_id)
    assert await subject(imap_services, imap_account_id, ids["Mail 1"]) == "Mail 1"


async def test_deleting_the_account_forgets_its_ids(
    imap_services: Services, imap_account_id: str
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    await imap_services.accounts.delete(ADMIN, imap_account_id)
    index = imap_services.index
    assert index.folder_states(imap_account_id) == {}
    assert index.in_folders(imap_account_id, [mappers.folder_id("INBOX")]) == []


async def test_a_new_mail_listed_and_moved_before_the_next_sync(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    # Found live: the listing gave the new mail its id, and another client
    # moved it before any sync had read its Message-ID.
    await imap_services.sync.sync_account(imap_account_id)
    server.add("INBOX", 5, make_message("Just arrived"))
    ids = await ids_by_subject(imap_services, imap_account_id)
    server.other_client_moves("INBOX", 5, "Archive", 1)
    assert (
        await subject(imap_services, imap_account_id, ids["Just arrived"])
        == "Just arrived"
    )


# --- through the domain: the id stays ------------------------------------------


async def test_our_own_move_keeps_the_id_without_a_sync(
    imap_services: Services,
    imap_account_id: str,
    server: FakeMailBox,
) -> None:
    ids = await ids_by_subject(imap_services, imap_account_id)
    moved = await imap_services.mailbox.update_message(
        ADMIN, imap_account_id, ids["Mail 2"], MessageUpdate(folder_ids=[ARCHIVE])
    )
    assert moved.id == ids["Mail 2"]
    assert moved.folder_ids == [ARCHIVE]
    server.calls.clear()
    message = await imap_services.mailbox.get_message(
        ADMIN, imap_account_id, ids["Mail 2"]
    )
    assert message.folder_ids == [ARCHIVE]
    # Found at once: COPYUID updated the mapping, no sync was needed.
    assert not any(c[0] == "status" for c in server.calls)


async def test_the_sync_after_our_move_keeps_the_id(
    imap_services: Services,
    imap_account_id: str,
    server: FakeMailBox,
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    await imap_services.mailbox.update_message(
        ADMIN, imap_account_id, ids["Mail 1"], MessageUpdate(folder_ids=[ARCHIVE])
    )
    await imap_services.sync.sync_account(imap_account_id)
    server.add("INBOX", 9, make_message("Later"))
    await imap_services.sync.sync_account(imap_account_id)
    message = await imap_services.mailbox.get_message(
        ADMIN, imap_account_id, ids["Mail 1"]
    )
    assert message.subject == "Mail 1"
    assert message.folder_ids == [ARCHIVE]


async def test_the_trash_keeps_the_id_and_for_good_forgets_it(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    server.folders["Trash"] = FakeFolder(flags=("\\Trash",))
    ids = await ids_by_subject(imap_services, imap_account_id)
    await imap_services.mailbox.delete_message(
        ADMIN, imap_account_id, ids["Mail 3"], False
    )
    trashed = await imap_services.mailbox.get_message(
        ADMIN, imap_account_id, ids["Mail 3"]
    )
    assert trashed.folder_ids == [mappers.folder_id("Trash")]
    await imap_services.mailbox.delete_message(
        ADMIN, imap_account_id, ids["Mail 3"], True
    )
    with pytest.raises(NotFoundError):
        await imap_services.mailbox.get_message(ADMIN, imap_account_id, ids["Mail 3"])


async def test_a_batch_move_keeps_every_id(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    ids = await ids_by_subject(imap_services, imap_account_id)
    wanted = [ids["Mail 1"], ids["Mail 2"], ids["Mail 4"]]
    result = await imap_services.mailbox.batch_messages(
        ADMIN,
        imap_account_id,
        MessageBatch(
            action="update", ids=wanted, changes=MessageUpdate(folder_ids=[ARCHIVE])
        ),
    )
    assert [r.id for r in result.results] == wanted
    assert all(r.ok and r.message and r.message.id == r.id for r in result.results)
    for message_id in wanted:
        message = await imap_services.mailbox.get_message(
            ADMIN, imap_account_id, message_id
        )
        assert message.folder_ids == [ARCHIVE]


async def test_a_batch_finds_messages_moved_by_others(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    await imap_services.sync.sync_account(imap_account_id)
    ids = await ids_by_subject(imap_services, imap_account_id)
    server.other_client_moves("INBOX", 2, "Archive", 7)
    result = await imap_services.mailbox.batch_messages(
        ADMIN,
        imap_account_id,
        MessageBatch(
            action="update",
            ids=[ids["Mail 1"], ids["Mail 2"]],
            changes=MessageUpdate(starred=True),
        ),
    )
    assert [r.ok for r in result.results] == [True, True]
    assert result.results[1].message is not None
    assert result.results[1].message.folder_ids == [ARCHIVE]


async def test_renaming_a_folder_keeps_the_ids_inside(
    imap_services: Services, imap_account_id: str, server: FakeMailBox
) -> None:
    server.folders["Projekte"] = FakeFolder()
    projects = mappers.folder_id("Projekte")
    ids = await ids_by_subject(imap_services, imap_account_id)
    await imap_services.mailbox.update_message(
        ADMIN, imap_account_id, ids["Mail 2"], MessageUpdate(folder_ids=[projects])
    )
    await imap_services.sync.sync_account(imap_account_id)
    renamed = await imap_services.mailbox.update_folder(
        ADMIN, imap_account_id, projects, FolderUpdate(name="Ablage")
    )
    assert renamed.id == mappers.folder_id("Ablage")
    message = await imap_services.mailbox.get_message(
        ADMIN, imap_account_id, ids["Mail 2"]
    )
    assert message.folder_ids == [renamed.id]
