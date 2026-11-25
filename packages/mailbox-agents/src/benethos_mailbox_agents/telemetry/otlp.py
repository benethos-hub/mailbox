"""Spans over OTLP, the only module that imports opentelemetry.

With ``MAILBOX_AGENTS_OTLP_ENDPOINT`` set, each process exports its spans
over OTLP and HTTP to ``<endpoint>/v1/traces``, so any target that takes
OTLP works, a collector, Tempo or Langfuse (decided 2026-11-25). Headers
such as the key of Langfuse come from the file
``MAILBOX_AGENTS_OTLP_HEADERS_FILE``, one ``name=value`` per line, and are
never logged. Unset, no exporter is made. See
docs/mailbox-agents/concept/operation.md.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from benethos_mailbox_common.log import redact

from .. import __version__
from ..errors import ConfigError
from ..settings import PREFIX, Settings
from .spans import NO_SPANS, Attribute, Span, Spans

__all__ = ["OtlpSpans", "open_spans"]

# The name of the service the spans of every agent name.
SERVICE = "benethos-mailbox-agents"


class _Open:
    def __init__(self, span: trace.Span) -> None:
        self._span = span

    def set(self, key: str, value: Attribute) -> None:
        self._span.set_attribute(key, value)


class OtlpSpans(Spans):
    """Spans that an OpenTelemetry provider of their own exports."""

    def __init__(self, provider: TracerProvider) -> None:
        self._provider = provider
        self._tracer = provider.get_tracer(SERVICE, __version__)

    @contextmanager
    def span(self, name: str, **attributes: Attribute) -> Iterator[Span]:
        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            yield _Open(span)

    def close(self) -> None:
        self._provider.shutdown()


def _check_url(url: str, allow_http: bool) -> str:
    """The URL of the traces below ``url``: https anywhere, http to this
    machine, or anywhere when allowed, as the headers may hold a key."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        raise ConfigError(f"{PREFIX}OTLP_ENDPOINT must be an http or https URL")
    if parts.scheme == "http" and not (allow_http or _loopback(host)):
        raise ConfigError(
            f"{PREFIX}OTLP_ENDPOINT is http to another machine: use https, or "
            f"set {PREFIX}OTLP_ALLOW_HTTP for a collector on a network of its own"
        )
    return url.rstrip("/") + "/v1/traces"


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _headers(path: Path | None) -> dict[str, str]:
    """The headers of the file at ``path``, one ``name=value`` per line,
    each value noted as a secret. A line that is empty or starts with #
    is left out."""
    if path is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        raise ConfigError(
            f"{PREFIX}OTLP_HEADERS_FILE cannot be read ({type(exc).__name__})"
        ) from None
    found: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if not sep or not name.strip() or not value.strip():
            raise ConfigError(
                f"{PREFIX}OTLP_HEADERS_FILE: line {number} is not name=value"
            )
        redact.note(value.strip())
        found[name.strip()] = value.strip()
    return found


def _provider(agent: str, exporter: SpanExporter, *, batch: bool) -> TracerProvider:
    resource = Resource.create(
        {
            "service.name": SERVICE,
            "service.version": __version__,
            "mailbox_agents.agent": agent,
        }
    )
    provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    return provider


@contextmanager
def open_spans(
    settings: Settings, agent: str, *, exporter: SpanExporter | None = None
) -> Iterator[Spans]:
    """The spans of one agent's process: over OTLP when the settings name
    an endpoint, to ``exporter`` when one is given, as a test does, and
    nowhere else. Closed when the block ends, sending what is left."""
    if exporter is None and settings.otlp_endpoint is None:
        yield NO_SPANS
        return
    batch = exporter is None
    if exporter is None:
        exporter = OTLPSpanExporter(
            endpoint=_check_url(settings.otlp_endpoint or "", settings.otlp_allow_http),
            headers=_headers(settings.otlp_headers_file),
            certificate_file=str(settings.ca_file) if settings.ca_file else None,
        )
    spans = OtlpSpans(_provider(agent, exporter, batch=batch))
    try:
        yield spans
    finally:
        spans.close()
