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
from .shapes import Identity

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
    answers = await account.call(
        _imported(session.account_id, blob, holder, draft=holder is drafts),
        (
            "EmailSubmission/set",
            _submission(session.account_id, identity, sender, recipients, holder, sent),
            "s",
        ),
        using=WITH_SUBMISSION,
    )
    email_id = _stored(answers)
    failed = _submission_failure(answers)
    if failed is not None:
        await _forget(account, email_id)
        raise failed
    # Sent: from here on nothing may fail, or a client would send again.
    return await _sent_copy(account, email_id, sent)


def _imported(owner: str, blob: str, holder: Folder, draft: bool) -> jmap.Invocation:
    """The ``Email/import`` of the message to send, as ``#m``, into the
    folder that holds it until it is sent."""
    keywords = {mappers.SEEN: True}
    if draft:
        keywords[mappers.DRAFT] = True
    email = {"blobId": blob, "mailboxIds": {holder.id: True}, "keywords": keywords}
    return ("Email/import", {"accountId": owner, "emails": {"m": email}}, "i")


def _stored(answers: list[jmap.Invocation]) -> str:
    """The id of the message the server stored to send."""
    imported = jmap.read(answers, "i", jmap.SetResult)
    refused = imported.not_created.get("m")
    if refused is not None:
        raise jmap.set_error(refused, "message")
    stored = imported.created.get("m")
    if stored is None:
        raise ProviderError("the JMAP server did not store the message to send")
    return stored.id


async def _sent_copy(
    account: JmapAccount, email_id: str, sent: Folder | None
) -> SentMessage:
    """The copy in the sent folder. A failure to read it is noted, never
    raised: the message is sent."""
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
    identities = jmap.read(answers, "0", jmap.Got[Identity]).items
    if not identities:
        raise ConflictError("the JMAP account has no identity to send as")
    wanted = sender.lower()
    domain = "*@" + wanted.rpartition("@")[2]
    for match in (wanted, domain):
        for identity in identities:
            if (identity.email or "").lower() == match:
                return identity.id
    return identities[0].id


async def _forget(account: JmapAccount, email_id: str) -> None:
    """Remove a message that was stored to be sent and was not."""
    try:
        await account.one("Email/set", {"destroy": [email_id]}, jmap.Anything)
    except MailboxServiceError:
        pass  # a stray draft is better than hiding why the send failed


def _submission_failure(answers: list[jmap.Invocation]) -> MailboxServiceError | None:
    """Why the server did not take the message, None when it did."""
    try:
        submitted = jmap.read(answers, "s", jmap.SetResult)
    except MailboxServiceError as exc:
        return exc
    refused = submitted.not_created.get("s")
    if refused is not None:
        return jmap.set_error(refused, "message")
    if "s" not in submitted.created:
        return ProviderError("the JMAP server did not say whether it sent the message")
    return None
