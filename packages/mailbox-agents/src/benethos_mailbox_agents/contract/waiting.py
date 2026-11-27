"""The keywords a list of an agent waits for, as patterns: a keyword in
the form of :data:`KEYWORD_FORM`, or the start of one with ``*`` at its
end for every keyword it starts. Compared without case, as a service may
answer keywords in lower case."""

from __future__ import annotations

from collections.abc import Iterable

from ..settings import KEYWORD_FORM

__all__ = ["is_pattern", "waits_for"]


def is_pattern(pattern: str) -> bool:
    """Whether ``pattern`` is a keyword, or the start of one with ``*`` at
    its end."""
    return KEYWORD_FORM.fullmatch(pattern.removesuffix("*")) is not None


def waits_for(patterns: Iterable[str], keyword: str) -> bool:
    """Whether ``keyword`` is one of ``patterns``, case aside."""
    found = keyword.casefold()
    return any(
        found.startswith(p[:-1]) if p.endswith("*") else found == p for p in patterns
    )
