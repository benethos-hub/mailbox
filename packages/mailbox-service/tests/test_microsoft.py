"""The ``microsoft`` adapter against a Graph mailbox in memory."""

from __future__ import annotations

import base64
from datetime import date
from email import message_from_bytes
from email.policy import default
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.http import ApiClient
from benethos_mailbox_service.data.models import (
    FolderRole,
    MessageFilter,
    MessageUpdate,
    ProviderType,
)
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    MailProvider,
    ProviderSettings,
    TokenSource,
    build_provider,
)
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider, mappers
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_service.data.providers.protocols.oauth import App, OAuthClient
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderUnavailableError,
)
from benethos_mailbox_service.main import build_services, create_app

from .conftest import API_KEY
from .graph_fake import TOKEN, FakeGraph
from .test_oauth import TokenEndpoint, granted, id_token


class Tokens:
    """A token source handing out ``values`` in turn, one per rejection."""

    def __init__(self, *values: str) -> None:
        self.values = list(values)
        self.rejected = 0

    async def access_token(self) -> SecretStr:
        return SecretStr(self.values[0])

    def reject(self) -> None:
        self.rejected += 1
        if len(self.values) > 1:
            self.values.pop(0)


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


def adapter(graph: FakeGraph, tokens: TokenSource | None = None) -> MicrosoftProvider:
    return MicrosoftProvider(
        tokens or Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(graph))
    )


# --- mappers --------------------------------------------------------------------------


def test_a_plain_list_is_ordered_by_date() -> None:
    params, rest = mappers.query(None)
    assert params["$orderby"] == "receivedDateTime desc"
    assert params["$filter"].startswith("receivedDateTime ge 1900-01-01")
    assert rest is None


def test_flags_go_into_the_filter() -> None:
    params, rest = mappers.query(
        MessageFilter(
            unread=True, starred=True, has_attachments=True, after=date(2026, 9, 1)
        )
    )
    assert "isRead eq false" in params["$filter"]
    assert "flag/flagStatus eq 'flagged'" in params["$filter"]
    assert "hasAttachments eq true" in params["$filter"]
    assert "receivedDateTime ge 2026-09-01T00:00:00Z" in params["$filter"]
    assert rest is None


def test_text_goes_into_the_search() -> None:
    params, rest = mappers.query(
        MessageFilter(text='say "hi"', sender="alice", subject="Invoice", unread=True)
    )
    assert "$filter" not in params and "$orderby" not in params
    assert params["$search"] == "\"'say  hi' from:'alice' subject:'Invoice'\""
    assert rest == MessageFilter(unread=True)


def test_system_keywords_are_not_stored() -> None:
    body = mappers.changes(False, True, ["$answered", "Work"])
    assert body == {
        "isRead": True,
        "flag": {"flagStatus": "flagged"},
        "categories": ["Work"],
    }


# --- reading --------------------------------------------------------------------------


async def test_folders_with_their_roles(graph: FakeGraph) -> None:
    projects = graph.new_folder("Projects", graph.root)
    graph.new_folder("Inner", projects)
    folders = {f.name: f for f in await adapter(graph).list_folders()}
    assert folders["Inbox"].role is FolderRole.INBOX
    assert folders["Sentitems"].role is FolderRole.SENT
    assert folders["Deleteditems"].role is FolderRole.TRASH
    assert folders["Projects"].role is None
    assert folders["Inner"].parent_id == projects


async def test_messages_newest_first_and_paged(graph: FakeGraph) -> None:
    first, second, third = (graph.add_message(subject=f"M{n}") for n in range(3))
    provider = adapter(graph)
    page = await provider.list_messages(graph.well_known["inbox"], limit=2, cursor=None)
    assert [m.id for m in page.items] == [third, second]
    assert page.next_cursor is not None and page.next_cursor.startswith("/me/")
    more = await provider.list_messages(None, limit=2, cursor=page.next_cursor)
    assert [m.id for m in more.items] == [first]
    assert more.next_cursor is None


