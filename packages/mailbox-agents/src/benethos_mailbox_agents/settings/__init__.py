"""Settings resolution, secrets from files.

Every setting carries the prefix ``MAILBOX_AGENTS_`` and comes from the
environment or from one ``.env`` file, read with ``FileSettings`` of
mailbox-common. A process runs one agent, so one environment describes
one agent. The service token and the gateway key may be given as a file
instead, named in the same setting with the suffix ``_FILE``. Where the
file is and where the state files go: ``folders``. See
docs/mailbox-agents/concept/configuration.md.
"""

from __future__ import annotations

from .database import server_of, shown_database
from .folders import DATA_DIR, DEFAULT_ENV_FILE, Folders, folders
from .model import (
    FORMER_STAGES,
    KEYWORD_FORM,
    PREFIX,
    Settings,
    Stage,
    load_settings,
)

__all__ = [
    "DATA_DIR",
    "DEFAULT_ENV_FILE",
    "FORMER_STAGES",
    "KEYWORD_FORM",
    "PREFIX",
    "Folders",
    "Settings",
    "Stage",
    "folders",
    "load_settings",
    "server_of",
    "shown_database",
]
