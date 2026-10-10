"""The settings of a program, read from the environment and a settings
file. A group with a library, pydantic-settings. Callers import the
modules from here, ``from benethos_mailbox_common.settings import files``."""

from __future__ import annotations

from . import files

__all__ = ["files"]
