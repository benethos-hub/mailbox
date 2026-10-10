"""Messages: the lists, one message, changes, flags and moves, deleting,
the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from benethos_mailbox_client import (
    Address,
    ApiError,
    AttachedFile,
    Change,
    Changes,
    Failed,
    Message,
    MessageSummary,
    Outcome,
    Page,
    Reference,
)

from ..fake_api import MESSAGE, PAGE, SUMMARY, FakeApi

AT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
# SUMMARY and MESSAGE of fake_api, as the client reads them.
READ_SUMMARY = MessageSummary(
    id="msg_1",
    account_id="acc_1",
    thread_id="thr_1",
    folder_ids=["fld_1"],
    subject="Hi",
    sender=Address("a@example.com", "Ann"),
    to=[Address("me@example.com")],
    date=AT,
    snippet="Hello",
    unread=True,
    starred=False,
    keywords=["work"],
    has_attachments=True,
)
READ_MESSAGE = Message(
    **{name: getattr(READ_SUMMARY, name) for name in READ_SUMMARY.__slots__},
    cc=[Address("c@example.com")],
    bcc=[],
    reply_to=[],
    message_id_header="<m1@example.com>",
    in_reply_to=None,
    text_body="Hello",
    html_body="<p>Hello</p>",
    attachments=[AttachedFile("att_0", "a.pdf", "application/pdf", 12)],
    reference=None,
)


async def test_list_messages(make_client: Callable) -> None:
    api = FakeApi(PAGE)
    found = await make_client(api).list_messages(
        "acc_1", folder="inbox", text="hi", sender="a@x.org", unread=True, limit=5
    )
    assert api.call() == (
        "GET",
        "/v1/accounts/acc_1/messages",
        {
            "folder": "inbox",
            "q": "hi",
            "from": "a@x.org",
            "unread": "true",
            "limit": "5",
        },
        None,
    )
    assert found == Page([READ_SUMMARY], "c2", ["acc_2: timed out"])


async def test_list_changes(make_client: Callable) -> None:
    change = {"type": "message.created", "id": "msg_1", "account_id": "acc_1"}
    at = "2026-10-01T08:00:00+00:00"
    api = FakeApi({"changes": [{**change, "at": at}], "state": "s2", "more": True})
    found = await make_client(api).list_changes("acc_1", since="s1", limit=10)
    assert api.call() == (
        "GET",
        "/v1/accounts/acc_1/changes",
        {"since": "s1", "limit": "10"},
        None,
    )
    assert found == Changes(
        [Change("message.created", "msg_1", "acc_1", AT)], "s2", True
    )


async def test_get_message(make_client: Callable) -> None:
    api = FakeApi(MESSAGE)
    assert await make_client(api).get_message("acc_1", "msg_1") == READ_MESSAGE
    assert api.call() == ("GET", "/v1/accounts/acc_1/messages/msg_1", {}, None)


async def test_a_message_reads_what_the_api_may_leave_out(
    make_client: Callable,
) -> None:
    """The API requires the id alone. A draft names what it answers."""
    reference = {"message_id": "msg_0", "action": "reply"}
    api = FakeApi({"id": "drf_1", "from": None, "reference": reference})
    found = await make_client(api).get_message("acc_1", "drf_1")
    assert found.sender is None and found.date is None
    assert found.to == [] and found.attachments == [] and not found.unread
    assert found.reference == Reference("msg_0", "reply", "inline", True)


def test_a_message_is_its_summary_and_more() -> None:
    assert isinstance(READ_MESSAGE, MessageSummary)
    assert READ_MESSAGE.subject == SUMMARY["subject"]


async def test_update_messages(make_client: Callable) -> None:
    results = [{"id": "m1", "ok": True}, {"id": "m2", "ok": False}]
    results.append({"id": "m3", "error": {"message": "gone"}})
    api = FakeApi({"results": results})
    found = await make_client(api).update_messages(
        "acc_1", ["m1", "m2", "m3"], unread=False, folder_id="archive"
    )
    assert api.call() == (
        "POST",
        "/v1/accounts/acc_1/messages/batch",
        {},
        {
            "ids": ["m1", "m2", "m3"],
            "action": "update",
            "changes": {"unread": False, "folder_ids": ["archive"]},
        },
    )
    assert found == Outcome(["m1"], [Failed("m2", "failed"), Failed("m3", "gone")])


async def test_trash_messages(make_client: Callable) -> None:
    api = FakeApi({"results": [{"id": "m1", "ok": True}]})
    found = await make_client(api).trash_messages("acc_1", ["m1"])
    body = {"ids": ["m1"], "action": "delete"}
    assert api.call() == ("POST", "/v1/accounts/acc_1/messages/batch", {}, body)
    assert found.done == ["m1"]


@pytest.mark.parametrize(
    ("permanent", "query"), [(False, {}), (True, {"permanent": "true"})]
)
async def test_delete_message(
    make_client: Callable, permanent: bool, query: dict[str, str]
) -> None:
    api = FakeApi(None)
    client = make_client(api)
    assert await client.delete_message("acc_1", "msg_1", permanent=permanent) is None
    assert api.call() == ("DELETE", "/v1/accounts/acc_1/messages/msg_1", query, None)


async def test_get_message_raw_answers_the_bytes(make_client: Callable) -> None:
    source = b"From: a@example.com\r\nSubject: Hi\r\n\r\nHello\r\n"

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/accounts/acc_1/messages/msg_1/raw"
        return httpx.Response(
            200, content=source, headers={"content-type": "message/rfc822"}
        )

    assert await make_client(answer).get_message_raw("acc_1", "msg_1") == source


async def test_get_message_raw_reads_an_error_as_one(make_client: Callable) -> None:
    api = FakeApi({"error": {"code": "not_found", "message": "no such message"}}, 404)
    with pytest.raises(ApiError) as raised:
        await make_client(api).get_message_raw("acc_1", "msg_9")
    assert raised.value.code == "not_found"


async def test_list_all_messages_names_the_accounts(make_client: Callable) -> None:
    api = FakeApi(PAGE)
    found = await make_client(api).list_all_messages(
        accounts=["acc_1", "acc_2"], folder="inbox", unread=True, limit=5
    )
    [request] = api.seen
    assert request.url.path == "/v1/messages"
    assert request.url.params.get_list("accounts") == ["acc_1", "acc_2"]
    others = {k: v for k, v in request.url.params.items() if k != "accounts"}
    assert others == {"folder": "inbox", "unread": "true", "limit": "5"}
    assert found.not_answering == ["acc_2: timed out"]


async def test_list_all_changes(make_client: Callable) -> None:
    api = FakeApi({"changes": [], "state": "s1", "more": False})
    found = await make_client(api).list_all_changes(since="s0")
    assert api.call() == ("GET", "/v1/changes", {"since": "s0"}, None)
    assert found == Changes(changes=[], state="s1", more=False)


async def test_update_message_sends_only_what_changes(make_client: Callable) -> None:
    api = FakeApi({"id": "msg_1", "keywords": ["work"]})
    found = await make_client(api).update_message("acc_1", "msg_1", keywords=["work"])
    assert api.call() == (
        "PATCH",
        "/v1/accounts/acc_1/messages/msg_1",
        {},
        {"keywords": ["work"]},
    )
    assert found.keywords == ["work"]


async def test_batch_messages(make_client: Callable) -> None:
    api = FakeApi({"results": [{"id": "m1", "ok": True}]})
    found = await make_client(api).batch_messages(
        "acc_1", ["m1"], "delete", permanent=True
    )
    assert api.call() == (
        "POST",
        "/v1/accounts/acc_1/messages/batch",
        {},
        {"ids": ["m1"], "action": "delete", "permanent": True},
    )
    assert found == Outcome(done=["m1"], failed=[])
