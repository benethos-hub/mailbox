"""The list of forwarding: what it refuses, and which rule holds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.forwarding.rules import Rules, load_rules
from benethos_mailbox_agents.errors import ConfigError

INVOICES = {"keywords": ["agent-invoice"], "to": ["Books@Example.org"]}


def _write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "forwarding.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# Every text of the owner the lists below hold: none may stand in a message.
OWN_TEXT = ("example.org", "secret", "agent-secret")


@pytest.mark.parametrize(
    ("data", "says"),
    [
        ({"rules": []}, "rules: Tuple should have at least 1 item"),
        ({"rules": [{"keywords": ["agent-secret"]}]}, "rules.0.to: Field required"),
        ({"rules": [{"keywords": ["agent-secret"], "to": []}]}, "rules.0.to"),
        (
            {"rules": [{"keywords": ["agent-secret"], "to": ["a@example.org"] * 6}]},
            "rules.0.to",
        ),
        (
            {"rules": [{"keywords": ["agent-secret"], "to": ["secret.example.org"]}]},
            "an address of to is one @",
        ),
        (
            {"rules": [{"keywords": ["agent-secret"], "to": ["se cret@example.org"]}]},
            "an address of to is one @",
        ),
        (
            {"rules": [{"keywords": ["agent-secret"], "to": ["a@b@example.org"]}]},
            "an address of to is one @",
        ),
        (
            {
                "rules": [
                    {"keywords": ["agent-secret"], "to": ["s" * 250 + "@example.org"]}
                ]
            },
            "at most 254 characters",
        ),
        (
            {"rules": [{"keywords": ["Agent-Secret"], "to": ["a@example.org"]}]},
            "lower case letters, digits and dashes",
        ),
        (
            {"rules": [{**INVOICES, "forward_as": "secret"}]},
            "rules.0.forward_as",
        ),
        (
            {"rules": [{**INVOICES, "sender_check": "secret"}]},
            "rules.0.sender_check",
        ),
        ({"rules": [{**INVOICES, "send": True}]}, "rules.0.send"),
        ({"rules": [INVOICES] * 51}, "rules: Tuple should have at most 50 items"),
    ],
)
def test_a_wrong_list_is_refused_by_the_place_of_its_rule(
    tmp_path: Path, data: Any, says: str
) -> None:
    with pytest.raises(
        ConfigError, match="the forwarding list forwarding.json"
    ) as raised:
        load_rules(_write(tmp_path, data))

    message = str(raised.value)
    assert says in message
    assert not any(text in message for text in OWN_TEXT)


def test_a_rule_as_read_with_its_defaults(tmp_path: Path) -> None:
    found = load_rules(_write(tmp_path, {"rules": [INVOICES]}))

    [rule] = found.rules
    assert rule.to == ("books@example.org",)
    assert (rule.forward_as, rule.sender_check) == ("inline", "required")
    assert found.recipients() == {"books@example.org"}


def test_the_first_rule_that_fits_holds() -> None:
    found = Rules.model_validate(
        {
            "rules": [
                {
                    "keywords": ["agent-invoice", "agent-partner-a"],
                    "to": ["a@example.org"],
                },
                INVOICES,
                {"keywords": ["agent-invoice"], "to": ["c@example.org"]},
            ]
        }
    )

    assert found.first(("Agent-Invoice",)) == (2, found.rules[1])
    assert found.first(("agent-partner-a", "agent-invoice")) == (1, found.rules[0])
    assert found.first(("agent-notice",)) is None


def test_what_the_list_waits_for() -> None:
    plain = Rules.model_validate({"rules": [INVOICES]})
    named = Rules.model_validate(
        {"on": {"keywords": ["agent-categorized-*"]}, "rules": [INVOICES]}
    )

    assert plain.waits_for("agent-invoice")
    assert not plain.waits_for("agent-notice")
    assert named.waits_for("agent-categorized-bookkeeping")
    assert not named.waits_for("agent-invoice")
