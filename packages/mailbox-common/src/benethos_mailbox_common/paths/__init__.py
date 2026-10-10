"""Where a program finds its settings and its data. The one group with a
library, platformdirs. Callers import the modules from here,
``from benethos_mailbox_common.paths import folders``."""

from __future__ import annotations

from . import folders

__all__ = ["folders"]
