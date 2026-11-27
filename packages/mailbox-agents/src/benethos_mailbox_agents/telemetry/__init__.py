"""Spans of what an agent does with one message, over OpenTelemetry: one
per message, below it the decision and its parts and each action.
``spans`` is what the rest of the package sees, ``otlp`` the only module
that imports opentelemetry. It is imported on its own, by the command
line alone, so the runtime loads no SDK it does not use. See
docs/mailbox-agents/concept/operation.md."""

from __future__ import annotations

from .spans import NO_SPANS, Attribute, Span, Spans

__all__ = ["NO_SPANS", "Attribute", "Span", "Spans"]
