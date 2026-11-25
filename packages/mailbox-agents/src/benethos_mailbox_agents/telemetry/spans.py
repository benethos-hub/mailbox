"""The spans of the agents as the rest of the package sees them, without
OpenTelemetry: :class:`Spans` opens a span, and is off unless
``telemetry/otlp.py`` gives one that exports.

A span names ids, states, counts, codes and names fixed in code or chosen
as identifiers of a list, such as the name of a dimension. Never a
subject, a sender, a text, a quote, the name of a category, a keyword or a
folder of a list: those are the owner's own text and often name a person
(decided 2026-11-25). See docs/mailbox-agents/concept/operation.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

__all__ = ["NO_SPANS", "Attribute", "Span", "Spans"]

# The value of an attribute of a span.
Attribute = str | bool | int | float


class Span(Protocol):
    """An open span: an attribute may be set on it while it is open."""

    def set(self, key: str, value: Attribute) -> None:
        """Set ``key`` to ``value``."""


class _Off:
    def set(self, key: str, value: Attribute) -> None:
        return None


class Spans:
    """Spans that go nowhere: the base, and the spans of a process without
    an OTLP endpoint."""

    @contextmanager
    def span(self, name: str, **attributes: Attribute) -> Iterator[Span]:
        """A span called ``name`` with ``attributes``, a child of the one
        open around it, closed when the block ends."""
        yield _Off()

    def close(self) -> None:
        """Send what is left and stop."""
        return None


NO_SPANS = Spans()
