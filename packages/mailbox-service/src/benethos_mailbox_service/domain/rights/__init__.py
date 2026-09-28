"""Rights: who may do what (docs/PERMISSIONS.md).

The catalogue of rights and groups is ``permissions``, what one caller
may do is ``Access``.
"""

from __future__ import annotations

from . import permissions
from .access import Access, SendLimit
from .permissions import permission_of

__all__ = ["Access", "SendLimit", "permission_of", "permissions"]
