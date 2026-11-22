"""Stand-ins for the two upstreams, served through ``httpx.MockTransport``.

:class:`FakeService` answers the REST paths of the mailbox service the
package uses, from messages kept in its wire format, and applies the
updates it is sent. :class:`FakeGateway` answers chat completions from a
queue of answers. Both record every request, so a test can say what was
asked. Nothing here reaches a network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from benethos_mailbox_agents import __version__

ACCOUNT = "acc1"

# Invented messages, shared by the tests of the agents and the evaluation.
INVENTED = Path(__file__).resolve().parent / "data" / "invented.json"

FOLDERS = [
    {"id": "inbox", "name": "INBOX", "role": "inbox"},
    {"id": "sent", "name": "Sent", "role": "sent"},
    {"id": "trash", "name": "Trash", "role": "trash"},
    {"id": "trash-sub", "name": "Sub", "role": None, "parent_id": "trash"},
    {"id": "junk", "name": "Junk", "role": "junk"},
    {"id": "inv", "name": "Invoices", "role": None},
    {"id": "inv-hosting", "name": "Hosting", "role": None, "parent_id": "inv"},
    {"id": "inv-mo", "name": "mo", "role": None, "parent_id": "inv"},
    {"id": "inv-cloudhost", "name": "CloudHost", "role": None, "parent_id": "inv"},
    {"id": "inv-telco", "name": "Telco", "role": None, "parent_id": "inv"},
]


def wire_message(
    message_id: str,
    *,
    account_id: str = ACCOUNT,
    folder_ids: list[str] | None = None,
    subject: str | None = "Hello",
    sender: str | None = "someone@example.test",
    sender_name: str | None = None,
    to: list[str] | None = None,
    text: str | None = "Hello.",
    html: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    keywords: list[str] | None = None,
    date: str = "2026-11-17T08:00:00+00:00",
) -> dict[str, Any]:
    """A message as the service answers ``get_message``."""
    return {
        "id": message_id,
        "account_id": account_id,
        "thread_id": thread_id,
        "folder_ids": folder_ids if folder_ids is not None else ["inbox"],
        "subject": subject,
        "from": {"email": sender, "name": sender_name} if sender else None,
        "to": [{"email": a} for a in (to or ["me@example.test"])],
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "date": date,
        "received": date,
        "snippet": None,
        "unread": True,
        "starred": False,
        "keywords": list(keywords or []),
        "has_attachments": bool(attachments),
        "message_id_header": f"<{message_id}@example.test>",
        "in_reply_to": None,
        "text_body": text,
        "html_body": html,
        "attachments": [
            {"id": f"att{i}", "size": 1000, "inline": False, **a}
            for i, a in enumerate(attachments or [])
        ],
    }


def invented(name: str = "invented.json") -> list[dict[str, Any]]:
    """The messages of packages/mailbox-agents/tests/data/<name> in the service's wire
    format."""
    found = json.loads((INVENTED.parent / name).read_text(encoding="utf-8"))
    return [wire_message(item.pop("id"), **item) for item in found]


def _error(status: int, code: str, message: str = "refused") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


def _escaped(status: int, body: Any) -> httpx.Response:
    """JSON with every character beyond ASCII escaped, as a service may send
    it: so a lone surrogate reaches the client as the escape it would be."""
    return httpx.Response(
        status,
        content=json.dumps(body).encode("ascii"),
        headers={"content-type": "application/json"},
    )


class FakeService:
    """The mailbox service, as far as this package uses it."""

    def __init__(self) -> None:
        self.folders: dict[str, list[dict[str, Any]]] = {
            ACCOUNT: [dict(f) for f in FOLDERS]
        }
        self.messages: dict[tuple[str, str], dict[str, Any]] = {}
        self.feed: list[dict[str, Any]] = []
        self.expired: set[str] = set()
        self.down = False
        # What /health names, and how often it was asked. A version of None
        # leaves the key out, and a status refuses /health with it.
        # The first release of the agents' own minor version, so the
        # suite follows the version of the package.
        self.version: str | None = ".".join(__version__.split(".")[:2]) + ".0"
        self.health_status: int | None = None
        self.health_asked = 0
        # Status and code every request is refused with while set.
        self.refusal: tuple[int, str] | None = None
        # Message ids whose get_message answers 500, as for a mail the
        # service cannot parse.
        self.broken: set[str] = set()
        # How many of the next writes that add a keyword answer 503.
        self.keyword_failures = 0
        # Status and code every write is refused with while set.
        self.write_refusal: tuple[int, str] | None = None
        self.requests: list[httpx.Request] = []

    # -- filling ---------------------------------------------------------------

    def add(
        self, message: dict[str, Any], change: str | None = "message.created"
    ) -> None:
        """Keep ``message`` and, unless ``change`` is None, put it in the feed."""
        key = (message["account_id"], message["id"])
        self.messages[key] = message
        if change:
            self.change(change, message["id"], message["account_id"])

    def change(self, kind: str, message_id: str, account_id: str = ACCOUNT) -> None:
        self.feed.append(
            {
                "type": kind,
                "id": message_id,
                "account_id": account_id,
                "at": "2026-11-17T08:00:00+00:00",
            }
        )

    @property
    def state(self) -> str:
        return str(len(self.feed))

    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        """The PATCH requests sent, as path and body."""
        return [
            (unquote(r.url.path), json.loads(r.content))
            for r in self.requests
            if r.method == "PATCH"
        ]

    def made(self) -> list[dict[str, Any]]:
        """The folders asked to be made, as the bodies sent."""
        return [
            json.loads(r.content)
            for r in self.requests
            if r.method == "POST" and _kind(_parts(r)) == "folders"
        ]

    # -- answering ---------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            # Open to everyone and outside /v1: no refusal reaches it, and
            # it is kept out of ``requests``, which name the calls of /v1.
            self.health_asked += 1
            if self.down:
                return _error(503, "unavailable")
            if self.health_status is not None:
                return _error(self.health_status, "not_found")
            if self.version is None:
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(200, json={"status": "ok", "version": self.version})
        self.requests.append(request)
        if self.down:
            return _error(503, "unavailable")
        if self.refusal:
            return _error(*self.refusal)
        if self.write_refusal and request.method in ("PATCH", "POST"):
            return _error(*self.write_refusal)
        parts = _parts(request)
        route: Callable[[httpx.Request, list[str]], httpx.Response] | None = {
            ("GET", "changes"): self._changes,
            ("GET", "messages"): self._list,
            ("GET", "account_messages"): self._list_folder,
            ("GET", "folders"): self._folders,
            ("GET", "message"): self._message,
            ("GET", "thread"): self._thread,
            ("PATCH", "message"): self._update,
            ("POST", "folders"): self._create_folder,
            ("GET", "me"): self._me,
        }.get((request.method, _kind(parts)))
        if route is None:
            return _error(404, "not_found", "no such path")
        return route(request, parts)

    def _me(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        """The caller, granted every account that has folders."""
        accounts = [
            {"id": account, "email": f"{account}@example.test"}
            for account in sorted(self.folders)
        ]
        return httpx.Response(
            200, json={"user_id": "usr1", "name": "agents", "accounts": accounts}
        )

    def _changes(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        since = request.url.params.get("since")
        if since is None:
            return httpx.Response(200, json={"changes": [], "state": self.state})
        if since in self.expired:
            return _error(410, "changes_expired", "too old")
        start = int(since)
        limit = int(request.url.params.get("limit", "200"))
        chunk = self.feed[start : start + limit]
        end = start + len(chunk)
        return _escaped(
            200,
            {"changes": chunk, "state": str(end), "more": end < len(self.feed)},
        )

    def _list(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        role = request.url.params.get("folder", "inbox")
        items = sorted(
            (m for m in self.messages.values() if self._in_role(m, role)),
            key=lambda m: m["id"],
        )
        cursor = int(request.url.params.get("cursor", "0"))
        limit = int(request.url.params.get("limit", "200"))
        page = items[cursor : cursor + limit]
        more = cursor + limit < len(items)
        return _escaped(
            200,
            {
                "items": page,
                "next_cursor": str(cursor + limit) if more else None,
            },
        )

    def _list_folder(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        """One account's messages, of a folder named by its id or its role,
        in one page: the tests list few."""
        named = request.url.params.get("folder", "inbox")
        roles = {f["id"]: f.get("role") for f in self.folders.get(parts[1], [])}
        items = sorted(
            (
                m
                for (account, _), m in self.messages.items()
                if account == parts[1]
                and any(i == named or roles.get(i) == named for i in m["folder_ids"])
            ),
            key=lambda m: m["id"],
        )
        return _escaped(200, {"items": items, "next_cursor": None})

    def _in_role(self, message: dict[str, Any], role: str) -> bool:
        """As the service lists: by the role of a folder, the inbox when
        no folder is named."""
        roles = {
            f["id"]: f.get("role") for f in self.folders.get(message["account_id"], [])
        }
        return any(roles.get(i) == role for i in message["folder_ids"])

    def _folders(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        return _escaped(200, self.folders.get(parts[1], []))

    def _create_folder(
        self, request: httpx.Request, parts: list[str]
    ) -> httpx.Response:
        """As the service at IMAP: a name refused only in the same case
        below the same parent (measured 2026-11-18)."""
        body = json.loads(request.content)
        known = self.folders.setdefault(parts[1], [])
        name, parent = body["name"], body.get("parent_id")
        if any(f["name"] == name and f.get("parent_id") == parent for f in known):
            return _error(409, "conflict", "the folder exists")
        made = {
            "id": f"{parent}/{name}" if parent else name,
            "name": name,
            "role": None,
            "parent_id": parent,
        }
        known.append(made)
        return httpx.Response(201, json=made)

    def _message(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        if parts[3] in self.broken:
            return _error(500, "internal", "the message cannot be read")
        found = self.messages.get((parts[1], parts[3]))
        if found is None:
            return _error(404, "not_found", "no such message")
        return _escaped(200, found)

    def _thread(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        account, thread = parts[1], parts[3]
        members = sorted(
            (
                m
                for (a, _), m in self.messages.items()
                if a == account and m.get("thread_id") == thread
            ),
            key=lambda m: m["date"],
        )
        if not members:
            return _error(404, "not_found", "no such thread")
        return _escaped(
            200,
            {
                "id": thread,
                "account_id": account,
                "subject": members[-1]["subject"],
                "participants": [],
                "message_count": len(members),
                "unread_count": 0,
                "date": members[-1]["date"],
                "snippet": None,
                "folder_ids": [],
                "truncated": False,
                "messages": members,
            },
        )

    def _update(self, request: httpx.Request, parts: list[str]) -> httpx.Response:
        found = self.messages.get((parts[1], parts[3]))
        if found is None:
            return _error(404, "not_found", "no such message")
        body = json.loads(request.content)
        if self.keyword_failures and body.get("add_keywords"):
            self.keyword_failures -= 1
            return _error(503, "unavailable")
        known = {
            name
            for f in self.folders.get(parts[1], [])
            for name in (f["id"], f.get("role"))
            if name
        }
        for folder_id in body.get("folder_ids", []):
            if folder_id not in known:
                # As the service at IMAP answers a folder deleted or renamed
                # since it was listed (measured 2026-11-18).
                return _error(404, "not_found", f"folder {folder_id} not found")
        keywords = [
            k for k in found["keywords"] if k not in body.get("remove_keywords", [])
        ]
        keywords += [k for k in body.get("add_keywords", []) if k not in keywords]
        found["keywords"] = keywords
        if "folder_ids" in body:
            found["folder_ids"] = list(body["folder_ids"])
        return _escaped(200, found)


def _parts(request: httpx.Request) -> list[str]:
    """The path of ``request`` below /v1, each part unquoted."""
    return [unquote(p) for p in request.url.path.split("/")[2:]]


def _kind(parts: list[str]) -> str:
    """Which route ``parts``, the path below /v1, names."""
    if parts == ["changes"]:
        return "changes"
    if parts == ["me"]:
        return "me"
    if parts == ["messages"]:
        return "messages"
    if len(parts) == 3 and parts[0] == "accounts" and parts[2] == "messages":
        return "account_messages"
    if len(parts) == 3 and parts[0] == "accounts" and parts[2] == "folders":
        return "folders"
    if len(parts) == 4 and parts[0] == "accounts" and parts[2] == "messages":
        return "message"
    if len(parts) == 4 and parts[0] == "accounts" and parts[2] == "threads":
        return "thread"
    return ""


class FakeGateway:
    """An OpenAI-compatible chat completions endpoint with queued answers.

    An answer is a dict, sent as the JSON content of the message, a string,
    sent as the content as it is, or an ``httpx.Response``, sent whole.
    """

    def __init__(self, model: str = "reported-model") -> None:
        self.model = model
        self.answers: list[dict[str, Any] | str | httpx.Response] = []
        self.requests: list[httpx.Request] = []
        # Called while a question is answered, for what happens meanwhile.
        self.during: Callable[[], None] | None = None

    def answer(self, *answers: dict[str, Any] | str | httpx.Response) -> None:
        self.answers.extend(answers)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not request.url.path.endswith("/chat/completions"):
            return httpx.Response(404, json={"error": {"message": "no such path"}})
        if not self.answers:
            return httpx.Response(503, json={"error": {"message": "no answer queued"}})
        if self.during is not None:
            self.during()
        found = self.answers.pop(0)
        if isinstance(found, httpx.Response):
            return found
        content = found if isinstance(found, str) else json.dumps(found)
        return _escaped(
            200,
            {
                "id": "chatcmpl-1",
                "model": self.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 15},
            },
        )