@pytest.mark.parametrize(
    "cursor",
    [
        "https://evil.example/v1.0/me/messages",
        "/v1.0/users/someone/messages",
        "/users/someone/messages",
        "/me/../users/someone/messages",
        "http://graph.microsoft.com/v1.0/me/messages",
    ],
)
async def test_a_forged_cursor_is_refused(graph: FakeGraph, cursor: str) -> None:
    with pytest.raises(BadRequestError, match="invalid cursor"):
        await adapter(graph).list_messages(None, limit=5, cursor=cursor)
    assert graph.requests == []


async def test_a_message(graph: FakeGraph) -> None:
    message_id = graph.add_message(
        hasAttachments=True,
        flag={"flagStatus": "flagged"},
        categories=["Work"],
        body={"contentType": "html", "content": "<p>Hi</p>"},
    )
    graph.attachments[message_id] = [
        {
            "id": "att1",
            "name": "offer.pdf",
            "contentType": "application/pdf",
            "size": 4,
            "isInline": False,
            "contentBytes": base64.b64encode(b"%PDF").decode(),
        }
    ]
    provider = adapter(graph)
    message = await provider.get_message(message_id)
    assert message.sender is not None and message.sender.email == "alice@example.com"
    assert message.unread and message.starred and message.keywords == ["work"]
    assert message.html_body == "<p>Hi</p>" and message.text_body is None
    assert [a.filename for a in message.attachments] == ["offer.pdf"]
    content = await provider.get_attachment(message_id, "att1")
    assert content.data == b"%PDF"
    assert (await provider.get_raw(message_id)).startswith(b"Message-ID:")


async def test_every_call_asks_for_immutable_ids(graph: FakeGraph) -> None:
    await adapter(graph).list_folders()
    assert all(r.headers["prefer"] == 'IdType="ImmutableId"' for r in graph.requests)


# --- changing -------------------------------------------------------------------------


