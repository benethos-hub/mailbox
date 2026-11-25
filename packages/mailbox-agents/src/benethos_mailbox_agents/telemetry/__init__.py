"""Spans of what an agent does with one message, over OpenTelemetry: one
per message, below it the decision and its parts and each action.
``spans`` is what the rest of the package sees, ``otlp`` the only module
that imports opentelemetry. See docs/mailbox-agents/concept/operation.md."""

from __future__ import annotations

from .otlp import OtlpSpans, open_spans
from .spans import NO_SPANS, Attribute, Span, Spans

__all__ = ["NO_SPANS", "Attribute", "OtlpSpans", "Span", "Spans", "open_spans"]
