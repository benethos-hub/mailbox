"""A Gmail mailbox in memory, as an ``httpx.MockTransport`` handler. It
answers the calls the ``gmail`` adapter makes, the way the Gmail API
documentation describes them, keeps a history of every change, and
records every request."""

from __future__ import annotations

import base64
import itertools
import json
import shlex
from email import message_from_bytes
from email.policy import default
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

TOKEN = "good-token"
PREFIX = "/gmail/v1/users/me"
ADDRESS = "me@gmail.com"
SYSTEM = (
    "INBOX",
    "SENT",
    "DRAFT",
    "TRASH",
    "SPAM",
    "STARRED",
    "UNREAD",
    "IMPORTANT",
    "CHAT",
    "CATEGORY_PROMOTIONS",
)
# Labels a message cannot be given by hand.
FIXED = frozenset({"SENT", "DRAFT"})


def source(
    subject: str = "Hello",
    sender: str = "Alice <alice@example.com>",
    to: str = ADDRESS,
    body: str = "Hi there",
    message_id: str | None = None,
) -> bytes:
    lines = [
        f"From: {sender}",
        f"To: {to}",
        f"Subject: {subject}",
        "Date: Tue, 01 Sep 2026 10:00:00 +0000",
        f"Message-ID: {message_id or '<m@example.com>'}",
        "Content-Type: text/plain; charset=utf-8",
        "",
        body,
    ]
    return "\r\n".join(lines).encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


