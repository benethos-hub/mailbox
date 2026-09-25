"""A Microsoft Graph mailbox in memory, as an ``httpx.MockTransport``
handler. It answers the calls the ``microsoft`` adapter makes, the way the
Graph documentation describes them, and records every request."""

from __future__ import annotations

import base64
import itertools
import json
from email import message_from_bytes
from email.policy import default
from email.utils import getaddresses
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

TOKEN = "good-token"
# How the fake marks an id that is not immutable.
REST = "rest-"
WELL_KNOWN = ("inbox", "sentitems", "drafts", "deleteditems", "junkemail")


class FakeGraph:
    def __init__(self) -> None:
        self.ids = (f"AAMk{n}=" for n in itertools.count(1))
        self.root = "root-folder"
        self.folders: dict[str, dict[str, Any]] = {}
        self.well_known: dict[str, str] = {}
        for name in WELL_KNOWN:
            folder_id = self.new_folder(name.capitalize(), self.root)
            self.well_known[name] = folder_id
        self.messages: dict[str, dict[str, Any]] = {}
        self.raws: dict[str, bytes] = {}
        self.attachments: dict[str, list[dict[str, Any]]] = {}
        self.sent: list[bytes] = []
        self.requests: list[httpx.Request] = []
        # Tokens the fake accepts. Any other answers 401.
        self.tokens = {TOKEN}

    # --- setting up -----------------------------------------------------------------

    def new_folder(self, name: str, parent: str) -> str:
        folder_id = next(self.ids)
        self.folders[folder_id] = {
            "id": folder_id,
            "displayName": name,
            "parentFolderId": parent,
        }
        return folder_id

    def add_message(self, folder: str = "inbox", **fields: Any) -> str:
        message_id = next(self.ids)
        self.messages[message_id] = {
            "id": message_id,
            "conversationId": "conv-1",
            "parentFolderId": self.well_known.get(folder, folder),
            "subject": "Hello",
            "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "me@example.org"}}],
            "receivedDateTime": f"2026-09-{len(self.messages) + 1:02d}T10:00:00Z",
            "bodyPreview": "Hi",
            "isRead": False,
            "flag": {"flagStatus": "notFlagged"},
            "categories": [],
            "hasAttachments": False,
            "isDraft": False,
            "internetMessageId": f"<{message_id}@example.com>",
            "body": {"contentType": "text", "content": "Hi there"},
            **fields,
        }
        self.raws[message_id] = (
            f"Message-ID: <{message_id}@example.com>\r\nSubject: "
            f"{self.messages[message_id]['subject']}\r\n\r\nHi there\r\n"
        ).encode()
        return message_id

    # --- the transport --------------------------------------------------------------

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") not in {
            f"Bearer {t}" for t in self.tokens
        }:
            return _error(401, "InvalidAuthenticationToken", "expired")
        url = urlsplit(str(request.url))
        assert url.netloc == "graph.microsoft.com", url.netloc
        if url.path == "/v1.0/$batch":
            return self._batch(request)
        path = [unquote(p) for p in url.path.removeprefix("/v1.0/me/").split("/")]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        method = request.method
        if path[0] == "mailFolders":
            return self._folders(method, path[1:], query, request)
        if path[0] == "messages":
            return self._messages(method, path[1:], query, request)
        if path == ["sendMail"] and method == "POST":
            self.sent.append(base64.b64decode(request.content))
            return httpx.Response(202)
        return _error(400, "BadRequest", f"unknown call {method} {url.path}")

    def _batch(self, request: httpx.Request) -> httpx.Response:
        """JSON batching. Each request is answered as on its own."""
        replies = []
        for one in json.loads(request.content)["requests"]:
            assert len(json.loads(request.content)["requests"]) <= 20
            inner = httpx.Request(
                one["method"],
                f"https://graph.microsoft.com/v1.0{one['url']}",
                headers={**request.headers, **one.get("headers", {})},
            )
            answer = self(inner)
            immutable = 'IdType="ImmutableId"' in inner.headers.get("prefer", "")
            body = answer.json() if answer.content else None
            if isinstance(body, dict) and immutable and "id" in body:
                body = {**body, "id": str(body["id"]).removeprefix(REST)}
            replies.append(
                {"id": one["id"], "status": answer.status_code, "body": body}
            )
        return _json(200, {"responses": replies})

    # --- folders --------------------------------------------------------------------

    def _folder(self, key: str) -> dict[str, Any] | None:
        if key == "msgfolderroot":
            return {"id": self.root}
        folder_id = self.well_known.get(key, key)
        return self.folders.get(folder_id)

    def _folder_json(self, folder: dict[str, Any]) -> dict[str, Any]:
        inside = [
            m for m in self.messages.values() if m["parentFolderId"] == folder["id"]
        ]
        children = [
            f for f in self.folders.values() if f["parentFolderId"] == folder["id"]
        ]
        return {
            **folder,
            "totalItemCount": len(inside),
            "unreadItemCount": sum(not m["isRead"] for m in inside),
            "childFolderCount": len(children),
        }

    def _folders(
        self,
        method: str,
        path: list[str],
        query: dict[str, str],
        request: httpx.Request,
    ) -> httpx.Response:
        if not path or path == [""]:
            if method == "GET":
                return _list(
                    self._folder_json(f)
                    for f in self.folders.values()
                    if f["parentFolderId"] == self.root
                )
            name = json.loads(request.content)["displayName"]
            return _json(
                201, self._folder_json(self.folders[self.new_folder(name, self.root)])
            )
        folder = self._folder(path[0])
        if folder is None:
            return _error(404, "ErrorItemNotFound", "folder not found")
        rest = path[1:]
        if not rest:
            if method == "GET":
                return _json(200, self._folder_json(folder))
            if method == "PATCH":
                folder["displayName"] = json.loads(request.content)["displayName"]
                return _json(200, self._folder_json(folder))
            if method == "DELETE":
                del self.folders[folder["id"]]
                return httpx.Response(204)
        if rest == ["childFolders"]:
            if method == "GET":
                return _list(
                    self._folder_json(f)
                    for f in self.folders.values()
                    if f["parentFolderId"] == folder["id"]
                )
            name = json.loads(request.content)["displayName"]
            return _json(
                201,
                self._folder_json(self.folders[self.new_folder(name, folder["id"])]),
            )
        if rest == ["move"]:
            target = self._folder(json.loads(request.content)["destinationId"])
            assert target is not None
            folder["parentFolderId"] = target["id"]
            return _json(201, self._folder_json(folder))
        if rest == ["messages"]:
            found = [
                m for m in self.messages.values() if m["parentFolderId"] == folder["id"]
            ]
            return self._page(
                found, query, f"/v1.0/me/mailFolders/{folder['id']}/messages"
            )
        return _error(400, "BadRequest", "unknown folder call")

    # --- messages -------------------------------------------------------------------

    def _page(
        self, found: list[dict[str, Any]], query: dict[str, str], path: str
    ) -> httpx.Response:
        if "$filter" in query and "isRead eq false" in query["$filter"]:
            found = [m for m in found if not m["isRead"]]
        if "$filter" in query and query["$filter"].startswith("internetMessageId eq '"):
            header = query["$filter"].split("'", 1)[1][:-1].replace("''", "'")
            found = [m for m in found if m["internetMessageId"] == header]
        if "$search" in query:
            words = query["$search"].strip('"').lower()
            found = [
                m
                for m in found
                if any(
                    w.strip("'") in m["subject"].lower() for w in words.split(":")[-1:]
                )
            ]
        found = sorted(found, key=lambda m: m["receivedDateTime"], reverse=True)
        skip = int(query.get("$skip", "0"))
        top = int(query.get("$top", "10"))
        page = found[skip : skip + top]
        if "$search" in query:
            # As seen live: search ignores the immutable id preference.
            page = [{**m, "id": REST + m["id"]} for m in page]
        body: dict[str, Any] = {"value": page}
        if skip + top < len(found):
            body["@odata.nextLink"] = (
                f"https://graph.microsoft.com{path}?%24top={top}&%24skip={skip + top}"
            )
        return _json(200, body)

    def _messages(
        self,
        method: str,
        path: list[str],
        query: dict[str, str],
        request: httpx.Request,
    ) -> httpx.Response:
        if not path or path == [""]:
            if method == "POST":
                return self._draft(base64.b64decode(request.content))
            return self._page(list(self.messages.values()), query, "/v1.0/me/messages")
        message = self.messages.get(path[0].removeprefix(REST))
        if message is None:
            return _error(
                404, "ErrorItemNotFound", "The specified object was not found"
            )
        rest = path[1:]
        if not rest:
            if method == "GET":
                return _json(200, message)
            if method == "PATCH":
                message.update(json.loads(request.content))
                return _json(200, message)
            if method == "DELETE":
                del self.messages[message["id"]]
                return httpx.Response(204)
        if rest == ["$value"]:
            return httpx.Response(200, content=self.raws[message["id"]])
        if rest == ["move"]:
            target = self._folder(json.loads(request.content)["destinationId"])
            if target is None:
                return _error(404, "ErrorItemNotFound", "folder not found")
            message["parentFolderId"] = target["id"]
            return _json(201, message)
        if rest[0] == "attachments":
            items = self.attachments.get(message["id"], [])
            if len(rest) == 1:
                return _list(
                    {k: v for k, v in a.items() if k != "contentBytes"} for a in items
                )
            match = next((a for a in items if a["id"] == rest[1]), None)
            if match is None:
                return _error(404, "ErrorItemNotFound", "attachment not found")
            return _json(200, match)
        return _error(400, "BadRequest", "unknown message call")

    def _draft(self, raw: bytes) -> httpx.Response:
        parsed = message_from_bytes(raw, policy=default)

        def recipients(header: str) -> list[dict[str, Any]]:
            values = [str(v) for v in parsed.get_all(header, [])]
            return [
                {"emailAddress": {"name": name, "address": address}}
                for name, address in getaddresses(values)
            ]

        body = parsed.get_body(("plain", "html"))
        message_id = self.add_message(
            "drafts",
            subject=str(parsed["Subject"] or ""),
            toRecipients=recipients("To"),
            ccRecipients=recipients("Cc"),
            bccRecipients=recipients("Bcc"),
            isDraft=True,
            isRead=True,
            body={
                "contentType": "text",
                "content": body.get_content() if body is not None else "",
            },
        )
        self.raws[message_id] = raw
        return _json(201, self.messages[message_id])


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def _list(items: Any) -> httpx.Response:
    return _json(200, {"value": list(items)})


def _error(status: int, code: str, message: str) -> httpx.Response:
    return _json(status, {"error": {"code": code, "message": message}})
