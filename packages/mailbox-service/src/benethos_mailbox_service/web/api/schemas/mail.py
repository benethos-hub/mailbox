"""What the mail routes take beyond the types of ``data.models``."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ....data.models import DraftMessage


class DraftReplacement(DraftMessage):
    """A draft as `create_draft` takes it, and which attachments of the
    stored draft to keep."""

    keep_attachments: list[str] = Field(
        default_factory=list,
        description=(
            "Ids of attachments of the stored draft that go into the new one, "
            "before those `attachments` brings. Any other stored attachment "
            "is gone afterwards."
        ),
    )


class LinkRequest(BaseModel):
    """How long a link to an attachment is to hold."""

    expires_in: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Seconds the link holds. Left out: as long as the service is set "
            "to, `MAILBOX_SERVICE_LINK_SECONDS`, 120 by default. More than "
            "that answers `400`."
        ),
    )


class AttachmentLink(BaseModel):
    """A link to an attachment: whoever holds the URL fetches the
    attachment once, without a token, until `expires_at`."""

    url: str = Field(
        description=(
            "Fetched with GET and no Authorization. Shown once: the service "
            "keeps only a digest of its secret."
        )
    )
    expires_at: datetime
    content_type: str
    size: int
    filename: str | None = None
