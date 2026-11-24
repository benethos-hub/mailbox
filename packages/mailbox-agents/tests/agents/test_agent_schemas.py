"""The rules every schema a model answers in keeps, for each agent that asks
a model: found by discovery, so a new agent gets the checks too."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import json
import re
from typing import Any

import pytest
from pydantic import BaseModel

from benethos_mailbox_agents.contract import Limits, discover
from benethos_mailbox_agents.llm import evidence
from benethos_mailbox_agents.llm.gateway import strict_schema
from benethos_mailbox_agents.records import (
    Address,
    Attachment,
    MailMessage,
    MessageRef,
)
from benethos_mailbox_agents.runtime.model import _texts
from benethos_mailbox_agents.runtime.readiness import uses_model

# The Claude API compiles a schema of structured output with at most this
# many parameters whose type is a union, nullable ones among them, and
# refuses the request otherwise.
UNION_PARAMETERS = 16

# An answer each agent's model could give, but with a value longer than
# the 300 characters a quote or value may hold (``Limits.answer_text``).
LONG = "x" * 301


def _schema_modules() -> dict[str, Any]:
    """The module ``schema`` of each agent that has one, by agent name."""
    found = {}
    for name in discover():
        module = f"benethos_mailbox_agents.agents.{name}.schema"
        if importlib.util.find_spec(module) is not None:
            found[name] = importlib.import_module(module)
    return found


def _models() -> list[tuple[str, type[BaseModel]]]:
    """Every pydantic model an agent's schema module defines."""
    return [
        (f"{name}.{cls.__name__}", cls)
        for name, module in _schema_modules().items()
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, BaseModel) and cls.__module__ == module.__name__
    ]


MODELS = _models()


def _too_long(name: str) -> tuple[type[BaseModel], dict[str, Any]]:
    """The answer model of agent ``name`` and an answer to it with one
    value too long."""
    schema = _schema_modules()[name]
    if name == "invoices":
        return schema.Answer, {"label": "invoice", "near_miss": "none", "quote": LONG}
    if name == "awaiting_reply":
        return schema.Answer, {"expects_reply": True, "quote": LONG}
    if name == "inquiries":
        fields: dict[str, Any] = dict.fromkeys(schema.FIELDS)
        fields["role"] = {"value": LONG, "quote": "Python"}
        return schema.Inquiry, {"label": "inquiry", "quote": "Projektanfrage", **fields}
    if name == "sorting":
        return schema.answer_for(("A",)), {"group": "A", "quote": LONG}
    raise AssertionError(f"give {name} an answer here that copies the mail")


ASKING = sorted(name for name, cls in discover().items() if uses_model(cls))


def _unions(node: Any, defs: dict[str, Any]) -> int:
    """How many properties of ``node``, at any depth, are a union. A
    definition counts at each place it is used, as the API unfolds it."""
    if isinstance(node, list):
        return sum(_unions(item, defs) for item in node)
    if not isinstance(node, dict):
        return 0
    if "$ref" in node:
        return _unions(defs[node["$ref"].rpartition("/")[2]], defs)
    found = sum(
        1
        for value in node.get("properties", {}).values()
        if "anyOf" in value or isinstance(value.get("type"), list)
    )
    return found + sum(
        _unions(value, defs) for key, value in node.items() if key != "$defs"
    )


def test_every_agent_that_asks_a_model_has_a_schema() -> None:
    assert ASKING
    assert set(ASKING) <= set(_schema_modules())


@pytest.mark.parametrize(("name", "schema"), MODELS, ids=[n for n, _ in MODELS])
def test_each_schema_fits_the_claude_api(name: str, schema: type[BaseModel]) -> None:
    found = strict_schema(schema)
    assert _unions(found, found.get("$defs", {})) <= UNION_PARAMETERS


SAMPLE = MailMessage(
    ref=MessageRef(account_id="acc1", message_id="m1"),
    subject="Angebot fuer das Projekt",
    sender=Address(email="office@client.example", name="Office"),
    to=(Address(email="partner@partner.example"),),
    cc=(Address(email="office@client.example"),),
    text="Hello,\nplease find the offer attached.\n",
    attachments=(
        Attachment(filename="offer.pdf", content_type="application/pdf", size=1),
    ),
)


@pytest.mark.parametrize("name", ASKING)
def test_each_word_of_the_frame_render_writes_is_known_to_the_evidence_check(
    name: str,
) -> None:
    header = _schema_modules()[name].render(SAMPLE).split("\n\n", 1)[0]
    words = [re.match(r"(\w+):", line) for line in header.splitlines()]

    assert all(words)
    for word in words:
        assert word is not None
        assert evidence._FRAME.match(word.group(0)), word.group(1)


def test_a_quote_with_the_word_of_its_frame_is_found() -> None:
    to = "partner@partner.example, office@client.example"

    assert evidence.contains(to, f"To: {to}")
    assert evidence.contains("Angebot fuer das Projekt", "Subject: Angebot fuer das")


@pytest.mark.parametrize("name", ASKING)
def test_an_answer_that_copies_the_mail_goes_past_the_runtime_limit(
    name: str,
) -> None:
    """The schema reads it, the runtime refuses it (``Calls.ask``)."""
    schema, answer = _too_long(name)

    value = schema.model_validate(answer)

    assert max(map(len, _texts(value.model_dump()))) > Limits().answer_text


# The schema each agent sends to the model, as a digest of its canonical
# JSON. A change here is a change of what the model reads: a new prompt
# version, never a refactoring.
SENT = {
    "invoices": "7c4a889d07ed6a1b8a0b28cbe99f38616df041104ce16cdaddbf4a726acb2b9d",
    "inquiries": "e791dfc941671cf4253830c1053f6a4ce295b90ff2c9fe080137970e8ea7d7e8",
    "awaiting_reply": (
        "f2fe71ce95925f3725756ac7b2a75576d1d50a3e17b3bec638c75788b4019186"
    ),
    # Made for the groups to choose from: here for two of them.
    "sorting": "0e46e2bdc657fde262bc22e39881071e97c15c3980516656266b65839744b44d",
}


def _sent(name: str) -> type[BaseModel]:
    """The answer model of agent ``name``, for sorting the one for two
    groups."""
    schema = _schema_modules()[name]
    if name == "sorting":
        return schema.answer_for(("Project Alpha", "Project Beta"))
    return schema.Inquiry if name == "inquiries" else schema.Answer


@pytest.mark.parametrize("name", sorted(SENT))
def test_the_schema_sent_to_the_model_stays(name: str) -> None:
    found = strict_schema(_sent(name))
    text = json.dumps(found, sort_keys=True, separators=(",", ":"))
    assert _unions(found, found.get("$defs", {})) <= UNION_PARAMETERS
    assert hashlib.sha256(text.encode()).hexdigest() == SENT[name]
