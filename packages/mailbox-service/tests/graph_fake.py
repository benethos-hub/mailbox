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
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import httpx

TOKEN = "good-token"
# What Graph takes in one request, and the least an upload session takes.
REQUEST_LIMIT = 4 * 1024 * 1024
SESSION_MINIMUM = 3_000_000
UPLOADS = "outlook.office.com"
# How the fake marks an id that is not immutable.
REST = "rest-"
PROPS = "singleValueExtendedProperties"
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
        # The MIME of each draft sent, and what the next send answers
        # in place of 202.
        self.sent: list[bytes] = []
        self.send_answer: httpx.Response | None = None
        # Files added to a message one by one, and open upload sessions.
        self.files: dict[str, list[dict[str, Any]]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        # Tokens the fake accepts. Any other answers 401.
        self.tokens = {TOKEN}
        # Given once to the next request instead of an answer of its own.
        self.next_answer: httpx.Response | None = None
        # Delta queries: every change bumps a message's version. A deltaLink
        # remembers the folder, the version and the messages it held then.
        self.version = 0
        self.versions: dict[str, int] = {}
        self.delta_links: dict[str, tuple[str, int, frozenset[str]]] = {}
        # Messages per page of a delta answer.
        self.delta_page = 50

    # --- setting up -----------------------------------------------------------------

    def new_folder(self, name: str, parent: str) -> str:
        folder_id = next(self.ids)
        self.folders[folder_id] = {
            "id": folder_id,
            "displayName": name,
            "parentFolderId": parent,
        }
        return folder_id

    def add_message(
        self, folder: str = "inbox", raw: bytes | None = None, **fields: Any
    ) -> str:
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
            raw
            or (
                f"Message-ID: <{message_id}@example.com>\r\nSubject: "
                f"{self.messages[message_id]['subject']}\r\n"
                "Content-Type: text/plain\r\n\r\nHi there\r\n"
            ).encode()
        )
        self.messages[message_id].setdefault("createdDateTime", self.now())
        self.touch(message_id)
        return message_id

    def now(self) -> str:
        """Graph's clock, which a test may set."""
        return getattr(self, "clock", "2026-09-26T10:00:00Z")

    def touch(self, message_id: str) -> None:
        self.version += 1
        self.versions[message_id] = self.version

    def other_client_changes(self, message_id: str, **fields: Any) -> None:
        """Another client changes a message, e.g. isRead or parentFolderId."""
        self.messages[message_id].update(fields)
        self.touch(message_id)

    # --- the transport --------------------------------------------------------------

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.next_answer is not None:
            answer, self.next_answer = self.next_answer, None
            return answer
        url = urlsplit(str(request.url))
        if url.netloc == UPLOADS:
            # The session's URL carries its authorization.
            return self._upload(request, url.path.rsplit("/", 1)[-1])
        if request.headers.get("authorization") not in {
            f"Bearer {t}" for t in self.tokens
        }:
            return _error(401, "InvalidAuthenticationToken", "expired")
        assert url.netloc == "graph.microsoft.com", url.netloc
        if len(request.content) > REQUEST_LIMIT:
            return _error(413, "RequestEntityTooLarge", "the request is too large")
        if url.path == "/v1.0/$batch":
            return self._batch(request)
        path = [unquote(p) for p in url.path.removeprefix("/v1.0/me/").split("/")]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        method = request.method
        if path[0] == "mailFolders":
            return self._folders(method, path[1:], query, request)
        if path[0] == "messages":
            return self._messages(method, path[1:], query, request)
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
        if key in ("msgfolderroot", self.root):
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
            return self._children(method, self.root, request)
        folder = self._folder(path[0])
        if folder is None:
            return _error(404, "ErrorItemNotFound", "folder not found")
        rest = path[1:]
        if not rest:
            return self._one_folder(method, folder, request)
        if rest == ["childFolders"]:
            return self._children(method, folder["id"], request)
        if rest == ["move"]:
            target = self._folder(json.loads(request.content)["destinationId"])
            assert target is not None
            folder["parentFolderId"] = target["id"]
            return _json(201, self._folder_json(folder))
        if rest == ["messages", "delta"]:
            return self._delta(folder["id"], query)
        if rest == ["messages"]:
            found = [
                m for m in self.messages.values() if m["parentFolderId"] == folder["id"]
            ]
            return self._page(
                found, query, f"/v1.0/me/mailFolders/{folder['id']}/messages"
            )
        return _error(400, "BadRequest", "unknown folder call")

    def _children(
        self, method: str, parent_id: str, request: httpx.Request
    ) -> httpx.Response:
        """The folders below ``parent_id``, or a new one there."""
        if method == "GET":
            return _list(
                self._folder_json(f)
                for f in self.folders.values()
                if f["parentFolderId"] == parent_id
            )
        name = json.loads(request.content)["displayName"]
        made = self.folders[self.new_folder(name, parent_id)]
        return _json(201, self._folder_json(made))

    def _one_folder(
        self, method: str, folder: dict[str, Any], request: httpx.Request
    ) -> httpx.Response:
        if method == "GET":
            return _json(200, self._folder_json(folder))
        if method == "PATCH":
            folder["displayName"] = json.loads(request.content)["displayName"]
            return _json(200, self._folder_json(folder))
        if method == "DELETE":
            del self.folders[folder["id"]]
            return httpx.Response(204)
        return _error(400, "BadRequest", "unknown folder call")

    # --- delta queries --------------------------------------------------------------

    def _delta(self, folder_id: str, query: dict[str, str]) -> httpx.Response:
        """A delta query: the first call answers every message, a call with
        a deltatoken what changed since, with @removed for those gone."""
        token = query.get("$deltatoken")
        inside = {
            m["id"] for m in self.messages.values() if m["parentFolderId"] == folder_id
        }
        if token is None:
            items = [self._delta_item(i) for i in sorted(inside)]
        else:
            if token not in self.delta_links:
                return _error(410, "SyncStateNotFound", "the sync state is gone")
            folder, version, held = self.delta_links[token]
            assert folder == folder_id
            items = [
                self._delta_item(i)
                for i in sorted(inside)
                if i not in held or self.versions.get(i, 0) > version
            ]
            items += [
                {"id": i, "@removed": {"reason": "deleted"}}
                for i in sorted(held - inside)
            ]
        skip = int(query.get("$skiptoken", "0"))
        page = items[skip : skip + self.delta_page]
        base = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder_id}"
        body: dict[str, Any] = {"value": page}
        if skip + self.delta_page < len(items):
            again = f"$deltatoken={token}&" if token else ""
            body["@odata.nextLink"] = (
                f"{base}/messages/delta?{again}$skiptoken={skip + self.delta_page}"
            )
        else:
            new = f"dt{len(self.delta_links) + 1}"
            self.delta_links[new] = (folder_id, self.version, frozenset(inside))
            body["@odata.deltaLink"] = f"{base}/messages/delta?$deltatoken={new}"
        return _json(200, body)

    def _delta_item(self, message_id: str) -> dict[str, Any]:
        message = self.messages[message_id]
        return {"id": message_id, "createdDateTime": message["createdDateTime"]}

    # --- messages -------------------------------------------------------------------

    def _page(
        self, found: list[dict[str, Any]], query: dict[str, str], path: str
    ) -> httpx.Response:
        if "$filter" in query and "isRead eq false" in query["$filter"]:
            found = [m for m in found if not m["isRead"]]
        if "$filter" in query and query["$filter"].startswith("internetMessageId eq '"):
            header = query["$filter"].split("'", 1)[1][:-1].replace("''", "'")
            found = [m for m in found if m["internetMessageId"] == header]
        if "$filter" in query and query["$filter"].startswith("conversationId eq '"):
            conversation = query["$filter"].split("'", 1)[1][:-1].replace("''", "'")
            found = [m for m in found if m["conversationId"] == conversation]
            assert "$orderby" not in query, "Graph refuses an order beside it"
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
            more = (
                {"$filter": query["$filter"]}
                if "conversationId" in str(query.get("$filter"))
                else {}
            )
            rest = f"&{urlencode(more)}" if more else ""
            body["@odata.nextLink"] = (
                f"https://graph.microsoft.com{path}?%24top={top}&%24skip={skip + top}"
                + rest
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
            return self._one_message(method, message, request)
        if rest == ["$value"]:
            return httpx.Response(200, content=self.mime(message["id"]))
        if rest == ["move"]:
            target = self._folder(json.loads(request.content)["destinationId"])
            if target is None:
                return _error(404, "ErrorItemNotFound", "folder not found")
            message["parentFolderId"] = target["id"]
            self.touch(message["id"])
            return _json(201, message)
        if rest == ["send"] and method == "POST":
            return self._send(message)
        if rest[0] == "attachments" and method == "POST":
            return self._attach(message, rest[1:], json.loads(request.content))
        return _error(400, "BadRequest", "unknown message call")

    def _one_message(
        self, method: str, message: dict[str, Any], request: httpx.Request
    ) -> httpx.Response:
        if method == "GET":
            return _json(200, message)
        if method == "PATCH":
            body = json.loads(request.content)
            # Extended properties merge by their id, as Graph keeps them.
            both = message.get(PROPS, []) + body.pop(PROPS, [])
            message.update(body, **{PROPS: list({p["id"]: p for p in both}.values())})
            self.touch(message["id"])
            return _json(200, message)
        if method == "DELETE":
            # As Graph does: outside the trash, a delete moves the message
            # there. Deleted from the trash, it is gone.
            trash = self.well_known["deleteditems"]
            if message["parentFolderId"] != trash:
                message["parentFolderId"] = trash
                self.touch(message["id"])
            else:
                del self.messages[message["id"]]
            return httpx.Response(204)
        return _error(400, "BadRequest", "unknown message call")

    def mime(self, message_id: str) -> bytes:
        """The message's MIME, with the files added one by one."""
        files = self.files.get(message_id, [])
        if not files:
            return self.raws[message_id]
        parsed = message_from_bytes(self.raws[message_id], policy=default)
        for file in files:
            maintype, _, subtype = file["contentType"].partition("/")
            parsed.add_attachment(
                file["data"], maintype, subtype, filename=file["name"]
            )
        return parsed.as_bytes()

    def _attach(
        self, message: dict[str, Any], rest: list[str], body: dict[str, Any]
    ) -> httpx.Response:
        """A file in one request, or an upload session for a large one."""
        if not rest:
            data = base64.b64decode(body.pop("contentBytes"))
            self.files.setdefault(message["id"], []).append({**body, "data": data})
            return _json(201, {"id": f"file-{len(self.files[message['id']])}"})
        item = body["AttachmentItem"]
        if item["size"] < SESSION_MINIMUM:
            return _error(
                400,
                "ErrorAttachmentSizeShouldNotBeLessThanMinimumSize",
                "too small for an upload session",
            )
        session = f"s{len(self.sessions) + 1}"
        self.sessions[session] = {"message": message["id"], "item": item, "data": b""}
        url = f"https://{UPLOADS}/api/v2.0/AttachmentSessions/{session}"
        return _json(
            201, {"uploadUrl": f"{url}?authtoken=t", "nextExpectedRanges": ["0-"]}
        )

    def _upload(self, request: httpx.Request, session: str) -> httpx.Response:
        """A range of a file, in order, without a token of the account."""
        assert "authorization" not in request.headers
        assert len(request.content) <= REQUEST_LIMIT
        open_ = self.sessions[session]
        span, _, total = (
            request.headers["content-range"].removeprefix("bytes ").partition("/")
        )
        start = int(span.split("-")[0])
        assert start == len(open_["data"]), "ranges come in order"
        open_["data"] += request.content
        if len(open_["data"]) < int(total):
            return _json(200, {"nextExpectedRanges": [str(len(open_["data"]))]})
        item = open_["item"]
        self.files.setdefault(open_["message"], []).append(
            {**item, "data": open_["data"]}
        )
        del self.sessions[session]
        return httpx.Response(201)

    def _send(self, message: dict[str, Any]) -> httpx.Response:
        """A draft sent: its copy in Sent Items keeps the immutable id."""
        if self.send_answer is not None:
            answer, self.send_answer = self.send_answer, None
            return answer
        if not message["isDraft"]:
            return _error(400, "ErrorInvalidOperation", "not a draft")
        self.sent.append(self.mime(message["id"]))
        message.update(parentFolderId=self.well_known["sentitems"], isDraft=False)
        self.touch(message["id"])
        return httpx.Response(202)

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
