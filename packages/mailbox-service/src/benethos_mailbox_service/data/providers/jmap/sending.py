"""Sending through JMAP (RFC 8621 7): the message is stored in the
drafts folder, submitted, and moved to the sent folder once the server
took it. Without a sent folder no copy is kept."""

from __future__ import annotations

from typing import Any

from ....errors import (
    ConflictError,
    MailboxServiceError,
    NotSupportedError,
    ProviderError,
)
from ...models import Folder, FolderRole, SentMessage
from ...protocols import jmap
from .. import rules
from . import mappers
from .account import JmapAccount

WITH_SUBMISSION = (jmap.CORE, jmap.MAIL, jmap.SUBMISSION)


async def send(
    account: JmapAccount, raw: bytes, sender: str, recipients: list[str]
) -> SentMessage:
    """The recipients go in the envelope, Bcc among them: the source
    names none of those."""
    session = await account.client.session()
    if not session.offers(jmap.SUBMISSION):
        raise NotSupportedError("the JMAP server offers no sending for this login")
    folders = await account.folders()
    drafts = rules.role_folder(folders, FolderRole.DRAFTS)
    sent = rules.role_folder(folders, FolderRole.SENT)
    holder = drafts or sent
    if holder is None:
        raise ConflictError("the account has no drafts or sent folder to send from")
    identity = await _identity(account, sender)
    blob = await account.upload(raw)
    keywords = {mappers.SEEN: True}
    if holder is drafts:
        keywords[mappers.DRAFT] = True
    answers = await account.call(
        (
            "Email/import",
            {
                "accountId": session.account_id,
                "emails": {
                    "m": {
                        "blobId": blob,
                        "mailboxIds": {holder.id: True},
                        "keywords": keywords,
                    }
                },
            },
            "i",
        ),
        (
            "EmailSubmission/set",
            _submission(session.account_id, identity, sender, recipients, holder, sent),
            "s",
        ),
        using=WITH_SUBMISSION,
    )
    imported = jmap.result(answers, "i")
    refused = (imported.get("notCreated") or {}).get("m")
    if refused is not None:
        raise jmap.set_error(refused, "message")
    stored = (imported.get("created") or {}).get("m") or {}
    if not stored.get("id"):
        raise ProviderError("the JMAP server did not store the message to send")
    email_id = str(stored["id"])
    failed = _submission_failure(answers)
    if failed is not None:
        await _forget(account, email_id)
        raise failed
    # Sent: from here on nothing may fail, or a client would send again.
    if sent is None:
        return SentMessage()
    try:
        copy = await account.email(email_id, mappers.SUMMARY_PROPERTIES)
    except MailboxServiceError as exc:
        return SentMessage(copy_error=exc.message)
    return SentMessage(sent_copy=mappers.summary(copy))


def _submission(
    owner: str,
    identity: str,
    sender: str,
    recipients: list[str],
    holder: Folder,
    sent: Folder | None,
) -> dict[str, Any]:
    """The ``EmailSubmission/set`` of the message imported as ``#m``: it
    goes to the sent folder once sent, or away without one."""
    submission: dict[str, Any] = {
        "accountId": owner,
        "create": {
            "s": {
                "identityId": identity,
                "emailId": "#m",
                "envelope": {
                    "mailFrom": {"email": sender},
                    "rcptTo": [{"email": r} for r in recipients],
                },
            }
        },
    }
    if sent is None:
        submission["onSuccessDestroyEmail"] = ["#s"]
    elif holder is not sent:
        submission["onSuccessUpdateEmail"] = {
            "#s": {
                f"mailboxIds/{holder.id}": None,
                f"mailboxIds/{sent.id}": True,
                f"keywords/{mappers.DRAFT}": None,
            }
        }
    return submission


async def _identity(account: JmapAccount, sender: str) -> str:
    """The identity to send as: the one with the sender's address, else
    one for the sender's domain, else the first."""
    owner = await account.id()
    answers = await account.call(
        ("Identity/get", {"accountId": owner, "ids": None}, "0"),
        using=WITH_SUBMISSION,
    )
    identities = list(jmap.result(answers, "0").get("list") or [])
    if not identities:
        raise ConflictError("the JMAP account has no identity to send as")
    wanted = sender.lower()
    domain = "*@" + wanted.rpartition("@")[2]
    for match in (wanted, domain):
        for identity in identities:
            if str(identity.get("email") or "").lower() == match:
                return str(identity["id"])
    return str(identities[0]["id"])


async def _forget(account: JmapAccount, email_id: str) -> None:
    """Remove a message that was stored to be sent and was not."""
    try:
        await account.one("Email/set", {"destroy": [email_id]})
    except MailboxServiceError:
        pass  # a stray draft is better than hiding why the send failed


def _submission_failure(answers: list[jmap.Invocation]) -> MailboxServiceError | None:
    """Why the server did not take the message, None when it did."""
    try:
        submitted = jmap.result(answers, "s")
    except MailboxServiceError as exc:
        return exc
    refused = (submitted.get("notCreated") or {}).get("s")
    if refused is not None:
        return jmap.set_error(refused, "message")
    if "s" not in (submitted.get("created") or {}):
        return ProviderError("the JMAP server did not say whether it sent the message")
    return None
