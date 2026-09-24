"""Where a domain ends. The only module that imports ``publicsuffixlist``.

Uses the copy of the Public Suffix List that ships with the package, no
download at runtime (CONCEPT 5.8). A live list would be read here and
nowhere else.
"""

from __future__ import annotations

from functools import cache

from publicsuffixlist import PublicSuffixList


@cache
def _list() -> PublicSuffixList:
    return PublicSuffixList()


def registrable_domain(host: str) -> str | None:
    """The part of a host name that can be registered: ``mx.hoster.co.uk``
    gives ``hoster.co.uk``. None for a public suffix such as ``co.uk``."""
    result = _list().privatesuffix(host.lower().rstrip("."))
    return str(result) if result else None


def is_public_suffix(host: str) -> bool:
    """True for ``de``, ``co.uk``, ``github.io`` and the like."""
    return bool(_list().is_public(host.lower().rstrip(".")))
