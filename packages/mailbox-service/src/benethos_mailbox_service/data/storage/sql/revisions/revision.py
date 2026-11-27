"""The base of every revision of the service: a ``Revision`` of the
storage of mailbox-common, whose first revision makes schema 26, the
last step of the old chain, and which raises the errors of the
service."""

from __future__ import annotations

from benethos_mailbox_common.storage import revision

from .....errors import STORAGE_ERRORS

# The schema the first revision makes, the last step of the old chain.
BASELINE = 26


class Revision(revision.Revision):
    """One step of the schema of the service, from the schema before
    ``version`` to it."""

    baseline = BASELINE
    errors = STORAGE_ERRORS
