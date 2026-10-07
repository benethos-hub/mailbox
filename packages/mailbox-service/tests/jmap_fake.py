"""A JMAP server in memory, as an ``httpx.MockTransport`` handler. It answers
the calls the ``jmap`` adapter makes, the way RFC 8620 and 8621 describe
them, and records every request.

The session names its URLs on another host than the one asked, as a server
behind a proxy does: a client must use their paths on the server it knows.
"""

from __future__ import annotations

import base64
import itertools
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import anyio
import httpx

from .jmap_fake_mail import ACCOUNT, MailMethods

HOST = "jmap.example.com"
PORT = 443
USER = "me@example.com"
PASSWORD = "secret"
TOKEN = "api-token"
# Where the session says its URLs are: never asked directly.
NAMED = "https://internal.example.test"
ROLES = ("inbox", "drafts", "sent", "trash", "junk")


class FakeJmap(MailMethods):
    def __init__(self) -> None:
        self.ids = (f"m{n}" for n in itertools.count(1))
        self.blob_ids = (f"b{n}" for n in itertools.count(1))
        self.mailboxes: dict[str, dict[str, Any]] = {}
        for role in ROLES:
            self.add_mailbox(role.capitalize(), role=role)
        self.emails: dict[str, dict[str, Any]] = {}
        self.blobs: dict[str, bytes] = {}
        self.identities = [{"id": "i1", "email": USER, "name": "Me"}]
        self.submissions: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self.calls: list[str] = []
        # Changes to emails: (state, id, created|updated|destroyed).
        self.counter = 0
        self.log: list[tuple[int, str, str]] = []
        # States older than this cannot be calculated from.
        self.oldest = 0
        self.session_state = "s1"
        self.capabilities: dict[str, Any] = {
            "urn:ietf:params:jmap:core": {
                "maxConcurrentRequests": 4,
                "maxCallsInRequest": 16,
                "maxObjectsInGet": 500,
            },
            "urn:ietf:params:jmap:mail": {},
            "urn:ietf:params:jmap:submission": {},
        }
        self.event_source = True
        # Lines of the event stream, then it ends unless ``hold`` is set.
        self.events: list[str] = []
        self.hold = False
        # Given once to the next request instead of an answer of its own.
        self.next_answer: httpx.Response | None = None
        # Method name -> the error type its next call answers.
        self.method_errors: dict[str, str] = {}
        # Email/import and EmailSubmission/set refuse with this SetError.
        self.refuse_import: dict[str, Any] | None = None
        self.refuse_submission: dict[str, Any] | None = None
        # Mailbox/set and Email/set refuse ids with these SetErrors.
        self.refuse_set: dict[str, dict[str, Any]] = {}
        # Query results per page at most, as a server may cap them.
        self.query_cap: int | None = None

    # --- setting up -----------------------------------------------------------------

    def add_mailbox(
        self, name: str, role: str | None = None, parent: str | None = None
    ) -> str:
        mailbox_id = role or f"x{len(self.mailboxes) + 1}"
        self.mailboxes[mailbox_id] = {
            "id": mailbox_id,
            "name": name,
            "role": role,
            "parentId": parent,
            "isSubscribed": True,
        }
        return mailbox_id

    def add_email(
        self,
        raw: bytes,
        mailbox: str = "inbox",
        keywords: dict[str, bool] | None = None,
        received: str | None = None,
    ) -> str:
        email_id = next(self.ids)
        blob_id = next(self.blob_ids)
        self.blobs[blob_id] = raw
        self.emails[email_id] = {
            "id": email_id,
            "blobId": blob_id,
            "threadId": f"t{email_id}",
            "mailboxIds": {mailbox: True},
            "keywords": dict(keywords or {}),
            "receivedAt": received or f"2026-09-{len(self.emails) + 1:02d}T10:00:00Z",
        }
        self.change(email_id, "created")
        return email_id

    def change(self, email_id: str, kind: str) -> None:
        self.counter += 1
        self.log.append((self.counter, email_id, kind))

    @property
    def state(self) -> str:
        return f"s{self.counter}"

    def other_client_changes(self, email_id: str, **fields: Any) -> None:
        """Another client changes an email, e.g. its mailboxIds."""
        self.emails[email_id].update(fields)
        self.change(email_id, "updated")

    def other_client_deletes(self, email_id: str) -> None:
        del self.emails[email_id]
        self.change(email_id, "destroyed")

    def raw_of(self, email_id: str) -> bytes:
        return self.blobs[self.emails[email_id]["blobId"]]

    # --- the transport --------------------------------------------------------------

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.next_answer is not None:
            answer, self.next_answer = self.next_answer, None
            return answer
        url = urlsplit(str(request.url))
        assert request.headers["host"].split(":")[0] == HOST, request.headers["host"]
        auth = request.headers.get("authorization", "")
        basic = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        if auth not in (f"Basic {basic}", f"Bearer {TOKEN}"):
            return httpx.Response(
                401, headers={"WWW-Authenticate": 'Basic realm="jmap"'}
            )
        path = url.path
        if path == "/.well-known/jmap":
            return httpx.Response(307, headers={"Location": "/jmap/session"})
        if path == "/jmap/session":
            return httpx.Response(200, json=self.session())
        if path == "/jmap/" and request.method == "POST":
            return self.api(json.loads(request.content))
        if path == f"/jmap/upload/{ACCOUNT}/" and request.method == "POST":
            blob_id = next(self.blob_ids)
            self.blobs[blob_id] = request.content
            return httpx.Response(201, json={"blobId": blob_id, "size": 1})
        if path.startswith(f"/jmap/download/{ACCOUNT}/"):
            blob_id = unquote(path.split("/")[4])
            if blob_id not in self.blobs:
                return httpx.Response(404)
            return httpx.Response(200, content=self.blobs[blob_id])
        if path == "/jmap/eventsource/":
            query = parse_qs(url.query)
            assert query["closeafter"] == ["no"], query
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=self.stream(),
            )
        return httpx.Response(404)

    async def stream(self) -> AsyncIterator[bytes]:
        for line in self.events:
            yield (line + "\n").encode()
        if self.hold:
            await anyio.sleep_forever()

    def session(self) -> dict[str, Any]:
        session: dict[str, Any] = {
            "capabilities": self.capabilities,
            "accounts": {
                ACCOUNT: {
                    "name": USER,
                    "accountCapabilities": {
                        k: {} for k in self.capabilities if not k.endswith("core")
                    },
                }
            },
            "primaryAccounts": {
                "urn:ietf:params:jmap:mail": ACCOUNT,
                "urn:ietf:params:jmap:submission": ACCOUNT,
            },
            "username": USER,
            "apiUrl": f"{NAMED}/jmap/",
            "downloadUrl": (
                f"{NAMED}/jmap/download/{{accountId}}/{{blobId}}/{{name}}"
                "?accept={type}"
            ),
            "uploadUrl": f"{NAMED}/jmap/upload/{{accountId}}/",
            "state": self.session_state,
        }
        if self.event_source:
            session["eventSourceUrl"] = (
                f"{NAMED}/jmap/eventsource/?types={{types}}"
                "&closeafter={closeafter}&ping={ping}"
            )
        return session

    # --- the API --------------------------------------------------------------------

    def api(self, body: dict[str, Any]) -> httpx.Response:
        responses: list[list[Any]] = []
        self.created: dict[str, str] = {}
        for name, args, tag in body["methodCalls"]:
            self.calls.append(name)
            assert args.get("accountId") == ACCOUNT, (name, args)
            if name in self.method_errors:
                kind = self.method_errors.pop(name)
                responses.append(["error", {"type": kind}, tag])
                continue
            try:
                args = self.resolve(args, responses)
            except LookupError:
                responses.append(["error", {"type": "invalidResultReference"}, tag])
                continue
            handler = getattr(self, name.replace("/", "_").lower(), None)
            if handler is None:
                responses.append(["error", {"type": "unknownMethod"}, tag])
                continue
            for answer in handler(args, body["using"]):
                responses.append([answer[0], answer[1], tag])
        return httpx.Response(
            200,
            json={"methodResponses": responses, "sessionState": self.session_state},
        )

    def resolve(
        self, args: dict[str, Any], responses: list[list[Any]]
    ) -> dict[str, Any]:
        """Back-references (RFC 8620 3.7): ``#ids`` from an earlier result."""
        found = dict(args)
        for key in [k for k in args if k.startswith("#")]:
            ref = found.pop(key)
            earlier = next(
                (
                    r
                    for r in responses
                    if r[2] == ref["resultOf"] and r[0] == ref["name"]
                ),
                None,
            )
            if earlier is None:
                raise LookupError(key)
            value: Any = earlier[1]
            for part in ref["path"].strip("/").split("/"):
                value = value[part]
            found[key[1:]] = value if isinstance(value, list) else [value]
        return found

    def identity_get(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        assert "urn:ietf:params:jmap:submission" in using
        return [("Identity/get", {"accountId": ACCOUNT, "list": self.identities})]

    def emailsubmission_set(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        assert "urn:ietf:params:jmap:submission" in using
        answer: dict[str, Any] = {"accountId": ACCOUNT}
        follow: list[Any] = []
        for key, new in args["create"].items():
            if self.refuse_submission is not None:
                answer.setdefault("notCreated", {})[key] = self.refuse_submission
                continue
            email_id = self.created.get(new["emailId"].lstrip("#"), new["emailId"])
            if email_id not in self.emails:
                answer.setdefault("notCreated", {})[key] = {"type": "invalidProperties"}
                continue
            self.submissions.append({**new, "emailId": email_id})
            answer.setdefault("created", {})[key] = {
                "id": f"sub{len(self.submissions)}"
            }
            ref = f"#{key}"
            if ref in (args.get("onSuccessUpdateEmail") or {}):
                follow += self.email_set(
                    {
                        "accountId": ACCOUNT,
                        "update": {email_id: args["onSuccessUpdateEmail"][ref]},
                    },
                    using,
                )
            if ref in (args.get("onSuccessDestroyEmail") or []):
                follow += self.email_set(
                    {"accountId": ACCOUNT, "destroy": [email_id]}, using
                )
        return [("EmailSubmission/set", answer), *follow]
