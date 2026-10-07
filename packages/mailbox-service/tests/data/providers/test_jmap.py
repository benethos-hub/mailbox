"""The ``jmap`` adapter against a JMAP server in memory: settings and
sign-in, folders, listing and reading, and the mappers."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime
from typing import Any

import anyio
import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.models import (
    CredentialKind,
    FolderRole,
    MailServer,
    MessageFilter,
    MessageUpdate,
    ProviderType,
    Security,
    ServerProtocol,
)
from benethos_mailbox_service.data.protocols import ServerClient
from benethos_mailbox_service.data.providers import (
    build_provider,
    settings_from_servers,
)
from benethos_mailbox_service.data.providers.jmap import JmapProvider, mappers
from benethos_mailbox_service.data.providers.jmap.shapes import Email, Mailbox
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
)

from ...imap_fake import make_message
from ...jmap_fake import HOST, PASSWORD, TOKEN, USER, FakeJmap

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def server() -> FakeJmap:
    return FakeJmap()


def adapter(server: FakeJmap, **settings: Any) -> JmapProvider:
    secrets = {"password": PASSWORD, "token": TOKEN}
    return JmapProvider(
        {"host": HOST, "username": USER, **settings},
        lambda field: SecretStr(secrets[field]),
        http=ServerClient(transport=httpx.MockTransport(server)),
        now=lambda: NOW,
    )


@pytest.fixture
def jmap(server: FakeJmap) -> JmapProvider:
    return adapter(server)


def sent_auth(server: FakeJmap) -> str:
    return server.requests[-1].headers["authorization"]


# --- settings and sign-in -------------------------------------------------------------


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"host": ""}, "settings.host"),
        ({"security": "starttls"}, "HTTPS"),
        ({"path": "jmap"}, "settings.path"),
        ({"path": "/a b"}, "settings.path"),
        ({"path": "/x#y"}, "settings.path"),
        ({"auth": "oauth"}, "settings.auth"),
        ({"username": ""}, "settings.username"),
        ({"port": "0"}, "port"),
    ],
)
def test_settings_are_checked(
    server: FakeJmap, settings: dict[str, Any], message: str
) -> None:
    with pytest.raises(BadRequestError, match=message):
        adapter(server, **settings)


async def test_a_password_signs_in_with_basic(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    await jmap.verify()
    pair = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    assert sent_auth(server) == f"Basic {pair}"
    # The session's URLs are used on the server the account names.
    assert {r.headers["host"] for r in server.requests} == {HOST}
    assert [r.url.path for r in server.requests[:2]] == [
        "/.well-known/jmap",
        "/jmap/session",
    ]


async def test_a_token_signs_in_with_bearer(server: FakeJmap) -> None:
    jmap = adapter(server, auth="token", username="")
    await jmap.verify()
    assert sent_auth(server) == f"Bearer {TOKEN}"


async def test_a_refused_credential_needs_a_new_one(server: FakeJmap) -> None:
    jmap = JmapProvider(
        {"host": HOST, "username": USER},
        lambda field: SecretStr("wrong"),
        http=ServerClient(transport=httpx.MockTransport(server)),
    )
    with pytest.raises(ProviderAuthError, match="refused the credential"):
        await jmap.verify()


async def test_a_server_without_mail_is_refused(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    del server.capabilities["urn:ietf:params:jmap:mail"]
    with pytest.raises(ProviderError, match="no JMAP mail"):
        await jmap.verify()


def test_settings_from_discovered_servers() -> None:
    server = MailServer(
        protocol=ServerProtocol.JMAP,
        host="jmap.example.org",
        port=443,
        security=Security.TLS,
        path="/jmap/session",
        username="me@example.org",
    )
    password = settings_from_servers(
        ProviderType.JMAP, [server], CredentialKind.PASSWORD, "me@example.org"
    )
    assert password == {
        "host": "jmap.example.org",
        "port": 443,
        "path": "/jmap/session",
        "username": "me@example.org",
    }
    token = settings_from_servers(
        ProviderType.JMAP,
        [server.model_copy(update={"path": None})],
        CredentialKind.API_TOKEN,
        "me@example.org",
    )
    assert token == {
        "host": "jmap.example.org",
        "port": 443,
        "path": "/.well-known/jmap",
        "auth": "token",
    }
    assert (
        settings_from_servers(ProviderType.JMAP, [], CredentialKind.PASSWORD, "a@b.c")
        == {}
    )


def test_the_registry_builds_it() -> None:
    built = build_provider(
        ProviderType.JMAP, {"host": HOST, "username": USER}, lambda f: SecretStr("x")
    )
    assert isinstance(built, JmapProvider)


# --- folders --------------------------------------------------------------------------


async def test_folders_with_roles(jmap: JmapProvider, server: FakeJmap) -> None:
    server.add_email(make_message("One"))
    folders = {f.id: f for f in await jmap.list_folders()}
    assert folders["inbox"].role is FolderRole.INBOX
    assert folders["trash"].role is FolderRole.TRASH
    assert folders["inbox"].total == 1 and folders["inbox"].unread == 1
    assert folders["inbox"].subscribed is True


async def test_create_rename_move_and_delete_a_folder(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    made = await jmap.create_folder("Projects", None)
    assert made.name == "Projects" and made.parent_id is None and made.subscribed
    child = await jmap.create_folder("Old", made.id)
    assert child.parent_id == made.id
    with pytest.raises(ConflictError, match="exists there already"):
        await jmap.create_folder("Old", made.id)
    with pytest.raises(NotFoundError):
        await jmap.create_folder("New", "nowhere")
    renamed = await jmap.update_folder(child.id, "Older", None)
    assert renamed.name == "Older" and renamed.parent_id is None
    assert (await jmap.update_folder(child.id, "Older", None)) == renamed
    with pytest.raises(BadRequestError, match="into itself"):
        await jmap.update_folder(made.id, "Projects", made.id)
    await jmap.update_folder(child.id, "Older", made.id)
    with pytest.raises(BadRequestError, match="into itself"):
        await jmap.update_folder(made.id, "Projects", child.id)
    with pytest.raises(NotFoundError):
        await jmap.update_folder("nowhere", "X", None)
    server.refuse_set[made.id] = {"type": "forbidden", "description": "no"}
    with pytest.raises(ConflictError, match="no"):
        await jmap.update_folder(made.id, "Renamed", None)
    await jmap.delete_folder(child.id)
    assert child.id not in server.mailboxes
    with pytest.raises(NotFoundError):
        await jmap.delete_folder(child.id)
    with pytest.raises(NotFoundError):
        await jmap.delete_folder("not an id")


async def test_a_folder_with_mail_is_not_deleted(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    folder = await jmap.create_folder("Keep", None)
    server.add_email(make_message("Kept"), folder.id)
    with pytest.raises(ConflictError, match="mailboxHasEmail"):
        await jmap.delete_folder(folder.id)


async def test_a_folder_the_server_refuses_to_create(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.method_errors["Mailbox/set"] = "forbidden"
    with pytest.raises(ProviderAuthError):
        await jmap.create_folder("No", None)


# --- listing and reading --------------------------------------------------------------


async def test_list_newest_first_in_pages(jmap: JmapProvider, server: FakeJmap) -> None:
    ids = [server.add_email(make_message(f"Mail {n}")) for n in range(5)]
    first = await jmap.list_messages("inbox", limit=2, cursor=None)
    assert [m.id for m in first.items] == [ids[4], ids[3]]
    assert first.next_cursor
    second = await jmap.list_messages("inbox", limit=2, cursor=first.next_cursor)
    assert [m.id for m in second.items] == [ids[2], ids[1]]
    # The last message of the page is gone: the next one moved up.
    server.other_client_deletes(ids[1])
    third = await jmap.list_messages("inbox", limit=2, cursor=second.next_cursor)
    assert [m.id for m in third.items] == [ids[0]]
    assert third.next_cursor is None


async def test_a_cursor_belongs_to_its_folder_and_search(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    for n in range(3):
        server.add_email(make_message(f"Mail {n}"))
    page = await jmap.list_messages("inbox", limit=1, cursor=None)
    assert page.next_cursor
    with pytest.raises(BadRequestError, match="cursor"):
        await jmap.list_messages("trash", limit=1, cursor=page.next_cursor)
    with pytest.raises(BadRequestError, match="cursor"):
        await jmap.list_messages(
            "inbox", limit=1, cursor=page.next_cursor, search=MessageFilter(text="x")
        )
    with pytest.raises(BadRequestError, match="cursor"):
        await jmap.list_messages("inbox", limit=1, cursor="c_garbage")
    with pytest.raises(NotFoundError):
        await jmap.list_messages("no such/folder", limit=1, cursor=None)


async def test_a_server_that_caps_the_page(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    for n in range(4):
        server.add_email(make_message(f"Mail {n}"))
    server.query_cap = 2
    page = await jmap.list_messages("inbox", limit=3, cursor=None)
    assert len(page.items) == 2 and page.next_cursor


async def test_without_a_folder_every_folder(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.add_email(make_message("In"))
    server.add_email(make_message("Gone"), "trash")
    page = await jmap.list_messages(None, limit=10, cursor=None)
    assert {m.subject for m in page.items} == {"In", "Gone"}


async def test_summary_fields(jmap: JmapProvider, server: FakeJmap) -> None:
    server.add_email(
        make_message("Hello", text="Hi there", date=NOW),
        keywords={"$seen": True, "$flagged": True, "$forwarded": True, "Work": True},
    )
    [summary] = (await jmap.list_messages("inbox", limit=5, cursor=None)).items
    assert summary.subject == "Hello" and summary.sender is not None
    assert summary.sender.email == "alice@example.com"
    assert summary.to[0].email == "me@example.com"
    assert summary.unread is False and summary.starred is True
    assert summary.keywords == ["$forwarded", "work"]
    assert summary.folder_ids == ["inbox"] and summary.date == NOW
    assert summary.snippet and summary.thread_id


@pytest.mark.parametrize(
    ("search", "subjects"),
    [
        (MessageFilter(text="needle"), {"Needle"}),
        (MessageFilter(sender="bob"), {"From Bob"}),
        (MessageFilter(to="carol"), {"To Carol"}),
        (MessageFilter(subject="needle"), {"Needle"}),
        (MessageFilter(unread=False), {"Read"}),
        (MessageFilter(unread=True, starred=False), {"Needle", "From Bob", "To Carol"}),
        (MessageFilter(starred=True), {"Read"}),
        (MessageFilter(has_attachments=True), {"To Carol"}),
        (MessageFilter(after=date(2026, 9, 3)), {"To Carol", "Read"}),
        (MessageFilter(before=date(2026, 9, 2)), {"Needle"}),
    ],
)
async def test_search(
    jmap: JmapProvider, server: FakeJmap, search: MessageFilter, subjects: set[str]
) -> None:
    server.add_email(make_message("Needle", text="a needle here"))
    server.add_email(make_message("From Bob", sender="bob@example.com"))
    server.add_email(
        make_message(
            "To Carol",
            to="carol@example.com",
            attachments=[("a.txt", "text/plain", b"x")],
        )
    )
    server.add_email(make_message("Read"), keywords={"$seen": True, "$flagged": True})
    page = await jmap.list_messages("inbox", limit=10, cursor=None, search=search)
    assert {m.subject for m in page.items} == subjects


async def test_a_search_the_server_cannot_do(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.method_errors["Email/query"] = "unsupportedFilter"
    with pytest.raises(NotSupportedError):
        await jmap.list_messages("inbox", limit=1, cursor=None)


async def test_read_a_message_its_source_and_attachment(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    raw = make_message(
        "Report",
        text="See attached",
        attachments=[("r.pdf", "application/pdf", b"%PDF")],
    )
    email_id = server.add_email(raw, keywords={"$seen": True})
    message = await jmap.get_message(email_id)
    assert message.text_body and "See attached" in message.text_body
    assert message.unread is False and message.folder_ids == ["inbox"]
    [attachment] = message.attachments
    assert attachment.filename == "r.pdf" and message.has_attachments
    assert await jmap.get_raw(email_id) == raw
    got = await jmap.get_attachment(email_id, attachment.id)
    assert got.data == b"%PDF"
    with pytest.raises(NotFoundError):
        await jmap.get_message("m999")
    with pytest.raises(NotFoundError):
        await jmap.get_message("not/an id")
    del server.blobs[server.emails[email_id]["blobId"]]
    with pytest.raises(NotFoundError):
        await jmap.get_raw(email_id)


# --- mappers --------------------------------------------------------------------------


def test_keyword_patch_escapes_a_pointer() -> None:
    patch = mappers.keyword_patch({"a~b": True}, MessageUpdate(keywords=["x~y"]))
    assert patch == {"keywords/x~0y": True, "keywords/a~0b": None}


def test_dates_the_server_writes_oddly() -> None:
    odd = Email.model_validate({"id": "e", "sentAt": "not a date", "receivedAt": None})
    assert mappers.summary(odd).date is None
    email = Email.model_validate(
        {"id": "e", "sentAt": "soon", "receivedAt": "2026-10-06T10:00:00Z"}
    )
    assert mappers.summary(email).date == datetime(2026, 10, 6, 10, tzinfo=UTC)


def test_what_is_odd_in_an_email_is_left_out() -> None:
    email = Email.model_validate(
        {"id": "e", "from": [{"email": "a@example.org"}, "odd", {"name": "x"}]}
    )
    assert [a.email for a in mappers.summary(email).to] == []
    assert mappers.summary(email).sender is not None


def test_a_folder_with_a_role_the_api_lacks() -> None:
    folder = mappers.folder(Mailbox(id="f", name="Imp", role="important"))
    assert folder.role is None


async def test_timeouts_end_the_wait(jmap: JmapProvider, server: FakeJmap) -> None:
    server.hold = True
    with anyio.fail_after(5):
        assert await jmap.wait_for_change(0.1) is False
