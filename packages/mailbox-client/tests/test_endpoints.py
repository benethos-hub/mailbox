"""Each endpoint: the request it makes and the record it answers, the
same for both clients."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from benethos_mailbox_client import (
    Changes,
    Folder,
    Me,
    MeAccount,
    Outcome,
    Page,
    Sending,
    Sent,
    message_body,
)


class FakeApi:
    """Answers every request with ``answer`` and ``status``, ``None`` as
    204, and records each."""

    def __init__(self, answer: Any = None, status: int = 200) -> None:
        self.answer, self.status = answer, status
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.answer is None:
            return httpx.Response(204)
        return httpx.Response(self.status, json=self.answer)

    def call(self) -> tuple[str, str, dict[str, str], Any]:
        """The one request: method, path, query and body."""
        [request] = self.seen
        body = json.loads(request.content) if request.content else None
        return request.method, request.url.path, dict(request.url.params), body


ME = {
    "accounts": [
        {
            "id": "acc_1",
            "email": "me@example.com",
            "display_name": "Me",
            "operations": ["list_messages"],
            "warnings": ["reads_and_sends"],
            "sending": [
                {"recipients": ["a@x.org"], "max_sends_per_day": 5, "sends_left": 4}
            ],
            "capabilities": ["flags"],
        },
        {"id": "acc_2", "email": "two@example.com"},
    ],
    "operations": ["list_users"],
}
FOLDER = {"id": "fld_1", "name": "Inbox", "role": "inbox", "unread": 2, "total": 9}
PAGE = {
    "items": [{"id": "msg_1"}],
    "next_cursor": "c2",
    "incomplete": [{"account_id": "acc_2", "message": "timed out"}],
}
SENT = {"message_id_header": "<m@x>", "refused": ["b@x.org"]}


async def test_me(make_client: Callable) -> None:
    api = FakeApi(ME)
    me = await make_client(api).me()
    assert api.call() == ("GET", "/v1/me", {}, None)
    assert me == Me(
        accounts=[
            MeAccount(
                id="acc_1",
                email="me@example.com",
                display_name="Me",
                operations=frozenset({"list_messages"}),
                warnings=frozenset({"reads_and_sends"}),
                sending=(Sending(("a@x.org",), 5, 4),),
                capabilities=frozenset({"flags"}),
            ),
            MeAccount(
                id="acc_2",
                email="two@example.com",
                display_name=None,
                operations=frozenset(),
                warnings=frozenset(),
            ),
        ],
        operations=frozenset({"list_users"}),
    )


async def test_list_folders(make_client: Callable) -> None:
    api = FakeApi([FOLDER])
    found = await make_client(api).list_folders("acc_1")
    assert api.call() == ("GET", "/v1/accounts/acc_1/folders", {}, None)
    assert found == [Folder("fld_1", "Inbox", "inbox", 2, 9)]


async def test_create_folder(make_client: Callable) -> None:
    api = FakeApi(FOLDER)
    found = await make_client(api).create_folder("acc_1", "Inbox", None)
    assert api.call() == ("POST", "/v1/accounts/acc_1/folders", {}, {"name": "Inbox"})
    assert found.id == "fld_1"


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
    assert found == Page([{"id": "msg_1"}], "c2", ["acc_2: timed out"])


async def test_list_messages_of_every_account(make_client: Callable) -> None:
    api = FakeApi({"items": []})
    found = await make_client(api).list_messages(None, limit=5, cursor="c")
    assert api.call() == ("GET", "/v1/messages", {"limit": "5", "cursor": "c"}, None)
    assert found == Page([], None)


async def test_list_changes(make_client: Callable) -> None:
    change = {"type": "message.created", "id": "msg_1", "account_id": "acc_1"}
    api = FakeApi({"changes": [{**change, "at": "t"}], "state": "s2", "more": True})
    found = await make_client(api).list_changes(None, since="s1", limit=10)
    assert api.call() == ("GET", "/v1/changes", {"since": "s1", "limit": "10"}, None)
    assert found == Changes([{**change, "at": "t"}], "s2", True)


async def test_get_message(make_client: Callable) -> None:
    api = FakeApi({"id": "msg_1"})
    assert await make_client(api).get_message("acc_1", "msg_1") == {"id": "msg_1"}
    assert api.call() == ("GET", "/v1/accounts/acc_1/messages/msg_1", {}, None)


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
    assert found == Outcome(
        ["m1"], [{"id": "m2", "error": "failed"}, {"id": "m3", "error": "gone"}]
    )


async def test_trash_messages(make_client: Callable) -> None:
    api = FakeApi({"results": [{"id": "m1", "ok": True}]})
    found = await make_client(api).trash_messages("acc_1", ["m1"])
    body = {"ids": ["m1"], "action": "delete"}
    assert api.call() == ("POST", "/v1/accounts/acc_1/messages/batch", {}, body)
    assert found.done == ["m1"]


async def test_list_drafts(make_client: Callable) -> None:
    api = FakeApi({"items": [], "next_cursor": None})
    await make_client(api).list_drafts("acc_1", 10)
    assert api.call() == ("GET", "/v1/accounts/acc_1/drafts", {"limit": "10"}, None)


BODY = message_body(
    to=[("a@x.org", "A")],
    cc=[("c@x.org", None)],
    bcc=[],
    subject="Hi",
    text="Hello",
    html="<p>Hello</p>",
    reference=("msg_1", "reply"),
)


def test_message_body() -> None:
    assert BODY == {
        "to": [{"email": "a@x.org", "name": "A"}],
        "cc": [{"email": "c@x.org"}],
        "bcc": [],
        "subject": "Hi",
        "text": "Hello",
        "html": "<p>Hello</p>",
        "reference": {"message_id": "msg_1", "action": "reply"},
    }


async def test_create_draft(make_client: Callable) -> None:
    api = FakeApi({"id": "drf_1"})
    found = await make_client(api).create_draft("acc_1", BODY)
    assert api.call() == ("POST", "/v1/accounts/acc_1/drafts", {}, BODY)
    assert found == {"id": "drf_1"}


@pytest.mark.parametrize(
    ("keep", "sent"), [(None, {}), (["att_0"], {"keep_attachments": ["att_0"]})]
)
async def test_update_draft(
    make_client: Callable, keep: list[str] | None, sent: dict[str, Any]
) -> None:
    api = FakeApi({"id": "drf_2"})
    await make_client(api).update_draft("acc_1", "drf_1", BODY, keep)
    path = "/v1/accounts/acc_1/drafts/drf_1"
    assert api.call() == ("PUT", path, {}, {**BODY, **sent})


async def test_delete_draft(make_client: Callable) -> None:
    api = FakeApi(None)
    assert await make_client(api).delete_draft("acc_1", "drf_1") is None
    assert api.call() == ("DELETE", "/v1/accounts/acc_1/drafts/drf_1", {}, None)


async def test_send_message(make_client: Callable) -> None:
    api = FakeApi(SENT)
    found = await make_client(api).send_message("acc_1", BODY, "key-1")
    assert api.call() == ("POST", "/v1/accounts/acc_1/send", {}, BODY)
    assert api.seen[0].headers["idempotency-key"] == "key-1"
    assert found == Sent("<m@x>", ["b@x.org"])


async def test_send_draft(make_client: Callable) -> None:
    api = FakeApi({})
    found = await make_client(api).send_draft("acc_1", "drf_1", "key-2")
    path = "/v1/accounts/acc_1/drafts/drf_1/send"
    assert api.call() == ("POST", path, {}, None)
    assert api.seen[0].headers["idempotency-key"] == "key-2"
    assert found == Sent(None, [])
