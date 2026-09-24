"""Drafts (CONCEPT 6.4): stored in the drafts folder, reached only there."""

from __future__ import annotations

from datetime import UTC, datetime
from email import message_from_bytes

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.mail import compose
from benethos_mailbox_api.data.models import (
    DraftMessage,
    Folder,
    FolderRole,
    Grant,
    ProviderType,
    Recipient,
)
from benethos_mailbox_api.data.providers import (
    CredentialReader,
    MailProvider,
    MemoryProvider,
    ProviderSettings,
)
from benethos_mailbox_api.data.providers.imap import ImapProvider, mappers
from benethos_mailbox_api.data.providers.protocols.imap import ImapSession
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
from benethos_mailbox_api.errors import ConflictError, NotFoundError
from benethos_mailbox_api.main import Services, build_services

from .conftest import ADMIN, bearer_for, create_account
from .imap_fake import FakeFolder, FakeMailBox, make_message
from .test_imap import provider

SENDER = Recipient(email="me@example.com", name="Me")
WHEN = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def draft_bytes(subject: str = "Plan", reference: str | None = None) -> bytes:
    return compose.message(
        DraftMessage(
            to=[Recipient(email="bob@example.com")],
            bcc=[Recipient(email="carol@example.com")],
            subject=subject,
            text="Draft text",
        ),
        SENDER,
        WHEN,
        compose.new_message_id(SENDER.email),
        draft=True,
        reference=reference,
    )


@pytest.fixture
def box() -> FakeMailBox:
    box = FakeMailBox()
    box.folders = {
        "INBOX": FakeFolder(uidvalidity=7),
        "Drafts": FakeFolder(uidvalidity=3, flags=("\\Drafts",)),
    }
    box.add("INBOX", 1, make_message("Not a draft"))
    return box


# --- the message format -----------------------------------------------------------


def test_a_draft_keeps_bcc_and_reference_until_it_is_sent() -> None:
    raw = draft_bytes(reference="reply msg_1")
    stored = message_from_bytes(raw)
    assert stored["Bcc"] == "carol@example.com"
    assert stored[compose.REFERENCE_HEADER] == "reply msg_1"

    later = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
    out, recipients, reference = compose.outgoing(raw, later)
    sent = message_from_bytes(out)
    assert recipients == ["bob@example.com", "carol@example.com"]
    assert reference == "reply msg_1"
    assert sent["Bcc"] is None and sent[compose.REFERENCE_HEADER] is None
    assert sent["Date"] == "Fri, 25 Sep 2026 08:00:00 +0000"
    assert sent["Message-ID"] == stored["Message-ID"]


def test_a_message_to_send_keeps_no_bcc_header() -> None:
    raw = compose.message(
        DraftMessage(bcc=[Recipient(email="carol@example.com")], text="x"),
        SENDER,
        WHEN,
        "<1@example.com>",
    )
    assert message_from_bytes(raw)["Bcc"] is None


# --- the IMAP adapter ---------------------------------------------------------------


async def test_a_draft_is_stored_in_the_drafts_folder(box: FakeMailBox) -> None:
    saved = await provider(box).save_draft(draft_bytes(), None)
    assert saved.folder_ids == [mappers.folder_id("Drafts")]
    assert saved.subject == "Plan"
    assert "$draft" in saved.keywords
    assert ("append", "Drafts", ("\\Draft", "\\Seen")) in box.calls


async def test_replacing_a_draft_removes_the_old_one(box: FakeMailBox) -> None:
    imap = provider(box)
    first = await imap.save_draft(draft_bytes("One"), None)
    second = await imap.save_draft(draft_bytes("Two"), first.id)
    page = await imap.list_drafts(limit=10, cursor=None)
    assert [m.subject for m in page.items] == ["Two"]
    assert second.id != first.id
    with pytest.raises(NotFoundError):
        await imap.get_draft(first.id)


