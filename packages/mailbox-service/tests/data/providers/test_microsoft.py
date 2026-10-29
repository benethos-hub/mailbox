"""The ``microsoft`` adapter against a Graph mailbox in memory."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.models import (
    FolderRole,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    ProviderType,
)
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.providers import (
    build_provider,
    rules,
)
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider, mappers
from benethos_mailbox_service.data.providers.microsoft import (
    messages as microsoft_messages,
)
from benethos_mailbox_service.errors import (
    BadRequestError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from ...graph_fake import TOKEN, FakeGraph
from ...microsoft_adapter import adapter
from ...oauth_fake import Tokens

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


def test_a_text_search_for_mail_without_attachments_checks_each_result() -> None:
    params, rest = mappers.query(MessageFilter(text="plan", has_attachments=False))
    assert "hasAttachments" not in params["$search"]
    assert rest == MessageFilter(has_attachments=False)
    with_file = MessageSummary(id="m", folder_ids=[], has_attachments=True)
    assert not mappers.keeps(with_file, rest)
    assert mappers.keeps(with_file.model_copy(update={"has_attachments": False}), rest)
    params, rest = mappers.query(MessageFilter(text="plan", has_attachments=True))
    assert "hasAttachments:true" in params["$search"] and rest is None


def test_text_goes_into_the_search() -> None:
    params, rest = mappers.query(
        MessageFilter(text='say "hi"', sender="alice", subject="Invoice", unread=True)
    )
    assert "$filter" not in params and "$orderby" not in params
    assert params["$search"] == "\"'say  hi' from:'alice' subject:'Invoice'\""
    assert rest == MessageFilter(unread=True)


def test_the_patch_body_leaves_system_keywords_out() -> None:
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


async def test_all_mail_is_every_folder_but_the_trash_and_junk(
    graph: FakeGraph,
) -> None:
    kept = graph.add_message(subject="Kept")
    filed = graph.add_message("sentitems", subject="Filed")
    graph.add_message("deleteditems", subject="Trashed")
    graph.add_message("junkemail", subject="Junk")
    provider = adapter(graph)
    [everything] = [
        f for f in await provider.list_folders() if f.role is FolderRole.ALL
    ]
    assert everything.id == rules.ALL and everything.total is None
    page = await provider.list_messages(rules.ALL, limit=10, cursor=None)
    assert {m.id for m in page.items} == {kept, filed}
    assert rules.ALL not in await provider.folder_states()
    into = await provider.update_messages([kept], MessageUpdate(folder_ids=["all"]))
    assert isinstance(into[kept], BadRequestError)


async def test_messages_newest_first_and_paged(graph: FakeGraph) -> None:
    first, second, third = (graph.add_message(subject=f"M{n}") for n in range(3))
    provider = adapter(graph)
    page = await provider.list_messages(graph.well_known["inbox"], limit=2, cursor=None)
    assert [m.id for m in page.items] == [third, second]
    assert page.next_cursor is not None
    inbox = graph.well_known["inbox"]
    more = await provider.list_messages(inbox, limit=2, cursor=page.next_cursor)
    assert [m.id for m in more.items] == [first]
    assert more.next_cursor is None
    # Graph's next page carries its own query: another folder or search
    # with it would answer the first list's page.
    for folder, search in ((rules.ALL, None), (inbox, MessageFilter(unread=True))):
        with pytest.raises(BadRequestError, match="invalid cursor"):
            await provider.list_messages(
                folder, limit=2, cursor=page.next_cursor, search=search
            )


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
    # As it stands, and wrapped as a cursor of this list would be.
    bound = rules.bound_cursor("m_", rules.cursor_scope(rules.ALL, None), cursor)
    for value in (cursor, bound):
        with pytest.raises(BadRequestError, match="invalid cursor"):
            await adapter(graph).list_messages(rules.ALL, limit=5, cursor=value)
    assert graph.requests == []


async def test_every_call_asks_for_immutable_ids(graph: FakeGraph) -> None:
    await adapter(graph).list_folders()
    assert all(r.headers["prefer"] == 'IdType="ImmutableId"' for r in graph.requests)


# --- sending and drafts ---------------------------------------------------------------


async def test_drafts(graph: FakeGraph) -> None:
    provider = adapter(graph)
    raw = (
        b"From: me@example.org\r\nTo: bob@example.org\r\nSubject: Plan\r\n"
        b"X-Mailbox-Service-Reference: reply AAMk1=\r\nIn-Reply-To: <x@example.com>\r\n"
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


async def test_a_draft_not_replaced_leaves_one(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old one cannot go: the new one goes again, and the error says
    so. Where even that fails, it names the new one."""
    provider = adapter(graph)
    raw = b"Subject: Plan\r\nContent-Type: text/plain\r\n\r\nFirst\r\n"
    saved = await provider.save_draft(raw, None)
    real = microsoft_messages.delete_for_good
    stuck = {saved.id}

    async def delete(graph: Any, message_id: str, trash: str | None = None) -> None:
        if message_id in stuck:
            raise ProviderUnavailableError("graph is busy")
        await real(graph, message_id, trash)

    monkeypatch.setattr(microsoft_messages, "delete_for_good", delete)
    with pytest.raises(ProviderUnavailableError, match="busy"):
        await provider.save_draft(raw, saved.id)
    assert list(graph.messages) == [saved.id]
    # Even the new one cannot go.
    monkeypatch.setattr(
        microsoft_messages, "delete_for_good", lambda graph, *_: delete(graph, saved.id)
    )
    with pytest.raises(ProviderError, match="replacing it stays beside it"):
        await provider.save_draft(raw, saved.id)
    assert len(graph.messages) == 2


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
    await adapter(graph, tokens).list_folders()
    assert tokens.rejected == 1


async def test_refused_twice_asks_for_a_new_sign_in(graph: FakeGraph) -> None:
    tokens = Tokens("stale", "also-stale")
    with pytest.raises(ProviderAuthError, match="sign in again"):
        await adapter(graph, tokens).list_folders()
    assert tokens.rejected == 1


async def test_verify_asks_a_refused_refresh_again(graph: FakeGraph) -> None:
    tokens = Tokens(TOKEN)
    await adapter(graph, tokens).verify()
    assert tokens.forgotten == 1


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
        rules.ALL, limit=30, cursor=None, search=MessageFilter(subject="invoice")
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
        rules.ALL, limit=10, cursor=None, search=MessageFilter(subject="to me")
    )
    assert {m.id for m in found.items} == {inbox, sent}


@pytest.mark.parametrize(
    ("status", "error", "message"),
    [
        (401, ProviderAuthError, "sign in again"),
        (403, ProviderError, "Access is denied"),
        (404, NotFoundError, "ErrorItemNotFound"),
    ],
)
async def test_what_graph_refuses(
    status: int, error: type[Exception], message: str
) -> None:
    """A 403 is a refused request, as on every provider: the token
    passed."""
    code = {403: "ErrorAccessDenied", 404: "ErrorItemNotFound"}.get(status, "x")
    body = {"error": {"code": code, "message": "Access is denied."}}
    answer = httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    graph = MicrosoftProvider(Tokens(TOKEN), ApiClient(transport=answer))
    with pytest.raises(error, match=message):
        await graph.get_raw("AAMk")
