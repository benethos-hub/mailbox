"""Messages as read, their attachments, and changes to them."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .accounts import Mark

MARKS = frozenset(m.value for m in Mark)


class MessageReference(BaseModel):
    """Reply to or forward a message of the same account. The service sets
    the recipients of a reply where none are given, the subject prefix,
    In-Reply-To, References and the quote."""

    message_id: str
    action: Literal["reply", "reply_all", "forward"]
    forward_as: Literal["inline", "attachment"] = Field(
        default="inline",
        description=(
            "`inline`: quoted with its headers, its attachments attached. "
            "`attachment`: the unchanged original as `message/rfc822`. "
            "Ignored for replies."
        ),
    )
    quote: bool = Field(
        default=True,
        description=(
            "`false`: the text holds the quote already, e.g. a stored draft "
            "edited as a whole. The link to the original stays (In-Reply-To, "
            "References, the mark on the original after sending), but nothing "
            "of the original is added: no quote, no forwarded original, none "
            "of its attachments."
        ),
    )


class Address(BaseModel):
    email: str
    name: str | None = None


class MessageSummary(BaseModel):
    id: str
    account_id: str | None = None
    thread_id: str | None = None
    folder_ids: list[str] = Field(default_factory=list)
    subject: str | None = None
    sender: Address | None = Field(default=None, alias="from")
    to: list[Address] = Field(default_factory=list)
    date: datetime | None = Field(
        default=None,
        description="The Date header: when the sender wrote the message, as "
        "every mail program shows it. Null without one.",
    )
    received: datetime | None = Field(
        default=None,
        description="When the account received the message. Lists sort by "
        "it, and `after` and `before` compare it. On POP3 it is read from "
        "the topmost `Received` header, and null without one.",
    )
    snippet: str | None = None
    unread: bool = False
    starred: bool = False
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Further flags, the marks named as in JMAP: `$answered`, "
            "`$forwarded`, `$draft`, and the provider's own keywords as it "
            "spells them, compared without case. Notes a server keeps for "
            "itself, such as `$hasnoattachment`, are left out."
        ),
    )
    has_attachments: bool = Field(
        default=False,
        description="Whether the message has a part a person sees as an "
        "attachment, not one the body shows in its place such as an image in "
        "the HTML. In a list of an IMAP account it is read from the header: "
        "whether the message is multipart/mixed.",
    )

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


def received_or_written(message: MessageSummary) -> datetime | None:
    """When a message came, for order: its received time, else its Date
    header, as on a POP3 mail without a ``Received`` header."""
    return message.received or message.date


class Attachment(BaseModel):
    id: str
    filename: str | None = None
    content_type: str
    size: int
    inline: bool = False


class AttachmentContent(BaseModel):
    """An attachment with its bytes, for download."""

    filename: str | None = None
    content_type: str
    data: bytes


class Message(MessageSummary):
    cc: list[Address] = Field(default_factory=list)
    bcc: list[Address] = Field(default_factory=list)
    reply_to: list[Address] = Field(default_factory=list)
    message_id_header: str | None = None
    in_reply_to: str | None = None
    text_body: str | None = None
    html_body: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    reference: MessageReference | None = Field(
        default=None,
        description=(
            "Of a draft: the message it answers or forwards, used when it is "
            "sent. To change the draft as a whole and keep this link, pass it "
            "back to `update_draft` with `quote: false`."
        ),
    )


# Search text on one line: a line break would end the IMAP command and start
# another one of the caller's choosing.
SEARCH_TEXT_PATTERN = r"^[^\x00-\x1f\x7f]{1,200}$"


class MessageFilter(BaseModel):
    """What a list keeps. Fields left out do not filter. Several narrow it
    down together."""

    text: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    sender: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    to: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    subject: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    # Received on or after this day, and before this day.
    after: date | None = None
    before: date | None = None
    unread: bool | None = None
    starred: bool | None = None
    has_attachments: bool | None = None

    def flags_match(self, message: MessageSummary) -> bool:
        """Whether ``message`` is unread, starred and has attachments as
        asked. The rest of the filter is not looked at."""
        return (
            (self.unread is None or message.unread == self.unread)
            and (self.starred is None or message.starred == self.starred)
            and (
                self.has_attachments is None
                or message.has_attachments == self.has_attachments
            )
        )


# A keyword on one line, not a system flag (those start with a
# backslash). An Outlook category may hold spaces: IMAP and JMAP take an
# atom alone, and answer anything else with 400.
KEYWORD_PATTERN = r"^[^\x00-\x1f\x7f\\][^\x00-\x1f\x7f]{0,99}$"
# Notes a server keeps for itself, not keywords of the message (UNIFORM
# 6.2): one repeats has_attachments, the others are its bookkeeping.
SERVER_NOTES = frozenset(
    {"$hasattachment", "$hasnoattachment", "$mdnsent", "$submitpending", "$submitted"}
)


def as_keyword(found: str) -> str | None:
    """A provider's keyword as the API answers it: a mark in the spelling
    of RFC 8621, any other as the provider spells it, a server note not
    at all. Keywords compare without case."""
    lowered = found.lower()
    if lowered in SERVER_NOTES:
        return None
    return lowered if lowered in MARKS else found


# Keywords that would bypass unread, starred or deletion.
RESERVED_KEYWORDS = frozenset({"$seen", "$flagged", "$deleted", "$recent"})


Keywords = Annotated[
    list[Annotated[str, Field(pattern=KEYWORD_PATTERN)]] | None,
    Field(max_length=50),
]
FolderIds = Annotated[list[str] | None, Field(max_length=20)]


class MessageUpdate(BaseModel):
    """What ``PATCH`` changes on a message. Fields left out stay as they are."""

    unread: bool | None = None
    starred: bool | None = None
    keywords: Keywords = Field(
        default=None,
        description=(
            "Replaces the list of keywords. Needs `keywords`. A mark such as "
            "`$answered` needs to be among the account's `marks.written`."
        ),
    )
    add_keywords: Keywords = Field(
        default=None, description="Added to the keywords it has. Not beside `keywords`."
    )
    remove_keywords: Keywords = Field(
        default=None,
        description="Taken off the keywords it has. Not beside `keywords`.",
    )
    folder_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description=(
            "The folders the message is to be in, by id or by a role such as "
            "`archive`. A change moves it, and the id stays. Needs `move`, and "
            "more than one folder `labels`."
        ),
    )
    add_folder_ids: FolderIds = Field(
        default=None,
        description=(
            "Folders the message is to be in as well, by id or by a role, such "
            "as a Gmail label. Only where a message can be in several folders "
            "(`labels`). Not beside `folder_ids`."
        ),
    )
    remove_folder_ids: FolderIds = Field(
        default=None,
        description=(
            "Folders the message is to leave, by id or by a role. Only where a "
            "message can be in several folders (`labels`), and one folder at "
            "least stays. Not beside `folder_ids`."
        ),
    )

    @field_validator("keywords", "add_keywords", "remove_keywords")
    @classmethod
    def _no_reserved_keywords(cls, keywords: list[str] | None) -> list[str] | None:
        reserved = sorted({k.lower() for k in keywords or []} & RESERVED_KEYWORDS)
        if reserved:
            raise ValueError(
                f"{', '.join(reserved)}: use unread, starred or a delete instead"
            )
        return keywords

    @model_validator(mode="after")
    def _replace_or_add(self) -> MessageUpdate:
        if self.keywords is not None and (self.add_keywords or self.remove_keywords):
            raise ValueError("keywords replaces them: not beside add or remove")
        if self.folder_ids is not None and (
            self.add_folder_ids or self.remove_folder_ids
        ):
            raise ValueError("folder_ids replaces them: not beside add or remove")
        both = {k.lower() for k in self.add_keywords or []} & {
            k.lower() for k in self.remove_keywords or []
        }
        both |= set(self.add_folder_ids or []) & set(self.remove_folder_ids or [])
        if both:
            raise ValueError(f"added and removed at once: {', '.join(sorted(both))}")
        return self

    @property
    def changes_keywords(self) -> bool:
        return (
            self.keywords is not None
            or bool(self.add_keywords)
            or bool(self.remove_keywords)
        )

    @property
    def changes_folders(self) -> bool:
        return (
            self.folder_ids is not None
            or bool(self.add_folder_ids)
            or bool(self.remove_folder_ids)
        )

    @property
    def adds_or_removes_folders(self) -> bool:
        return bool(self.add_folder_ids) or bool(self.remove_folder_ids)

    def named_folders(self) -> list[str]:
        """Every folder the change names: those to be in, to join and to
        leave."""
        return [
            *(self.folder_ids or []),
            *(self.add_folder_ids or []),
            *(self.remove_folder_ids or []),
        ]

    def keywords_after(self, current: Iterable[str]) -> dict[str, str] | None:
        """The keywords of a message that has ``current`` once changed, by
        their lower case: one it has as it is spelled there, a new one as
        the caller spelled it. None where the keywords stay as they are."""
        if not self.changes_keywords:
            return None
        have = {k.lower(): k for k in current}
        if self.keywords is not None:
            return {k.lower(): have.get(k.lower(), k) for k in self.keywords}
        for keyword in self.remove_keywords or []:
            have.pop(keyword.lower(), None)
        for keyword in self.add_keywords or []:
            have.setdefault(keyword.lower(), keyword)
        return have

    def new_keywords(self) -> list[str]:
        """Every keyword the change sets or adds, as the caller spelled it."""
        return [*(self.keywords or []), *(self.add_keywords or [])]

    def folders_after(self, current: Iterable[str]) -> list[str] | None:
        """The folders of a message that is in ``current`` once changed, in
        the order named. None where it stays where it is."""
        if self.folder_ids is not None:
            return list(dict.fromkeys(self.folder_ids))
        if not self.adds_or_removes_folders:
            return None
        removed = set(self.remove_folder_ids or [])
        kept = [f for f in current if f not in removed]
        return list(dict.fromkeys([*kept, *(self.add_folder_ids or [])]))
