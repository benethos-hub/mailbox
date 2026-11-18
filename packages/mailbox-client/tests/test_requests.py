"""Each request the client builds is one the API takes: the method and the
path of its operation in docs/openapi.json, its query parameters among
the operation's, and every field of its body, nested ones too, among the
fields of the request's schema. Each endpoint is called with every
parameter given, so each optional one is checked as well.

Every endpoint is an operation of the API, or names the one it sends: a
route the service drops fails here with the method left in the client.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_client import Grant, Reference, endpoints, message_body
from benethos_mailbox_client.calls import Call

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"
DOCUMENT = json.loads(CONTRACT.read_text("utf-8"))
METHODS = {"get", "put", "post", "patch", "delete"}
# Endpoints that send another operation: a shorthand of it.
SENDS = {"update_messages": "batch_messages", "trash_messages": "batch_messages"}
# Takes any method and path: it covers no operation of its own.
GENERIC = {"request"}
# A sample per annotation, by its first type.
SAMPLES: dict[str, Any] = {
    "str": "x1",
    "bool": True,
    "int": 1,
    "datetime": datetime(2026, 1, 2, tzinfo=UTC),
    "dict": {"k": "v"},
    "list[str]": ["x1"],
    "Sequence[Grant]": [Grant(accounts=["*"], allow=["mail.read"])],
}
# A body of a message, built as a caller builds it, with every field.
MESSAGE = message_body(
    to=[("a@x.org", "A")],
    cc=[("c@x.org", None)],
    bcc=[("b@x.org", None)],
    subject="Hi",
    text="Hello",
    html="<p>Hello</p>",
    reference=Reference("msg_1", "forward", forward_as="attachment", quote=False),
    reply_to=[("r@x.org", "R")],
    attachments=[],
    attachments_from=[],
)


def _operations() -> dict[str, tuple[str, str, dict[str, Any]]]:
    """Each operation by its id: its method, its path and itself."""
    return {
        operation["operationId"]: (method.upper(), route, operation)
        for route, item in DOCUMENT["paths"].items()
        for method, operation in item.items()
        if method in METHODS
    }


OPERATIONS = _operations()
ENDPOINTS = sorted(
    name
    for name in endpoints.__all__
    if str(inspect.signature(getattr(endpoints, name)).return_annotation).startswith(
        "Call["
    )
    and name not in GENERIC
)


def _sample(name: str, annotation: str) -> Any:
    if name == "message":
        return dict(MESSAGE)
    if name == "changes":
        # The changes of many messages, as update_messages builds them.
        built = _made("update_messages").json
        assert built is not None
        return built["changes"]
    first = annotation.split(" | ")[0]
    found = [value for key, value in SAMPLES.items() if first.startswith(key)]
    assert found, f"no sample for {name}: {annotation}"
    return found[0]


def _made(name: str) -> Call[Any]:
    """The endpoint's request, every parameter given."""
    function = getattr(endpoints, name)
    parameters = inspect.signature(function).parameters.values()
    made: Call[Any] = function(
        **{p.name: _sample(p.name, str(p.annotation)) for p in parameters}
    )
    return made


def _resolved(schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = DOCUMENT["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return schema


def _variants(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """The object schemas a value may match: through references and
    unions, without null."""
    schema = _resolved(schema)
    found: list[dict[str, Any]] = []
    for key in ("anyOf", "oneOf", "allOf"):
        for part in schema.get(key, []):
            found += _variants(part)
    if "properties" in schema or "items" in schema or not found:
        found.append(schema)
    return [s for s in found if s.get("type") != "null"]


def _unknown(value: Any, schema: dict[str, Any], where: str) -> list[str]:
    """The fields of ``value`` its schema does not name, nested ones too."""
    variants = _variants(schema)
    if isinstance(value, list):
        items = [v["items"] for v in variants if "items" in v]
        return [
            u for item in value for s in items[:1] for u in _unknown(item, s, where)
        ]
    if not isinstance(value, dict):
        return []
    known = [v for v in variants if "properties" in v]
    if not known or any(v.get("additionalProperties") for v in known):
        return []
    named = {p: s for v in known for p, s in v["properties"].items()}
    found = [f"{where}.{key}" for key in value if key not in named]
    for key, inner in value.items():
        if key in named:
            found += _unknown(inner, named[key], f"{where}.{key}")
    return found


def test_the_contract_and_the_client_are_read() -> None:
    assert len(OPERATIONS) > 50
    assert len(ENDPOINTS) > 50


@pytest.mark.parametrize("name", ENDPOINTS)
def test_every_endpoint_sends_an_operation_of_the_api(name: str) -> None:
    assert SENDS.get(name, name) in OPERATIONS, f"{name} is no operation of the API"


@pytest.mark.parametrize("name", ENDPOINTS)
def test_a_request_is_one_its_operation_takes(name: str) -> None:
    method, route, operation = OPERATIONS[SENDS.get(name, name)]
    made = _made(name)
    assert made.method == method
    pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(route))
    assert re.fullmatch(pattern, made.path), f"{made.path} is not {route}"
    query = {p["name"] for p in operation.get("parameters", []) if p["in"] == "query"}
    assert set(made.params) <= query, f"unknown parameters {set(made.params) - query}"
    if made.json is None:
        return
    content = operation.get("requestBody", {}).get("content", {})
    assert "application/json" in content, f"{name} sends a body {route} takes not"
    schema = content["application/json"]["schema"]
    assert _unknown(made.json, schema, "body") == []
