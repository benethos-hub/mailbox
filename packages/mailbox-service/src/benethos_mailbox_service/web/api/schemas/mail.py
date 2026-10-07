"""What the mail routes take beyond the types of ``data.models``."""

from __future__ import annotations

from pydantic import Field

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
