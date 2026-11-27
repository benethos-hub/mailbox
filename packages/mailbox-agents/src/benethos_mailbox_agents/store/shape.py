"""What the state file is, as the storage of mailbox-common is handed it:
its tables, its revisions from schema 5 on, the old steps of its file
before them, and the errors it raises."""

from __future__ import annotations

from benethos_mailbox_common.storage import shape

from ..errors import STATE_ERRORS
from .file import OLD_STEPS
from .revisions import BASELINE, SCHEMA_VERSION, VERSIONS
from .schema import METADATA

SHAPE = shape.Shape(
    program="benethos-mailbox-agents",
    noun="agent",
    metadata=METADATA,
    versions=VERSIONS,
    newest=SCHEMA_VERSION,
    baseline=BASELINE,
    errors=STATE_ERRORS,
    extra=(
        "storage postgres needs the extra postgres of the agents:"
        " pip install 'benethos-mailbox-agents[postgres]'"
    ),
    file_steps=OLD_STEPS,
)
