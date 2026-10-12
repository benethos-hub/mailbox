"""The tool get_thread: a conversation from one of its mails or its id,
each mail marked as foreign content, the bodies sharing max_chars."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from benethos_mailbox_mcp.errors import ToolError
from benethos_mailbox_mcp.tools import reading

BASE = "/v1/accounts/acc_1"


def mail(n: int, text: str = "Hello") -> dict[str, Any]:
    return {
        "id": f"msg_{n}",
        "account_id": "acc_1",
        "thread_id": "thr_1",
        "folder_ids": ["INBOX"] if n % 2 else ["Sent"],
        "from": {"email": "a@example.com"},
        "to": [{"email": "me@example.com"}],
        "subject": "Hi",
        "date": f"2026-09-{n:02d}T10:00:00Z",
        "text_body": text,
    }


def thread(*numbers: int, truncated: bool = False) -> dict[str, Any]:
    return {
        "id": "thr_1",
        "account_id": "acc_1",
        "subject": "Hi",
        "participants": [{"email": "a@example.com"}],
        "message_count": len(numbers),
        "unread_count": 0,
        "folder_ids": ["INBOX", "Sent"],
        "truncated": truncated,
        "messages": [mail(n) for n in numbers],
    }


def routes(*numbers: int, **mails: dict[str, Any]) -> dict[str, Any]:
    found = {f"{BASE}/messages/msg_{n}": mail(n) for n in numbers}
    found.update({f"{BASE}/messages/{k}": v for k, v in mails.items()})
    return {f"{BASE}/threads/thr_1": thread(*numbers), **found}


async def test_from_a_search_hit_oldest_first(api: Callable) -> None:
    handler = api(routes=routes(1, 2, 3))
    text = await reading.get_thread("acc_1", message_id="msg_2")
    head = text[: text.index("<mail-content")]
    assert "thread: thr_1" in head and "mails: 3" in head
    assert "folders: INBOX, Sent" in head
    sources = [f'source="acc_1/msg_{n}"' for n in (1, 2, 3)]
    assert [text.index(s) for s in sources] == sorted(text.index(s) for s in sources)
    # The hit was read once.
    paths = [c.path for c in handler.calls]
    assert paths.count(f"{BASE}/messages/msg_2") == 1


async def test_a_search_hit_and_a_mail_name_their_thread(api: Callable) -> None:
    api(
        routes={"/v1/messages": {"items": [mail(1)]}, f"{BASE}/messages/msg_1": mail(1)}
    )
    found = await reading.search_messages()
    assert found["messages"][0]["thread_id"] == "thr_1"
    text = await reading.get_message("acc_1", "msg_1")
    assert "thread: thr_1" in text[: text.index("<mail-content")]


async def test_by_its_thread_id(api: Callable) -> None:
    api(routes=routes(1, 2))
    text = await reading.get_thread("acc_1", thread_id="thr_1")
    assert text.count("<mail-content") == 2


async def test_the_bodies_share_max_chars(api: Callable) -> None:
    long = "x" * 5000
    api(routes=routes(1, msg_2={**mail(2), "text_body": long}) | {
        f"{BASE}/threads/thr_1": thread(1, 2)
    })  # fmt: skip
    text = await reading.get_thread("acc_1", thread_id="thr_1", max_chars=2000)
    assert "x" * 1000 in text and "x" * 1001 not in text
    assert "body cut to 1000 characters" in text


async def test_a_long_thread_reads_its_newest(
    api: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reading, "MAX_THREAD_MAILS", 2)
    handler = api(routes=routes(1, 2, 3))
    text = await reading.get_thread("acc_1", thread_id="thr_1")
    assert "note: the oldest mail left out, the newest 2 follow" in text
    assert 'source="acc_1/msg_1"' not in text
    assert f"{BASE}/messages/msg_1" not in [c.path for c in handler.calls]


async def test_a_truncated_thread_says_so(api: Callable) -> None:
    found = thread(1, truncated=True)
    api(routes={f"{BASE}/threads/thr_1": found, f"{BASE}/messages/msg_1": mail(1)})
    text = await reading.get_thread("acc_1", thread_id="thr_1")
    assert "note: older mails left out" in text


@pytest.mark.parametrize("given", [{}, {"message_id": "msg_1", "thread_id": "thr_1"}])
async def test_one_of_the_two_ids(given: dict[str, str]) -> None:
    with pytest.raises(ToolError, match="either message_id or thread_id"):
        await reading.get_thread("acc_1", **given)


async def test_a_mail_without_a_thread(api: Callable) -> None:
    api(routes={f"{BASE}/messages/msg_1": {**mail(1), "thread_id": None}})
    with pytest.raises(ToolError, match="names no thread"):
        await reading.get_thread("acc_1", message_id="msg_1")
