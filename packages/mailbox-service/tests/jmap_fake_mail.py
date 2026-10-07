"""The mail of the fake JMAP server: the Mailbox and Email methods of
RFC 8621 that ``jmap_fake.FakeJmap`` answers, on the one account it holds.
"""

from __future__ import annotations

from collections.abc import Callable
from email import message_from_bytes
from email.policy import default
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

ACCOUNT = "acc1"


class MailMethods:
    """Mailbox/get, Mailbox/set, Email/query, Email/get, Email/set,
    Email/import and Email/changes. ``FakeJmap`` holds the state they work
    on and adds mailboxes, emails and changes."""

    mailboxes: dict[str, dict[str, Any]]
    emails: dict[str, dict[str, Any]]
    blobs: dict[str, bytes]
    created: dict[str, str]
    counter: int
    log: list[tuple[int, str, str]]
    oldest: int
    refuse_import: dict[str, Any] | None
    refuse_set: dict[str, dict[str, Any]]
    query_cap: int | None

    def mailbox_get(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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

    def mailbox_set(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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

    def email_query(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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

    def email_get(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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

    def email_set(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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

    def email_import(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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

    def email_changes(self, args: dict[str, Any], using: list[str]) -> list[Any]:
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
