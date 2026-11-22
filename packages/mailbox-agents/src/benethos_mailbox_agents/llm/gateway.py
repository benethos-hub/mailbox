"""The model gateway: the only module that talks to it.

One call is one chat completion of two messages, the agent's system prompt
and the content of a mail, with the answer forced into a JSON schema by
``response_format`` and validated again with pydantic. No tools are sent,
no conversation is kept, no model SDK is used. No sampling setting is
sent either: some models refuse one, so the gateway sets it per model.
What the gateway reports as its model is returned with the answer, with
the tokens and the duration.
See docs/mailbox-agents/concept/model-gateway.md.
"""

from __future__ import annotations

import ipaddress
import json
import ssl
import time
from copy import deepcopy
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..errors import AnswerRefusedError, ConfigError, GatewayUnavailableError

__all__ = ["Gateway", "Reply", "strict_schema"]

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Reply(Generic[T]):
    """A validated answer and what the call cost. ``request`` and ``answer``
    are the bodies as sent and received, kept only where
    PROMPT_RETENTION_DAYS says so."""

    value: T
    model: str
    tokens_in: int
    tokens_out: int
    duration_ms: int
    request: dict[str, Any]
    answer: dict[str, Any]


def strict_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema of ``schema`` in the strict form structured output
    asks for: every object closed and every property required. A field
    that may be empty says so with ``null`` in its type, not by being left
    out."""
    found = deepcopy(schema.model_json_schema())

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(found)
    return found


class Gateway:
    """An OpenAI-compatible chat completions endpoint, for one agent's key
    and one model alias."""

    def __init__(
        self,
        base_url: str,
        key: str,
        model: str,
        *,
        timeout: float,
        allow_http: bool = False,
        verify: ssl.SSLContext | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """``verify`` replaces the roots of certifi, as an own CA needs.
        Without it, httpx verifies against its own roots."""
        _check_url(base_url, allow_http)
        self.model = model
        # verify is passed only when given: certificates are always checked.
        trust: dict[str, Any] = {}
        if verify is not None:
            trust["verify"] = verify
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
            trust_env=False,
            **trust,
        )

    async def __aenter__(self) -> Gateway:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    def request(self, *, system: str, content: str, schema: type[T]) -> dict[str, Any]:
        """The body of one call."""
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": strict_schema(schema),
                },
            },
        }

    async def ask(self, *, system: str, content: str, schema: type[T]) -> Reply[T]:
        """One call. Raises :class:`GatewayUnavailableError` when the
        gateway is away, :class:`ConfigError` when it refuses the key or
        the alias, and :class:`AnswerRefusedError` for a request it refuses
        or an answer that does not fit ``schema``."""
        body = self.request(system=system, content=content, schema=schema)
        started = time.monotonic()
        try:
            response = await self._http.post("/chat/completions", json=body)
        except httpx.TransportError as exc:
            raise GatewayUnavailableError(
                f"the gateway is away ({type(exc).__name__})"
            ) from None
        except httpx.HTTPError:
            # Such as a DecodingError: a body that says gzip and is none.
            raise AnswerRefusedError(
                "the gateway answered a body that cannot be read", reason="schema"
            ) from None
        duration_ms = int((time.monotonic() - started) * 1000)
        _check(response)
        try:
            answer = response.json()
        except (ValueError, RecursionError):
            # RecursionError: JSON nested too deep for the parser.
            raise AnswerRefusedError(
                "the gateway answered no JSON", reason="schema"
            ) from None
        value = _value(answer, schema)
        usage = answer.get("usage")
        # The name the gateway reports is stored: a lone surrogate in it
        # becomes "?".
        model = str(answer.get("model") or self.model)
        return Reply(
            value=value,
            model=model.encode("utf-8", "replace").decode("utf-8"),
            tokens_in=_tokens(usage, "prompt_tokens"),
            tokens_out=_tokens(usage, "completion_tokens"),
            duration_ms=duration_ms,
            request=body,
            answer=answer,
        )


#: The largest whole number SQLite stores.
MAX_TOKENS = 2**63 - 1


def _tokens(usage: object, name: str) -> int:
    """A token count of the answer's usage, 0 where it is missing, no whole
    number or below 0, and at most what SQLite stores: the call is made and
    paid, and a count the gateway garbled must not end the process before
    the step is stored."""
    if not isinstance(usage, dict):
        return 0
    try:
        return min(max(0, int(usage.get(name) or 0)), MAX_TOKENS)
    except (TypeError, ValueError, OverflowError):
        return 0


def _check(response: httpx.Response) -> None:
    status = response.status_code
    if 300 <= status < 400:
        # Redirects are not followed: the URL is the one to correct, such
        # as http where the gateway answers https.
        raise ConfigError(
            f"the gateway answered a redirect ({status}): check "
            "MAILBOX_AGENTS_GATEWAY_URL"
        )
    if status < 400:
        return
    if status >= 500 or status in (408, 429):
        raise GatewayUnavailableError(f"the gateway answered {status}")
    if status in (401, 403, 404):
        raise ConfigError(f"the gateway refused the key or the model alias ({status})")
    raise AnswerRefusedError(
        f"the gateway refused the request ({status})", reason="request"
    )


def _check_url(url: str, allow_http: bool) -> None:
    """https anywhere, http to this machine, or anywhere when allowed: the
    key and the mail would otherwise travel unencrypted."""
    try:
        parts = httpx.URL(url)
    except httpx.InvalidURL:
        raise ConfigError("MAILBOX_AGENTS_GATEWAY_URL is not a URL") from None
    if parts.scheme == "https" and parts.host:
        return
    if parts.scheme != "http" or not parts.host:
        raise ConfigError("MAILBOX_AGENTS_GATEWAY_URL must be an http or https URL")
    if allow_http or _loopback(parts.host):
        return
    raise ConfigError(
        f"MAILBOX_AGENTS_GATEWAY_URL is http to {parts.host}, so the key and the "
        "mail would travel unencrypted. Use https, or set "
        "MAILBOX_AGENTS_GATEWAY_ALLOW_HTTP=true for a network you trust, such as "
        "between containers."
    )


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _value(answer: Any, schema: type[T]) -> T:
    """The content of the first choice, validated against ``schema``.

    The JSON escape of a lone surrogate passes ``json.loads`` and the
    schema, but cannot be stored as UTF-8: such an answer is refused, so it
    is stored, counted and tried again like any other."""
    try:
        content = answer["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        json.dumps(parsed, ensure_ascii=False).encode("utf-8")
        return schema.model_validate(parsed)
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        RecursionError,
        ValidationError,
    ):
        raise AnswerRefusedError(
            "the answer does not fit the schema", reason="schema"
        ) from None