async def test_flags_and_move_keep_the_id(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    archive = graph.new_folder("Archive", graph.root)
    results = await adapter(graph).update_messages(
        [message_id, "missing"],
        MessageUpdate(unread=False, starred=True, folder_ids=[archive]),
    )
    moved = results[message_id]
    assert not isinstance(moved, Exception)
    assert moved.id == message_id and moved.folder_ids == [archive]
    assert not moved.unread and moved.starred
    assert isinstance(results["missing"], NotFoundError)


async def test_trash_then_for_good(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    provider = adapter(graph)
    [trashed] = (await provider.delete_messages([message_id], permanent=False)).values()
    assert not isinstance(trashed, Exception) and trashed is not None
    assert trashed.folder_ids == [graph.well_known["deleteditems"]]
    [again] = (await provider.delete_messages([message_id], permanent=False)).values()
    assert isinstance(again, ConflictError)
    [gone] = (await provider.delete_messages([message_id], permanent=True)).values()
    assert gone is None and message_id not in graph.messages


async def test_message_headers_come_in_one_batch(graph: FakeGraph) -> None:
    ids = [graph.add_message(subject=f"m{n}") for n in range(3)]
    provider = adapter(graph)
    before = len(graph.requests)  # the fake answers a batch through itself
    found = await provider.message_headers([*ids, "AAMk999="])
    posted = [r for r in graph.requests[before:] if r.method == "POST"]
    assert [r.url.path for r in posted] == ["/v1.0/$batch"]
    assert set(found) == set(ids)
    assert all(v is not None and v.startswith("<") for v in found.values())


async def test_for_good_from_the_inbox(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    provider = adapter(graph)
    [gone] = (await provider.delete_messages([message_id], permanent=True)).values()
    assert gone is None and message_id not in graph.messages


async def test_a_top_level_rename_does_not_move(graph: FakeGraph) -> None:
    provider = adapter(graph)
    top = await provider.create_folder("Work", None)
    await provider.update_folder(top.id, "Working", None)
    moves = [r for r in graph.requests if r.url.path.endswith("/move")]
    assert moves == []


async def test_graph_asking_to_wait_is_left_alone(graph: FakeGraph) -> None:
    now = [0.0]
    provider = MicrosoftProvider(
        Tokens(TOKEN),
        ApiClient(transport=httpx.MockTransport(graph)),
        clock=lambda: now[0],
    )
    graph.next_answer = httpx.Response(
        429,
        json={"error": {"code": "TooManyRequests", "message": "slow down"}},
        headers={"Retry-After": "30"},
    )
    with pytest.raises(ProviderUnavailableError, match="retry after 30s"):
        await provider.list_folders()
    before = len(graph.requests)  # the fake answers a batch through itself
    with pytest.raises(ProviderUnavailableError, match="next attempt in 30s"):
        await provider.list_folders()
    assert len(graph.requests) == before
    now[0] += 31
    await provider.list_folders()


async def test_folders_are_created_renamed_moved_deleted(graph: FakeGraph) -> None:
    provider = adapter(graph)
    top = await provider.create_folder("Work", None)
    inner = await provider.create_folder("Inner", top.id)
    assert inner.parent_id == top.id
    renamed = await provider.update_folder(inner.id, "Inside", top.id)
    assert renamed.name == "Inside" and renamed.id == inner.id
    lifted = await provider.update_folder(inner.id, "Inside", None)
    assert lifted.parent_id == graph.root
    assert await provider.folder_contents(inner.id) == []
    await provider.delete_folder(inner.id)
    assert inner.id not in graph.folders


# --- sending and drafts ---------------------------------------------------------------


async def test_send_puts_hidden_recipients_in_bcc(graph: FakeGraph) -> None:
    raw = b"From: me@example.org\r\nTo: bob@example.org\r\nSubject: Hi\r\n\r\nHello\r\n"
    await adapter(graph).send(
        raw, "me@example.org", ["bob@example.org", "carol@example.org"]
    )
    [sent] = graph.sent
    parsed = message_from_bytes(sent, policy=default)
    assert parsed["To"] == "bob@example.org"
    assert parsed["Bcc"] == "carol@example.org"
    assert parsed.get_content().strip() == "Hello"


async def test_drafts(graph: FakeGraph) -> None:
    provider = adapter(graph)
    raw = (
        b"From: me@example.org\r\nTo: bob@example.org\r\nSubject: Plan\r\n"
        b"X-Mailbox-Api-Reference: reply AAMk1=\r\nIn-Reply-To: <x@example.com>\r\n"
        b"Content-Type: text/plain\r\n\r\nFirst\r\n"
    )
    saved = await provider.save_draft(raw, None)
    assert "$draft" in saved.keywords
    listed = await provider.list_drafts(limit=10, cursor=None)
    assert [m.id for m in listed.items] == [saved.id]
    draft = await provider.get_message(saved.id)
    assert draft.reference is not None and draft.reference.message_id == "AAMk1="
    assert draft.in_reply_to == "<x@example.com>"
    replaced = await provider.save_draft(raw.replace(b"First", b"Second"), saved.id)
    assert saved.id not in graph.messages
    assert b"Second" in await provider.get_draft(replaced.id)
    await provider.delete_draft(replaced.id)
    assert replaced.id not in graph.messages


async def test_draft_calls_reach_drafts_only(graph: FakeGraph) -> None:
    inbox_mail = graph.add_message()
    provider = adapter(graph)
    for call in (provider.get_draft(inbox_mail), provider.delete_draft(inbox_mail)):
        with pytest.raises(NotFoundError):
            await call
    assert inbox_mail in graph.messages


# --- tokens and failures --------------------------------------------------------------


async def test_a_refused_token_is_renewed_once(graph: FakeGraph) -> None:
    tokens = Tokens("stale", TOKEN)
    await adapter(graph, tokens).verify()
    assert tokens.rejected == 1


async def test_refused_twice_asks_for_a_new_sign_in(graph: FakeGraph) -> None:
    tokens = Tokens("stale", "also-stale")
    with pytest.raises(ProviderAuthError, match="sign in again"):
        await adapter(graph, tokens).verify()
    assert tokens.rejected == 1


async def test_throttling() -> None:
    def busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "7"},
            json={"error": {"code": "ApplicationThrottled", "message": "slow down"}},
        )

    provider = MicrosoftProvider(
        Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(busy))
    )
    with pytest.raises(ProviderUnavailableError, match="retry after 7s"):
        await provider.list_folders()


def test_without_an_oauth_app_there_is_no_adapter() -> None:
    with pytest.raises(NotSupportedError, match="no OAuth app"):
        build_provider(ProviderType.MICROSOFT, {}, lambda field: SecretStr(""))


# --- through the whole service ------------------------------------------------------


