"""The JMAP provider, registry key ``jmap``."""

from __future__ import annotations

from .connect import settings_from
from .provider import JmapProvider

__all__ = ["JmapProvider", "settings_from"]
