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
from collections.abc import AsyncIterator, Callable
from email import message_from_bytes
from email.policy import default
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import anyio
import httpx

HOST = "jmap.example.com"
PORT = 443
USER = "me@example.com"
PASSWORD = "secret"
TOKEN = "api-token"
ACCOUNT = "acc1"
# Where the session says its URLs are: never asked directly.
NAMED = "https://internal.example.test"
ROLES = ("inbox", "drafts", "sent", "trash", "junk")


class FakeJmap:
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
            handler = getattr(self, name.replace("/", "_"), None)
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

    def Mailbox_get(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        ids = args.get("ids")
        found = [
            self.mailbox_json(m)
            for m in self.mailboxes.values()
            if ids is None or m["id"] in ids
        ]
        return [("Mailbox/get", {"accountId": ACCOUNT, "list": found, "state": "m1"})]

    def mailbox_json(self, mailbox: dict[str, Any]) -> dict[str, Any]:
        inside = [e for e in self.emails.values() if mailbox["id"] in e["mailboxIds"]]
        return {
            **mailbox,
            "totalEmails": len(inside),
            "unreadEmails": sum("$seen" not in e["keywords"] for e in inside),
        }

    def Mailbox_set(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        answer: dict[str, Any] = {"accountId": ACCOUNT}
        for key, new in (args.get("create") or {}).items():
            mailbox_id = self.add_mailbox(new["name"], parent=new.get("parentId"))
            self.mailboxes[mailbox_id]["isSubscribed"] = new.get("isSubscribed", False)
            answer.setdefault("created", {})[key] = {"id": mailbox_id}
        for mailbox_id, patch in (args.get("update") or {}).items():
            if mailbox_id in self.refuse_set:
                answer.setdefault("notUpdated", {})[mailbox_id] = self.refuse_set[
                    mailbox_id
                ]
            elif mailbox_id not in self.mailboxes:
                answer.setdefault("notUpdated", {})[mailbox_id] = {"type": "notFound"}
            else:
                self.mailboxes[mailbox_id].update(patch)
                answer.setdefault("updated", {})[mailbox_id] = None
        for mailbox_id in args.get("destroy") or []:
            assert args.get("onDestroyRemoveEmails") is False
            if mailbox_id not in self.mailboxes:
                answer.setdefault("notDestroyed", {})[mailbox_id] = {"type": "notFound"}
            elif any(mailbox_id in e["mailboxIds"] for e in self.emails.values()):
                answer.setdefault("notDestroyed", {})[mailbox_id] = {
                    "type": "mailboxHasEmail"
                }
            else:
                del self.mailboxes[mailbox_id]
                answer.setdefault("destroyed", []).append(mailbox_id)
        return [("Mailbox/set", answer)]

    def Email_query(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        assert args["sort"] == [{"property": "receivedAt", "isAscending": False}]
        found = [e for e in self.emails.values() if self.matches(e, args["filter"])]
        found.sort(key=lambda e: e["receivedAt"], reverse=True)
        ids = [e["id"] for e in found]
        position = args.get("position", 0)
        if "anchor" in args:
            if args["anchor"] not in ids:
                return [("error", {"type": "anchorNotFound"})]
            position = ids.index(args["anchor"]) + args.get("anchorOffset", 0)
        limit = args.get("limit", 1000)
        answer: dict[str, Any] = {"accountId": ACCOUNT, "position": position}
        if self.query_cap is not None and limit > self.query_cap:
            limit = answer["limit"] = self.query_cap
        answer["ids"] = ids[position : position + limit]
        return [("Email/query", answer)]

    def matches(self, email: dict[str, Any], condition: dict[str, Any]) -> bool:
        if "operator" in condition:
            assert condition["operator"] == "AND"
            return all(self.matches(email, c) for c in condition["conditions"])
        parsed = self.parsed(email)
        return all(
            _CONDITIONS[key](email, parsed, value)
            for key, value in condition.items()
            if key in _CONDITIONS
        )

    def parsed(self, email: dict[str, Any]) -> dict[str, Any]:
        msg = message_from_bytes(self.blobs.get(email["blobId"], b""), policy=default)
        body = msg.get_body(("plain",))
        text = body.get_content() if body is not None else ""
        return {
            "subject": str(msg["subject"] or ""),
            "from": [
                {"name": n or None, "email": a}
                for n, a in getaddresses([str(msg["from"] or "")])
                if a
            ],
            "to": [
                {"name": n or None, "email": a}
                for n, a in getaddresses([str(msg["to"] or "")])
                if a
            ],
            "messageId": [str(msg["message-id"]).strip("<>")]
            if msg["message-id"]
            else None,
            "sentAt": parsedate_to_datetime(str(msg["date"])).isoformat()
            if msg["date"]
            else None,
            "preview": text[:50],
            "text": text,
            "attached": any(True for _ in msg.iter_attachments()),
        }

    def email_json(
        self, email: dict[str, Any], properties: list[str]
    ) -> dict[str, Any]:
        parsed = self.parsed(email)
        full = {
            **email,
            "subject": parsed["subject"],
            "from": parsed["from"],
            "to": parsed["to"],
            "messageId": parsed["messageId"],
            "sentAt": parsed["sentAt"],
            "preview": parsed["preview"],
            "hasAttachment": parsed["attached"],
        }
        return {p: full.get(p) for p in ["id", *properties]}

    def Email_get(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        ids = args.get("ids") or []
        assert len(ids) <= 500
        properties = args.get("properties") or ["id"]
        return [
            (
                "Email/get",
                {
                    "accountId": ACCOUNT,
                    "state": self.state,
                    "list": [
                        self.email_json(self.emails[i], properties)
                        for i in ids
                        if i in self.emails
                    ],
                    "notFound": [i for i in ids if i not in self.emails],
                },
            )
        ]

    def Email_set(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        answer: dict[str, Any] = {"accountId": ACCOUNT}
        for email_id, patch in (args.get("update") or {}).items():
            email_id = self.created.get(email_id.lstrip("#"), email_id)
            if email_id in self.refuse_set:
                answer.setdefault("notUpdated", {})[email_id] = self.refuse_set[
                    email_id
                ]
                continue
            email = self.emails.get(email_id)
            if email is None:
                answer.setdefault("notUpdated", {})[email_id] = {"type": "notFound"}
                continue
            for path, value in patch.items():
                if path == "mailboxIds":
                    if any(m not in self.mailboxes for m in value):
                        answer.setdefault("notUpdated", {})[email_id] = {
                            "type": "invalidProperties"
                        }
                        break
                    email["mailboxIds"] = dict(value)
                    continue
                field, _, key = path.partition("/")
                key = key.replace("~1", "/").replace("~0", "~")
                if value is None:
                    email[field].pop(key, None)
                else:
                    email[field][key] = value
            else:
                self.change(email_id, "updated")
                answer.setdefault("updated", {})[email_id] = None
        for email_id in args.get("destroy") or []:
            email_id = self.created.get(email_id.lstrip("#"), email_id)
            if email_id not in self.emails:
                answer.setdefault("notDestroyed", {})[email_id] = {"type": "notFound"}
                continue
            self.other_client_deletes(email_id)
            answer.setdefault("destroyed", []).append(email_id)
        return [("Email/set", answer)]

    def Email_import(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        answer: dict[str, Any] = {"accountId": ACCOUNT}
        for key, new in args["emails"].items():
            if self.refuse_import is not None:
                answer.setdefault("notCreated", {})[key] = self.refuse_import
                continue
            raw = self.blobs[new["blobId"]]
            email_id = self.add_email(
                raw,
                next(iter(new["mailboxIds"])),
                new.get("keywords"),
                received=f"2026-10-{len(self.emails) + 1:02d}T10:00:00Z",
            )
            self.emails[email_id]["mailboxIds"] = dict(new["mailboxIds"])
            self.created[key] = email_id
            answer.setdefault("created", {})[key] = {"id": email_id}
        return [("Email/import", answer)]

    def Email_changes(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        since = args["sinceState"]
        if not since.startswith("s") or int(since[1:]) < self.oldest:
            return [("error", {"type": "cannotCalculateChanges"})]
        start = int(since[1:])
        limit = args.get("maxChanges", 1000)
        entries = [e for e in self.log if e[0] > start][:limit]
        end = entries[-1][0] if entries else start
        kinds: dict[str, set[str]] = {
            "created": set(),
            "updated": set(),
            "destroyed": set(),
        }
        for _, email_id, kind in entries:
            kinds[kind].add(email_id)
        kinds["updated"] -= kinds["created"]
        return [
            (
                "Email/changes",
                {
                    "accountId": ACCOUNT,
                    "oldState": since,
                    "newState": f"s{end}",
                    "hasMoreChanges": end < self.counter,
                    **{k: sorted(v) for k, v in kinds.items()},
                },
            )
        ]

    def Identity_get(self, args: dict[str, Any], using: list[str]) -> list[Any]:
        assert "urn:ietf:params:jmap:submission" in using
        return [("Identity/get", {"accountId": ACCOUNT, "list": self.identities})]

    def EmailSubmission_set(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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
                follow += self.Email_set(
                    {
                        "accountId": ACCOUNT,
                        "update": {email_id: args["onSuccessUpdateEmail"][ref]},
                    },
                    using,
                )
            if ref in (args.get("onSuccessDestroyEmail") or []):
                follow += self.Email_set(
                    {"accountId": ACCOUNT, "destroy": [email_id]}, using
                )
        return [("EmailSubmission/set", answer), *follow]


def _contains(field: str) -> Callable[[dict[str, Any], dict[str, Any], Any], bool]:
    return lambda email, parsed, value: value.lower() in str(parsed[field]).lower()


# The conditions of a FilterCondition the fake knows: whether an email,
# with what its source says, meets each.
_CONDITIONS: dict[str, Callable[[dict[str, Any], dict[str, Any], Any], bool]] = {
    "inMailbox": lambda email, parsed, value: value in email["mailboxIds"],
    "text": _contains("text"),
    "from": _contains("from"),
    "to": _contains("to"),
    "subject": _contains("subject"),
    "after": lambda email, parsed, value: email["receivedAt"] >= value,
    "before": lambda email, parsed, value: email["receivedAt"] < value,
    "hasKeyword": lambda email, parsed, value: value in email["keywords"],
    "notKeyword": lambda email, parsed, value: value not in email["keywords"],
    "hasAttachment": lambda email, parsed, value: value == parsed["attached"],
}
