"""The entrance for peers over A2A, the only module that imports a2a-sdk,
Starlette and uvicorn.

One skill, ``classify``: a peer sends a message with a data part that
names ``account_id`` and ``message_id``, and gets a message with a data
part back, what :class:`Classified` or :class:`NotClassified` holds.
Every request carries the bearer token of the settings, the agent card
too. The protocol of A2A 1.0 and 0.3 on one endpoint. See
docs/mailbox-agents/concept/a2a.md.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.applications import Starlette
from starlette.responses import JSONResponse

from ..records import Classified, MessageRef, NotClassified
from ..serving.port import Port
from ..settings import PREFIX

__all__ = ["Card", "Classify", "Server", "app"]

# What answers a peer: the classifier of the runtime.
Classify = Callable[[MessageRef], Awaitable[Classified | NotClassified]]

_SCHEME = "bearer"
_JSON = "application/json"


@dataclass(frozen=True, slots=True)
class Card:
    """What the agent card says: who answers, in which version, and where
    a peer reaches it. Never a category of a list."""

    name: str
    version: str
    url: str


class _Asked(BaseModel):
    """The data part a peer sends."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str = Field(min_length=1, max_length=256)
    message_id: str = Field(min_length=1, max_length=1024)

    @field_validator("account_id", "message_id")
    @classmethod
    def _one_part(cls, value: str) -> str:
        """An id is one part of a path: never ``.`` or ``..``, which the
        HTTP client would drop from the path it asks the service for, and
        no slash, backslash or control character."""
        if value in (".", ".."):
            raise ValueError("an id is not a part of a path")
        if any(c in "/\\\x7f" or ord(c) < 32 for c in value):
            raise ValueError("an id holds no slash and no control character")
        return value


class _Executor(AgentExecutor):
    def __init__(self, classify: Classify) -> None:
        self._classify = classify

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        answer = await self._answer(context)
        await event_queue.enqueue_event(
            new_data_message(answer, context_id=context.context_id)
        )

    async def _answer(self, context: RequestContext) -> dict[str, Any]:
        parts = get_data_parts(context.message.parts) if context.message else []
        if len(parts) != 1:
            return {"error": "one data part with account_id and message_id"}
        try:
            asked = _Asked.model_validate(parts[0])
        except ValidationError:
            return {"error": "one data part with account_id and message_id"}
        ref = MessageRef(account_id=asked.account_id, message_id=asked.message_id)
        found = await self._classify(ref)
        return found.model_dump(mode="json")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # An answer comes at once: there is nothing running to cancel.
        return None


class _Bearer:
    """Lets a request through only with the token, compared in constant
    time. The lifespan of the server passes."""

    def __init__(self, inner: Any, token: str) -> None:
        self._inner = inner
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            given = dict(scope.get("headers") or ()).get(b"authorization", b"")
            if not hmac.compare_digest(given, self._expected):
                refused = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await refused(scope, receive, send)
                return
        await self._inner(scope, receive, send)


def _card(card: Card) -> AgentCard:
    return AgentCard(
        name=card.name,
        description=(
            "Classifies one message of a mailbox by its id, the way the "
            "agent does, and acts on nothing."
        ),
        version=card.version,
        supported_interfaces=[
            AgentInterface(
                url=card.url, protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        security_schemes={
            _SCHEME: SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer")
            )
        },
        security_requirements=[SecurityRequirement(schemes={_SCHEME: StringList()})],
        default_input_modes=[_JSON],
        default_output_modes=[_JSON],
        skills=[
            AgentSkill(
                id="classify",
                name="classify",
                description=(
                    "A data part with account_id and message_id in, the "
                    "categories of the message and whether a quote backs "
                    "each out."
                ),
                tags=["mail", "classification"],
                input_modes=[_JSON],
                output_modes=[_JSON],
            )
        ],
    )


def app(classify: Classify, card: Card, token: str) -> Any:
    """The ASGI application: the agent card and the JSON-RPC endpoint at
    the root, behind the token."""
    found = _card(card)
    handler = DefaultRequestHandlerV2(
        agent_executor=_Executor(classify),
        task_store=InMemoryTaskStore(),
        agent_card=found,
    )
    routes = create_agent_card_routes(found) + create_jsonrpc_routes(
        handler, "/", enable_v0_3_compat=True
    )
    return _Bearer(Starlette(routes=routes), token)


class Server:
    """The application on a port, run in the event loop of the worker."""

    def __init__(self, application: Any, host: str, port: int) -> None:
        # SIGINT and SIGTERM stay with the worker: it stops, and the
        # entrance with it.
        self._port = Port(
            application,
            host,
            port,
            f"the entrance for peers cannot be served on port {port}: "
            f"correct {PREFIX}A2A_PORT",
            own_signals=False,
        )

    @asynccontextmanager
    async def serving(self) -> AsyncIterator[None]:
        """Serve from when the port is open until the block ends. A port
        that cannot be opened is a ConfigError."""
        async with self._port.serving():
            yield