async def test_a_draft_reads_back_as_stored(box: FakeMailBox) -> None:
    imap = provider(box)
    saved = await imap.save_draft(draft_bytes(), None)
    raw = await imap.get_draft(saved.id)
    assert message_from_bytes(raw)["Bcc"] == "carol@example.com"


async def test_draft_operations_reach_no_other_mail(box: FakeMailBox) -> None:
    imap = provider(box)
    inbox_mail = mappers.message_id("INBOX", 7, 1)
    with pytest.raises(NotFoundError):
        await imap.get_draft(inbox_mail)
    with pytest.raises(NotFoundError):
        await imap.delete_draft(inbox_mail)
    with pytest.raises(NotFoundError):
        await imap.save_draft(draft_bytes(), inbox_mail)
    with pytest.raises(NotFoundError):
        await imap.delete_draft("not an id")
    assert 1 in box.folders["INBOX"].messages
    assert not [c for c in box.calls if c[0] == "append"]


async def test_a_deleted_draft_is_gone(box: FakeMailBox) -> None:
    imap = provider(box)
    saved = await imap.save_draft(draft_bytes(), None)
    await imap.delete_draft(saved.id)
    assert not box.folders["Drafts"].messages
    with pytest.raises(NotFoundError):
        await imap.delete_draft(saved.id)


async def test_without_a_drafts_folder(box: FakeMailBox) -> None:
    del box.folders["Drafts"]
    with pytest.raises(ConflictError):
        await provider(box).save_draft(draft_bytes(), None)


# --- the memory adapter -------------------------------------------------------------


async def test_memory_drafts() -> None:
    memory = MemoryProvider()
    saved = await memory.save_draft(draft_bytes("One"), None)
    replaced = await memory.save_draft(draft_bytes("Two"), saved.id)
    page = await memory.list_drafts(limit=10, cursor=None)
    assert [m.subject for m in page.items] == ["Two"]
    assert message_from_bytes(await memory.get_draft(replaced.id))["Subject"] == "Two"
    await memory.delete_draft(replaced.id)
    assert not (await memory.list_drafts(limit=10, cursor=None)).items


async def test_memory_drafts_reach_no_other_mail() -> None:
    memory = MemoryProvider(
        folders=[Folder(id="inbox", name="Inbox", role=FolderRole.INBOX)]
    )
    with pytest.raises(ConflictError):
        await memory.list_drafts(limit=10, cursor=None)
    memory.folders.append(Folder(id="drafts", name="Drafts", role=FolderRole.DRAFTS))
    with pytest.raises(NotFoundError):
        await memory.delete_draft("m0")


# --- the API ------------------------------------------------------------------------


def drafts_url(account_id: str, draft_id: str = "") -> str:
    return f"/v1/accounts/{account_id}/drafts" + (f"/{draft_id}" if draft_id else "")


def test_a_draft_through_its_life(client: TestClient, account_id: str) -> None:
    created = client.post(
        drafts_url(account_id),
        json={"subject": "Plan", "text": "First", "bcc": [{"email": "c@example.com"}]},
    )
    assert created.status_code == 201
    draft_id = created.json()["id"]
    listed = client.get(drafts_url(account_id)).json()["items"]
    assert [d["id"] for d in listed] == [draft_id]

    replaced = client.put(
        drafts_url(account_id, draft_id),
        json={"to": [{"email": "bob@example.com"}], "subject": "Plan B", "text": "x"},
    )
    assert replaced.status_code == 200
    assert replaced.json()["id"] == draft_id
    message = client.get(f"/v1/accounts/{account_id}/messages/{draft_id}").json()
    assert message["subject"] == "Plan B"
    assert message["to"] == [{"email": "bob@example.com", "name": None}]

    assert client.delete(drafts_url(account_id, draft_id)).status_code == 204
    assert client.delete(drafts_url(account_id, draft_id)).status_code == 404
    assert client.get(drafts_url(account_id)).json()["items"] == []


