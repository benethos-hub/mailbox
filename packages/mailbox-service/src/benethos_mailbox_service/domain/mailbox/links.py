"""Links to an attachment (CONCEPT 6.3): a secret that hands one
attachment to whoever holds it, once, for a short time, so that another
service fetches the file without a token of this one.

A link belongs to the API token that made it. When it is used, the
rights of that token are resolved anew, as if the token asked. The
secret is shown once and kept as its digest. Every refusal is the same
``NotFoundError``, a locked-out address too, and counts as a wrong
token of the address that tried. A mail server that fails is not the
fetcher's doing: it counts nothing, and a link it failed holds again.
Where the secret travels, the URL and its path, is the web layer's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from benethos_mailbox_common.values import secret

from ...common.clock import utc_now
from ...common.retention import PURGE_EVERY
from ...data.models import AttachmentContent
from ...data.storage import LinkRepository, StoredLink
from ...errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    ProviderAuthError,
    ProviderError,
)
from ..activity import SERVICE, ActivityLog, Actor, someone
from ..activity import mailbox as said
from ..auth import AuthService
from ..rights import Access
from .service import MailboxService

# 96 random bytes are 128 characters of URL-safe text: a link is a
# bearer credential in a URL, and nobody can guess one.
SECRET_BYTES = 96
SECRET_LENGTH = 128
# How long a link holds by default, MAILBOX_SERVICE_LINK_SECONDS.
LINK_SECONDS = 120
# The one answer to every link that does not hand out its attachment.
LINK_GONE = "no such link"


@dataclass(frozen=True, slots=True)
class SharedLink:
    """A new link: its secret, shown once, when it ends, and what it hands
    out."""

    secret: str
    expires_at: datetime
    content_type: str
    size: int
    filename: str | None


class AttachmentLinks:
    def __init__(
        self,
        store: LinkRepository,
        mailbox: MailboxService,
        auth: AuthService,
        *,
        seconds: int = LINK_SECONDS,
        clock: Callable[[], datetime] = utc_now,
        activity: ActivityLog | None = None,
    ) -> None:
        """``seconds`` is how long a link holds at most."""
        self._store = store
        self._mailbox = mailbox
        self._auth = auth
        self._seconds = seconds
        self._clock = clock
        self._activity = activity or ActivityLog(clock)
        self._purged_at: datetime | None = None

    @property
    def seconds(self) -> int:
        """How long a link holds at most."""
        return self._seconds

    async def share(
        self,
        access: Access,
        account_id: str,
        message_id: str,
        attachment_id: str,
        expires_in: int | None = None,
    ) -> SharedLink:
        """A link to the attachment for ``expires_in`` seconds, by default
        and at most those of the settings. Needs ``get_attachment`` and
        ``share_attachment``, and an API token, which the link belongs
        to."""
        seconds = self._seconds if expires_in is None else expires_in
        if not 1 <= seconds <= self._seconds:
            raise BadRequestError(
                f"expires_in is 1 to {self._seconds} seconds, as the service is set"
            )
        if access.credential_id is None:
            raise BadRequestError("a link is made with an API token")
        found = await self._mailbox.attachment_to_share(
            access, account_id, message_id, attachment_id
        )
        now = self._clock()
        if self._purged_at is None or now - self._purged_at >= PURGE_EVERY:
            self.purge()
        plain = secret.token(SECRET_BYTES)
        link = StoredLink(
            id=secret.new_id("lnk"),
            secret_hash=secret.digest(plain),
            account_id=account_id,
            message_id=message_id,
            attachment_id=attachment_id,
            token_id=access.credential_id,
            expires_at=now + timedelta(seconds=seconds),
        )
        with self._activity.atomic():
            self._store.add(link)
            self._activity.record(
                said.LinkShared(
                    by=Actor.of(access),
                    link_id=link.id,
                    account_id=account_id,
                    message_id=message_id,
                    attachment_id=attachment_id,
                    seconds=seconds,
                )
            )
        return SharedLink(
            plain, link.expires_at, found.content_type, found.size, found.filename
        )

    async def redeem(self, presented: str, source: str) -> AttachmentContent:
        """The attachment of the link whose secret ``presented`` is, used up.
        ``source`` is the client address that asks. Anything else is
        ``NotFoundError``, always the same."""
        if self._auth.lockouts.is_locked_out(source):
            raise NotFoundError(LINK_GONE)
        link = (
            self._store.find(secret.digest(presented))
            if len(presented) == SECRET_LENGTH
            else None
        )
        if link is None:
            raise self._refused(source)
        access, why = self._holder(link, source)
        if access is None:
            raise self._refused(source, link, why)

        claimed: list[bool] = []

        def claim() -> None:
            with self._activity.atomic():
                if not self._store.redeem(link.id, self._clock(), source):
                    raise ConflictError("it was used or ended just now")
                self._activity.record(
                    said.LinkUsed(
                        by=Actor.of(access),
                        link_id=link.id,
                        account_id=link.account_id,
                        message_id=link.message_id,
                        attachment_id=link.attachment_id,
                    )
                )
            claimed.append(True)

        try:
            return await self._mailbox.linked_attachment(
                access, link.account_id, link.message_id, link.attachment_id, claim
            )
        except (ProviderError, ProviderAuthError) as exc:
            if not claimed:
                raise self._refused(source, link, exc.message, counted=False) from None
            with self._activity.atomic():
                self._store.release(link.id)
                self._activity.record(
                    said.LinkReturned(
                        by=Actor.of(access), link_id=link.id, reason=exc.message
                    )
                )
            raise NotFoundError(LINK_GONE) from None
        except MailboxServiceError as exc:
            raise self._refused(source, link, exc.message) from None

    def _holder(self, link: StoredLink, source: str) -> tuple[Access | None, str]:
        """The rights the link is used with, or None and why not."""
        if link.redeemed_at is not None:
            return None, "it was used"
        if link.expires_at <= self._clock():
            return None, "it ended"
        access = self._auth.token_access(link.token_id, source)
        if access is None:
            return None, "its token or the token's user can no longer act"
        return access, ""

    def _refused(
        self,
        source: str,
        link: StoredLink | None = None,
        why: str = "",
        *,
        counted: bool = True,
    ) -> NotFoundError:
        """The answer to a link that does not hold, the failure counted for
        ``source`` unless the mail server failed. A secret that is no
        link's writes no line."""
        if counted:
            self._auth.lockouts.failed(source)
        if link is not None:
            self._activity.record(
                said.LinkRefused(by=someone(source), link_id=link.id, reason=why)
            )
        return NotFoundError(LINK_GONE)

    def purge(self) -> None:
        """Remove the links used or ended, and say how many."""
        now = self._clock()
        count = self._store.purge(now)
        self._purged_at = now
        if count:
            self._activity.record(said.LinksPurged(by=SERVICE, count=count, before=now))
