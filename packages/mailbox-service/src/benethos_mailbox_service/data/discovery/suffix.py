"""Where a domain ends. The only module that imports ``publicsuffixlist``.

Uses the copy of the Public Suffix List that ships with the package, no
download at runtime (CONCEPT 5.8). A live list would be read here and
nowhere else.
"""

from __future__ import annotations

from functools import cache

from publicsuffixlist import PublicSuffixList

from ...common.hosts import ascii_host


@cache
def _list() -> PublicSuffixList:
    return PublicSuffixList()


def registrable_domain(host: str) -> str | None:
    """The part of a host name that can be registered: ``mx.hoster.co.uk``
    gives ``hoster.co.uk``. None for a public suffix such as ``co.uk``."""
    result = _list().privatesuffix(ascii_host(host) or host)
    return str(result) if result else None
