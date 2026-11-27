"""The base of every revision of the state file: a ``Revision`` of the
storage of mailbox-common, whose first revision makes schema 5, the last
step of the old ones, and which raises the errors of the state file."""

from __future__ import annotations

from benethos_mailbox_common.storage import revision

from ...errors import STATE_ERRORS

# The schema the first revision makes, the last step of the old ones.
BASELINE = 5


class Revision(revision.Revision):
    """One step of the schema of the state file, from the schema before
    ``version`` to it."""

    baseline = BASELINE
    errors = STATE_ERRORS