def test_a_reply_draft_keeps_its_reference(client: TestClient, account_id: str) -> None:
    created = client.post(
        drafts_url(account_id),
        json={"reference": {"message_id": "m1", "action": "reply"}, "text": "Gern."},
    ).json()
    assert created["subject"] == "Re: Invoice 1"
    raw = client.get(f"/v1/accounts/{account_id}/messages/{created['id']}/raw")
    stored = message_from_bytes(raw.content)
    assert stored[compose.REFERENCE_HEADER] == "reply m1"
    assert stored["To"] == "Alice <alice@example.com>"
    assert "> body 1" in stored.get_payload()


def test_draft_routes_reach_no_other_mail(client: TestClient, account_id: str) -> None:
    body = {"subject": "Overwrite", "text": "x"}
    assert client.put(drafts_url(account_id, "m1"), json=body).status_code == 404
    assert client.delete(drafts_url(account_id, "m1")).status_code == 404
    assert client.get(f"/v1/accounts/{account_id}/messages/m1").status_code == 200


def test_drafts_is_a_right_of_its_own(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    drafter = bearer_for(services, Grant(accounts=[account_id], allow=["drafts"]))
    created = app_client.post(
        drafts_url(account_id), json={"text": "x"}, headers=drafter
    )
    assert created.status_code == 201
    # A reference quotes the original: reading it is a right of its own.
    reply = {"reference": {"message_id": "m1", "action": "reply"}, "text": "x"}
    answer = app_client.post(drafts_url(account_id), json=reply, headers=drafter)
    assert answer.status_code == 403
    assert "get_message" in answer.json()["error"]["message"]

    reader = bearer_for(services, Grant(accounts=[account_id], allow=["mail.read"]))
    answer = app_client.post(drafts_url(account_id), json={"text": "x"}, headers=reader)
    assert answer.status_code == 403


# --- ids on IMAP: a replaced draft is a new message, its id stays --------------------


@pytest.fixture
def on_imap(box: FakeMailBox, monkeypatch: pytest.MonkeyPatch) -> tuple[Services, str]:
    monkeypatch.setenv("MAILBOX_API_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> MailProvider:
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=box),
            sleep=lambda seconds: None,
        )

    services = build_services(Settings(storage="memory"), provider_factory=factory)
    services.vault.initialize()
    account = create_account(
        services.accounts,
        ProviderType.IMAP,
        "me@example.com",
        settings={"host": "imap.example.com", "username": "me@example.com"},
        credentials={"password": SecretStr("secret")},
    )
    return services, account.id


async def test_a_replaced_draft_keeps_its_id(
    box: FakeMailBox, on_imap: tuple[Services, str]
) -> None:
    services, account_id = on_imap
    mailbox = services.mailbox
    first = await mailbox.create_draft(
        ADMIN, account_id, DraftMessage(subject="One", text="x")
    )
    second = await mailbox.update_draft(
        ADMIN, account_id, first.id, DraftMessage(subject="Two", text="y")
    )
    assert second.id == first.id
    assert list(box.folders["Drafts"].messages) == [2]
    message = await mailbox.get_message(ADMIN, account_id, first.id)
    assert message.subject == "Two"
    listed = await mailbox.list_drafts(ADMIN, account_id, limit=10, cursor=None)
    assert [d.id for d in listed.items] == [first.id]

    await mailbox.delete_draft(ADMIN, account_id, first.id)
    assert not box.folders["Drafts"].messages
    with pytest.raises(NotFoundError):
        await mailbox.get_message(ADMIN, account_id, first.id)


async def test_a_draft_id_that_left_the_drafts_folder(
    box: FakeMailBox, on_imap: tuple[Services, str]
) -> None:
    """Another client moved the draft away: it is no draft any more."""
    services, account_id = on_imap
    draft = await services.mailbox.create_draft(
        ADMIN, account_id, DraftMessage(subject="One", text="x")
    )
    box.other_client_moves("Drafts", 1, "INBOX", 2)
    with pytest.raises(NotFoundError):
        await services.mailbox.delete_draft(ADMIN, account_id, draft.id)
    assert box.folders["INBOX"].messages
