"""Settings resolution, secrets from files.

Every setting carries the prefix ``MAILBOX_AGENTS_`` and comes from the
environment or from one ``.env`` file, read with ``FileSettings`` of
mailbox-common. A
process runs one agent, so one environment describes one agent. The
service token and the gateway key may be given as a file instead, named
in the same setting with the suffix ``_FILE``. See
docs/mailbox-agents/concept/configuration.md.
"""

from __future__ import annotations

from .model import (
    DEFAULT_ENV_FILE,
    KEYWORD_FORM,
    PREFIX,
    Settings,
    Stage,
    load_settings,
)

__all__ = [
    "DEFAULT_ENV_FILE",
    "KEYWORD_FORM",
    "PREFIX",
    "Settings",
    "Stage",
    "load_settings",
]
