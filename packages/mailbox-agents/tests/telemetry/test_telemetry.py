"""The spans of the agents: one per message, the decision and its parts
below it, each action, and nothing of the mail or of the owner's list in
them: docs/mailbox-agents/concept/operation.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.telemetry import NO_SPANS, open_spans
from benethos_mailbox_agents.telemetry.otlp import _check_url, _headers

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import mail, settings, wired

QUOTE = "please find attached the invoice for November"
SUBJECT = "Your invoice of November"
SENDER = "billing@hosting.example"

CHAIN: dict[str, Any] = {
    "dimensions": [
        {
            "name": "partner",
            "categories": [
                {
                    "name": "Hosting",
                    "senders": ["*@hosting.example"],
                    "then": [
                        {"move": "Invoices/Hosting"},
                        {"keyword": "agent-hosting"},
                    ],
                }
            ],
        },
        {
            "name": "kind",
            "when": {"partner": ["Hosting"]},
            "categories": [
                {
                    "name": "Invoice",
                    "topic": "Invoices of a provider for a service the owner pays",
                    "by_topic": "act",
                    "then": [{"move_below": "Billed"}, {"keyword": "agent-invoice"}],
                }
            ],
        },
    ]
}

# What no attribute of a span may hold: the subject, the sender, the text
# and its quote, the names of the categories, the keywords and the folders
# of the list.
SECRET = [
    SUBJECT,
    SENDER,
    QUOTE,
    "Hosting",
    "Invoice",
    "agent-hosting",
    "agent-invoice",
    "Billed",
]


async def test_a_message_through_two_dimensions_and_its_actions_in_spans(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sorting.json"
    path.write_text(json.dumps(CHAIN), encoding="utf-8")
    agent = Sorting(settings(stage="full", sorting_file=path))
    exporter = InMemorySpanExporter()
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message(
                "m1", sender=SENDER, subject=SUBJECT, text=f"Hello,\n{QUOTE}.\n"
            ),
            change=None,
        )
        world.fake_gateway.answer({"group": "Invoice", "quote": QUOTE})
        with open_spans(agent.settings, agent.name, exporter=exporter) as spans:
            worker = Worker(
                agent=agent,
                store=world.store,
                mailbox=world.mailbox,
                gateway=world.gateway,
                now=world.clock,
                spans=spans,
            )
            world.store.enqueue(
                MessageRef(account_id=ACCOUNT, message_id="m1"), world.clock()
            )
            await worker.process_due()
        assert mail(world, "m1")["keywords"]

    found = exporter.get_finished_spans()
    names = [span.name for span in found]
    assert names.count("message") == 1
    assert names.count("decision") == 1
    assert names.count("dimension") == 2
    assert names.count("action") >= 3
    message = next(s for s in found if s.name == "message")
    assert dict(message.attributes or {})["state"] == "done"
    assert dict(message.attributes or {})["message_id"] == "m1"
    for span in found:
        if span.name != "message":
            assert span.parent is not None
    dimensions = [dict(s.attributes or {}) for s in found if s.name == "dimension"]
    assert dimensions == [
        {
            "dimension": "partner",
            "recognizer": "group",
            "source": "code",
            "category": "label-1",
            "quote_found": True,
        },
        {
            "dimension": "kind",
            "recognizer": "topic",
            "source": "model",
            "category": "label-1",
            "quote_found": True,
        },
    ]
    for span in found:
        for value in (span.attributes or {}).values():
            for secret in SECRET:
                assert secret.casefold() not in str(value).casefold(), (
                    span.name,
                    value,
                )


def test_without_an_endpoint_no_spans_go_out() -> None:
    with open_spans(settings(), "sorting") as spans:
        assert spans is NO_SPANS
        with spans.span("message", message_id="m1") as span:
            span.set("state", "done")


@pytest.mark.parametrize(
    ("url", "allow", "says"),
    [
        ("https://otel.example/api/public/otel", False, None),
        ("http://127.0.0.1:4318/", False, None),
        ("http://collector:4318", True, None),
        ("http://collector:4318", False, "http to another machine"),
        ("ftp://collector", False, "an http or https URL"),
    ],
)
def test_the_endpoint_is_https_or_http_to_this_machine(
    url: str, allow: bool, says: str | None
) -> None:
    if says is None:
        assert _check_url(url, allow).endswith("/v1/traces")
        assert "//v1" not in _check_url(url, allow)
        return
    with pytest.raises(ConfigError, match=says):
        _check_url(url, allow)


def test_the_headers_come_from_their_file_and_a_wrong_line_names_its_number(
    tmp_path: Path,
) -> None:
    good = tmp_path / "headers"
    good.write_text("# Langfuse\nAuthorization=Basic c2VjcmV0\n\n", encoding="utf-8")
    wrong = tmp_path / "wrong"
    wrong.write_text("Authorization Basic c2VjcmV0\n", encoding="utf-8")

    assert _headers(good) == {"Authorization": "Basic c2VjcmV0"}
    with pytest.raises(ConfigError, match="line 1 is not name=value") as raised:
        _headers(wrong)
    assert "c2VjcmV0" not in raised.value.message
