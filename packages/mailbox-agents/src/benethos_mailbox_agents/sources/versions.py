"""Which versions of the mailbox service the agents take: the check of
a version the service names, the versions taken in words, and a version
cut for a line of text. No client here: ``sources/mailbox.py`` asks the
service and checks its answer with these. See
docs/mailbox-agents/concept/mailbox-service.md."""

from __future__ import annotations

import re

from .. import __version__

__all__ = ["matches", "shown", "taken"]

# A release of the service: three numbers and at most a local part after
# a "+". A pre-release such as 0.10.0rc1 or 0.10.1.dev3 is none, also of a
# later patch: the agents take releases of the service only.
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\+[0-9A-Za-z.-]+)?")

# The major and minor version of the agents themselves, also of a
# pre-release of their own.
_OWN = re.compile(r"(\d+)\.(\d+)")


def _own(own: str | None) -> tuple[int, int]:
    """The major and minor version of ``own``, this package's by default."""
    found = _OWN.match(own if own is not None else __version__)
    if found is None:
        return (0, 0)
    return int(found.group(1)), int(found.group(2))


def matches(version: str, own: str | None = None) -> bool:
    """Whether the service of ``version`` fits the agents of ``own``, this
    package's version by default. The agents are released with the
    service under one version. While the major version is 0, a minor
    release may change what the service does, so the service has the
    agents' minor version. From 1.0 it has their major version and a
    minor version no older than theirs, which may call what that minor
    version added. A pre-release of the service fits none."""
    match = _VERSION.fullmatch(version)
    if match is None:
        return False
    major, minor = int(match.group(1)), int(match.group(2))
    own_major, own_minor = _own(own)
    if own_major == 0:
        return (major, minor) == (own_major, own_minor)
    return major == own_major and minor >= own_minor


def taken(own: str | None = None) -> str:
    """Which versions of the service the agents of ``own`` take, in words,
    for a person."""
    own_major, own_minor = _own(own)
    if own_major == 0:
        return f"{own_major}.{own_minor}"
    return f"{own_major} from {own_major}.{own_minor}"


def shown(version: str) -> str:
    """``version`` as the service names it, cut for a line of text: a
    service may answer anything there."""
    return version[:40]