class FakeGmail:
    def __init__(self) -> None:
        self.numbers = itertools.count(1)
        self.labels: dict[str, dict[str, Any]] = {
            name: {"id": name, "name": name, "type": "system"} for name in SYSTEM
        }
        self.messages: dict[str, dict[str, Any]] = {}
        self.drafts: dict[str, str] = {}  # draft id -> message id
        self.sent: list[bytes] = []
        self.requests: list[httpx.Request] = []
        self.tokens = {TOKEN}
        # Given once to the next request instead of an answer of its own.
        self.next_answer: httpx.Response | None = None
        self.history_id = 1000
        self.history: list[dict[str, Any]] = []
        # History ids older than this are no longer kept: 404.
        self.oldest = 0

    # --- setting up -----------------------------------------------------------------

    def new_label(self, name: str) -> str:
        label_id = f"Label_{next(self.numbers)}"
        self.labels[label_id] = {"id": label_id, "name": name, "type": "user"}
        return label_id

    def add_message(
        self, labels: tuple[str, ...] = ("INBOX", "UNREAD"), **fields: Any
    ) -> str:
        """A message that arrived, with ``source(**fields)``."""
        number = next(self.numbers)
        message_id = f"{number:016x}"
        self.messages[message_id] = {
            "id": message_id,
            "threadId": f"t{number:015x}",
            "labelIds": list(labels),
            "raw": source(**fields),
            "internalDate": str(1788000000000 + number * 1000),
        }
        self._record(messagesAdded=[{"message": self._ref(message_id)}])
        return message_id

    def _ref(self, message_id: str) -> dict[str, Any]:
        found = self.messages[message_id]
        return {
            "id": message_id,
            "threadId": found["threadId"],
            "labelIds": list(found["labelIds"]),
        }

    def _record(self, **change: Any) -> None:
        self.history_id += 1
        self.history.append({"id": str(self.history_id), **change})

    # --- the handler ----------------------------------------------------------------

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.next_answer is not None:
            answer, self.next_answer = self.next_answer, None
            return answer
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in self.tokens:
            return _error(401, "Invalid Credentials", "UNAUTHENTICATED")
        url = urlsplit(str(request.url))
        assert url.netloc == "gmail.googleapis.com", url.netloc
        assert url.path.startswith(PREFIX), url.path
        path = [unquote(p) for p in url.path[len(PREFIX) :].split("/")[1:]]
        query = parse_qs(url.query)
        body = json.loads(request.content) if request.content else {}
        return self._route(request.method, path, query, body)

    def _route(
        self, method: str, path: list[str], query: dict[str, list[str]], body: Any
    ) -> httpx.Response:
        match method, path:
            case "GET", ["profile"]:
                return _ok({"emailAddress": ADDRESS, "historyId": str(self.history_id)})
            case "GET", ["history"]:
                return self._history(query)
            case _, ["labels", *rest]:
                return self._labels_route(method, rest, body)
            case _, ["messages", *rest]:
                return self._messages_route(method, rest, query, body)
            case _, ["drafts", *rest]:
                return self._drafts_route(method, rest, body)
        return _not_routed()

    def _labels_route(self, method: str, rest: list[str], body: Any) -> httpx.Response:
        match method, rest:
            case "GET", []:
                return _ok({"labels": list(self.labels.values())})
            case "GET", [label_id]:
                return self._label(label_id)
            case "POST", []:
                return self._create_label(body)
            case "PATCH", [label_id]:
                return self._rename_label(label_id, body)
            case "DELETE", [label_id]:
                return self._delete_label(label_id)
        return _not_routed()

    def _messages_route(
        self, method: str, rest: list[str], query: dict[str, list[str]], body: Any
    ) -> httpx.Response:
        match method, rest:
            case "GET", []:
                return self._list(query)
            case "POST", ["send"]:
                return self._send(body)
            case "GET", [message_id]:
                return self._get(message_id, query)
            case "POST", [message_id, "modify"]:
                return self._modify(
                    message_id, body.get("addLabelIds"), body.get("removeLabelIds")
                )
            case "POST", [message_id, "trash"]:
                return self._modify(message_id, ["TRASH"], [])
            case "DELETE", [message_id]:
                return self._delete(message_id)
        return _not_routed()

    def _drafts_route(self, method: str, rest: list[str], body: Any) -> httpx.Response:
        match method, rest:
            case "GET", []:
                return self._list_drafts()
            case "POST", []:
                return self._save_draft(None, body)
            case "PUT", [draft_id]:
                return self._save_draft(draft_id, body)
            case "DELETE", [draft_id]:
                return self._delete_draft(draft_id)
        return _not_routed()

    # --- labels ---------------------------------------------------------------------

    def _label(self, label_id: str) -> httpx.Response:
        label = self.labels.get(label_id)
        if label is None:
            return _missing()
        inside = [m for m in self.messages.values() if label_id in m["labelIds"]]
        unread = [m for m in inside if "UNREAD" in m["labelIds"]]
        return _ok(
            {**label, "messagesTotal": len(inside), "messagesUnread": len(unread)}
        )

    def _create_label(self, body: dict[str, Any]) -> httpx.Response:
        name = body["name"]
        if any(label["name"] == name for label in self.labels.values()):
            return _error(409, "Label name exists or conflicts", "ALREADY_EXISTS")
        return _ok(self.labels[self.new_label(name)])

    def _rename_label(self, label_id: str, body: dict[str, Any]) -> httpx.Response:
        label = self.labels.get(label_id)
        if label is None:
            return _missing()
        if label["type"] != "user":
            return _error(400, "Invalid label", "INVALID_ARGUMENT")
        label["name"] = body["name"]
        return _ok(label)

    def _delete_label(self, label_id: str) -> httpx.Response:
        if self.labels.pop(label_id, None) is None:
            return _missing()
        for message in self.messages.values():
            if label_id in message["labelIds"]:
                message["labelIds"].remove(label_id)
        return httpx.Response(204)

    # --- messages -------------------------------------------------------------------

    def _list(self, query: dict[str, list[str]]) -> httpx.Response:
        found = sorted(
            self.messages.values(), key=lambda m: int(m["internalDate"]), reverse=True
        )
        wanted = query.get("labelIds", [])
        if any(w not in self.labels for w in wanted):
            return _error(400, "Invalid label", "INVALID_ARGUMENT")
        found = [m for m in found if all(w in m["labelIds"] for w in wanted)]
        if query.get("includeSpamTrash") != ["true"]:
            found = [m for m in found if not {"TRASH", "SPAM"} & set(m["labelIds"])]
        for term in shlex.split(query.get("q", [""])[0]):
            found = [m for m in found if _matches(m, term)]
        start = int(query.get("pageToken", ["0"])[0])
        size = int(query.get("maxResults", ["100"])[0])
        page = found[start : start + size]
        answer: dict[str, Any] = {"resultSizeEstimate": len(found)}
        if page:
            answer["messages"] = [
                {"id": m["id"], "threadId": m["threadId"]} for m in page
            ]
        if start + size < len(found):
            answer["nextPageToken"] = str(start + size)
        return _ok(answer)

    def _get(self, message_id: str, query: dict[str, list[str]]) -> httpx.Response:
        found = self.messages.get(message_id)
        if found is None:
            return _missing()
        shape = query.get("format", ["full"])[0]
        answer = {**self._ref(message_id), "historyId": str(self.history_id)}
        answer["internalDate"] = found["internalDate"]
        answer["snippet"] = "Hi &amp; there"
        if shape == "raw":
            answer["raw"] = _b64(found["raw"])
        elif shape == "metadata":
            parsed = message_from_bytes(found["raw"], policy=default)
            names = query.get("metadataHeaders", [])
            answer["payload"] = {
                "mimeType": parsed.get_content_type(),
                "headers": [
                    {"name": name, "value": str(value)}
                    for name, value in parsed.items()
                    if name in names
                ],
            }
        return _ok(answer)

    def _modify(
        self, message_id: str, add: list[str] | None, remove: list[str] | None
    ) -> httpx.Response:
        found = self.messages.get(message_id)
        if found is None:
            return _missing()
        add, remove = add or [], remove or []
        if any(label not in self.labels for label in add + remove):
            return _error(400, "Invalid label", "INVALID_ARGUMENT")
        if FIXED & set(add):
            return _error(400, "Invalid label: SENT", "INVALID_ARGUMENT")
        before = set(found["labelIds"])
        labels = [x for x in found["labelIds"] if x not in remove]
        labels += [x for x in add if x not in labels]
        found["labelIds"] = labels
        put_on = sorted(set(labels) - before)
        taken_off = sorted(before - set(labels))
        if put_on:
            ref = self._ref(message_id)
            self._record(labelsAdded=[{"message": ref, "labelIds": put_on}])
        if taken_off:
            ref = self._ref(message_id)
            self._record(labelsRemoved=[{"message": ref, "labelIds": taken_off}])
        return _ok(self._ref(message_id))

    def _delete(self, message_id: str) -> httpx.Response:
        if message_id not in self.messages:
            return _missing()
        ref = self._ref(message_id)
        del self.messages[message_id]
        self._record(messagesDeleted=[{"message": ref}])
        return httpx.Response(204)

    def _send(self, body: dict[str, Any]) -> httpx.Response:
        raw = base64.urlsafe_b64decode(body["raw"] + "==")
        self.sent.append(raw)
        message_id = self._stored(raw, ["SENT"])
        return _ok(self._ref(message_id))

    def _stored(self, raw: bytes, labels: list[str]) -> str:
        number = next(self.numbers)
        message_id = f"{number:016x}"
        self.messages[message_id] = {
            "id": message_id,
            "threadId": f"t{number:015x}",
            "labelIds": labels,
            "raw": raw,
            "internalDate": str(1788000000000 + number * 1000),
        }
        self._record(messagesAdded=[{"message": self._ref(message_id)}])
        return message_id

    # --- drafts ---------------------------------------------------------------------

    def _list_drafts(self) -> httpx.Response:
        drafts = [
            {"id": d, "message": {"id": m, "threadId": self.messages[m]["threadId"]}}
            for d, m in self.drafts.items()
        ]
        return _ok({"drafts": drafts} if drafts else {})

    def _save_draft(self, draft_id: str | None, body: dict[str, Any]) -> httpx.Response:
        if draft_id is not None and draft_id not in self.drafts:
            return _missing()
        raw = base64.urlsafe_b64decode(body["message"]["raw"] + "==")
        message_id = self._stored(raw, ["DRAFT"])
        if draft_id is None:
            draft_id = f"r{next(self.numbers)}"
        else:
            self._delete(self.drafts[draft_id])
        self.drafts[draft_id] = message_id
        return _ok({"id": draft_id, "message": self._ref(message_id)})

    def _delete_draft(self, draft_id: str) -> httpx.Response:
        message_id = self.drafts.pop(draft_id, None)
        if message_id is None:
            return _missing()
        return self._delete(message_id)

    # --- history --------------------------------------------------------------------

    def _history(self, query: dict[str, list[str]]) -> httpx.Response:
        start = int(query["startHistoryId"][0])
        if start < self.oldest:
            return _missing()
        records = [h for h in self.history if int(h["id"]) > start]
        answer: dict[str, Any] = {"historyId": str(self.history_id)}
        if records:
            answer["history"] = records
        return _ok(answer)


def _matches(message: dict[str, Any], term: str) -> bool:
    negated = term.startswith("-")
    term = term.removeprefix("-")
    labels = set(message["labelIds"])
    text = message["raw"].decode().lower()
    if term == "is:unread":
        hit = "UNREAD" in labels
    elif term == "is:starred":
        hit = "STARRED" in labels
    elif term == "has:attachment":
        hit = "multipart/mixed" in text
    elif term.startswith(("after:", "before:")):
        name, _, seconds = term.partition(":")
        received = int(message["internalDate"]) // 1000
        hit = received > int(seconds) if name == "after" else received < int(seconds)
    elif term.startswith(("from:", "to:", "subject:")):
        name, _, value = term.partition(":")
        hit = f"{name}: " in text and value.lower() in _header(text, name)
    else:
        hit = term.lower() in text
    return hit != negated


def _header(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{name}: "):
            return line
    return ""


def _ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


def _not_routed() -> httpx.Response:
    return _error(404, "Not Found", "NOT_FOUND")


def _missing() -> httpx.Response:
    return _error(404, "Requested entity was not found.", "NOT_FOUND")


def _error(status: int, message: str, code: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": status, "message": message, "status": code}},
    )
