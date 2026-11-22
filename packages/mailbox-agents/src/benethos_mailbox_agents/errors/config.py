"""The error ``ConfigError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["ConfigError"]


class ConfigError(MailboxAgentError):
    """A setting or a configuration file is missing or wrong."""

    code = "config"
