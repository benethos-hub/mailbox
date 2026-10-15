"""Sending, drafts, idempotency, the send limit, links to attachments
(docs/LOGGING.md 5.6, 5.9).

Drafts are mail content and change nothing others see: not logged. A
send names the count of its recipients, never their addresses: those are
in the audit of sends alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from benethos_mailbox_common.log import lines
from benethos_mailbox_common.values import text

from ....data.models import Account
from ..base import Activity, Failure, Purged, account


@dataclass(frozen=True, kw_only=True)
class MessageSent(Activity):
    name: ClassVar[str] = "sent"

    account: Account
    recipients: int
    # The sent copy, else the Message-ID the message went out with.
    message: str

    def says(self) -> str:
        return (
            f"sent a message from {account(self.account)} to "
            f"{text.plural(self.recipients, 'recipient')}: {self.message}"
        )


@dataclass(frozen=True, kw_only=True)
class SendRefused(Activity):
    """The grants do not allow the send, ``denied`` in the audit of sends.
    The reason is the error's code, as in the audit: its message may name
    a recipient."""

    name: ClassVar[str] = "refused"
    level: ClassVar[int] = logging.WARNING

    account_id: str
    code: str

    def says(self) -> str:
        return f"was refused to send from {self.account_id}"

    def why(self) -> str:
        return self.code


@dataclass(frozen=True, kw_only=True)
class SendFailed(Activity):
    """The provider did not take the message, ``failed`` in the audit of
    sends. The reason is the error's code: a mail server's answer may name
    a recipient."""

    name: ClassVar[str] = "send_failed"
    level: ClassVar[int] = logging.WARNING

    account_id: str
    code: str

    def says(self) -> str:
        return f"could not send from {self.account_id}"

    def why(self) -> str:
        return self.code


@dataclass(frozen=True, kw_only=True)
class SentBut(Failure):
    """A step after the message went out failed. The send stands."""

    name: ClassVar[str] = "sent_but"

    account: Account
    what: str

    def says(self) -> str:
        return f"sent a message from {account(self.account)}, but {self.what}"


@dataclass(frozen=True, kw_only=True)
class NotInAudit(Failure):
    name: ClassVar[str] = "not_in_audit"
    level: ClassVar[int] = logging.ERROR

    account_id: str

    def says(self) -> str:
        return (
            f"sent a message from {self.account_id}, but it is not in the audit "
            "of sends"
        )


@dataclass(frozen=True, kw_only=True)
class SendLimitReached(Activity):
    """The grants' limit of mails in 24 hours. The audit of sends has the
    attempt as ``denied``."""

    name: ClassVar[str] = "send_limit"
    level: ClassVar[int] = logging.WARNING

    account_id: str
    reason: str
    retry_after: int

    def says(self) -> str:
        return f"reached the send limit on {self.account_id}"

    def why(self) -> str:
        return f"{self.reason}, the next in {self.retry_after}s"


@dataclass(frozen=True, kw_only=True)
class SendsPurged(Purged):
    """Records older than the audit keeps are gone. The normal course,
    once an hour at most, so no warning."""

    name: ClassVar[str] = "sends_purged"
    purged_from: ClassVar[str] = "the audit of sends"


@dataclass(frozen=True, kw_only=True)
class Replayed(Activity):
    """A retry with the same Idempotency-Key got the first result."""

    name: ClassVar[str] = "replayed"
    level: ClassVar[int] = logging.DEBUG

    account_id: str
    operation: str

    def says(self) -> str:
        return (
            f"answered {self.operation} on {self.account_id} with the result of "
            "its Idempotency-Key"
        )


@dataclass(frozen=True, kw_only=True)
class ResultNotKept(Failure):
    """The result of a request with an Idempotency-Key, done but not
    stored: a retry would do it again."""

    name: ClassVar[str] = "result_not_kept"
    level: ClassVar[int] = logging.ERROR

    account_id: str
    operation: str

    def says(self) -> str:
        return (
            f"did {self.operation} on {self.account_id}, but could not keep its "
            "result for the Idempotency-Key"
        )


@dataclass(frozen=True, kw_only=True)
class LinkShared(Activity):
    """A link to an attachment made. Never its secret, never its URL."""

    name: ClassVar[str] = "link_shared"
    audited: ClassVar[bool] = True

    link_id: str
    account_id: str
    message_id: str
    attachment_id: str
    seconds: int

    def says(self) -> str:
        return (
            f"shared attachment {self.attachment_id} of {self.message_id} in "
            f"{self.account_id} as link {self.link_id} for {self.seconds}s"
        )

    def touched(self) -> str | None:
        return self.link_id


@dataclass(frozen=True, kw_only=True)
class LinkUsed(Activity):
    """A link to an attachment used. The actor is the user of the token
    that made it, the source the address that fetched it."""

    name: ClassVar[str] = "link_used"
    audited: ClassVar[bool] = True

    link_id: str
    account_id: str
    message_id: str
    attachment_id: str

    def says(self) -> str:
        return (
            f"had attachment {self.attachment_id} of {self.message_id} in "
            f"{self.account_id} fetched through link {self.link_id}"
        )

    def touched(self) -> str | None:
        return self.link_id


@dataclass(frozen=True, kw_only=True)
class LinkRefused(Activity):
    """A link that exists, refused: used, ended, or its token or rights
    gone. A secret that is no link's writes no line, as a wrong token
    does not."""

    name: ClassVar[str] = "link_refused"
    level: ClassVar[int] = logging.WARNING

    link_id: str
    reason: str

    def says(self) -> str:
        return f"was refused link {self.link_id}"

    def why(self) -> str:
        return self.reason


@dataclass(frozen=True, kw_only=True)
class LinksPurged(Purged):
    """Links used or ended are gone. The normal course, so no warning."""

    name: ClassVar[str] = "links_purged"
    record: ClassVar[str] = "link"

    def says(self) -> str:
        return (
            f"purged {text.plural(self.count, self.record)} to attachments, "
            f"used or ended by {lines.log_time(self.before)}"
        )