def test_connect_read_and_send_through_the_api(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))
    graph.add_message(subject="Welcome")
    endpoint = TokenEndpoint(
        granted(TOKEN, "rt-1", id_token=id_token(email="me@example.org")),
        # The account's own adapter renews once, from the stored token.
        granted(TOKEN, "rt-2"),
    )

    def factory(
        kind: ProviderType,
        settings: ProviderSettings,
        credentials: CredentialReader,
        /,
        *,
        tokens: TokenSource | None = None,
    ) -> MailProvider:
        assert kind is ProviderType.MICROSOFT and tokens is not None
        return MicrosoftProvider(
            tokens, ApiClient(transport=httpx.MockTransport(graph))
        )

    config = Settings(storage="memory", api_key=SecretStr(API_KEY))
    app = App(microsoft_endpoints(), "client-1", SecretStr("secret"))
    services = build_services(
        config,
        provider_factory=factory,
        oauth_clients={
            ProviderType.MICROSOFT: OAuthClient(
                app, ApiClient(transport=httpx.MockTransport(endpoint))
            )
        },
    )
    services.vault.initialize()
    client = TestClient(
        create_app(config, services), headers={"Authorization": f"Bearer {API_KEY}"}
    )
    from urllib.parse import parse_qs, urlsplit

    started = client.post("/v1/oauth/microsoft/start", json={}).json()["url"]
    state = parse_qs(urlsplit(started).query)["state"][0]
    import anyio

    caller = services.auth.authenticate(API_KEY)
    account = anyio.run(
        lambda: services.oauth.finish(caller, ProviderType.MICROSOFT, state, "code")
    )
    base = f"/v1/accounts/{account.id}"
    roles = {f["role"] for f in client.get(f"{base}/folders").json()}
    assert {"inbox", "sent", "drafts", "trash"} <= roles
    listed = client.get(f"{base}/messages", params={"folder": "inbox"}).json()
    assert [m["subject"] for m in listed["items"]] == ["Welcome"]
    sent = client.post(
        f"{base}/send",
        json={"to": [{"email": "bob@example.org"}], "subject": "Hi", "text": "Hello"},
    )
    assert sent.status_code == 200, sent.text
    [raw] = graph.sent
    assert message_from_bytes(raw)["Subject"] == "Hi"
    draft = client.post(
        f"{base}/drafts", json={"to": [{"email": "bob@example.org"}], "text": "Later"}
    )
    assert draft.status_code == 201, draft.text
    listed_drafts: Any = client.get(f"{base}/drafts").json()
    assert [d["id"] for d in listed_drafts["items"]] == [draft.json()["id"]]


async def test_search_results_come_under_immutable_ids(graph: FakeGraph) -> None:
    wanted = graph.add_message(subject="Invoice 7")
    graph.add_message(subject="Other")
    provider = adapter(graph)
    page = await provider.list_messages(
        graph.well_known["inbox"],
        limit=10,
        cursor=None,
        search=MessageFilter(subject="invoice"),
    )
    assert [m.id for m in page.items] == [wanted]
    batches = [r for r in graph.requests if r.url.path.endswith("/$batch")]
    assert len(batches) == 1


async def test_many_search_results_go_in_batches_of_twenty(graph: FakeGraph) -> None:
    wanted = {graph.add_message(subject=f"Invoice {n}") for n in range(25)}
    page = await adapter(graph).list_messages(
        None, limit=30, cursor=None, search=MessageFilter(subject="invoice")
    )
    assert {m.id for m in page.items} == wanted
    assert len([r for r in graph.requests if r.url.path.endswith("/$batch")]) == 2


async def test_a_search_result_in_two_folders_keeps_its_own(graph: FakeGraph) -> None:
    """The same Message-ID in Sent Items and the inbox, e.g. a mail to
    oneself: each result is looked up in its own folder."""
    header = "<same@example.com>"
    inbox = graph.add_message(subject="To me", internetMessageId=header)
    sent = graph.add_message("sentitems", subject="To me", internetMessageId=header)
    provider = adapter(graph)
    found = await provider.list_messages(
        None, limit=10, cursor=None, search=MessageFilter(subject="to me")
    )
    assert {m.id for m in found.items} == {inbox, sent}
