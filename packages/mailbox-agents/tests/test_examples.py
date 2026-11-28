"""Every example list in the repository parses with the loader it is for,
the copies the production setup carries are the same as their sources,
and the production setup has a service for every agent."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from benethos_mailbox_agents.agents.categorization.lists import load_chain
from benethos_mailbox_agents.agents.filing.rules import load_rules
from benethos_mailbox_agents.agents.forwarding.rules import (
    load_rules as load_forwarding,
)
from benethos_mailbox_agents.agents.inquiries.patterns import load_patterns
from benethos_mailbox_agents.contract import discover

from .agents_helpers import ROOT

EXAMPLES = sorted(
    [
        *(ROOT / "config" / "benethos-mailbox-agents").rglob("*.example.json"),
        *(ROOT / "containers").glob("*/mailbox-agents/**/*.example.json"),
        ROOT / "containers" / "live" / "mailbox-agents" / "categorization.json",
    ]
)
LOADERS = {
    "inquiries": load_patterns,
    "categorization": load_chain,
    "filing": load_rules,
    "forwarding": load_forwarding,
}


@pytest.mark.parametrize(
    "path", EXAMPLES, ids=[p.relative_to(ROOT).as_posix() for p in EXAMPLES]
)
def test_an_example_parses(path: Path) -> None:
    loader = LOADERS[path.name.split(".")[0]]

    assert loader(path) is not None


def test_every_example_is_found() -> None:
    assert len(EXAMPLES) >= 5


PRODUCTION = sorted(
    (ROOT / "containers" / "production" / "mailbox-agents" / "agents").rglob(
        "*.example.json"
    )
)
CONFIG = ROOT / "config" / "benethos-mailbox-agents"


@pytest.mark.parametrize(
    "path", PRODUCTION, ids=[p.relative_to(ROOT).as_posix() for p in PRODUCTION]
)
def test_a_production_example_is_the_one_under_config(path: Path) -> None:
    """containers/production/mailbox-agents/agents/<name>/ carries a copy of the example
    of config/, byte for byte, so the two never come to differ."""
    assert path.read_bytes() == (CONFIG / path.name).read_bytes()


def test_every_production_example_is_found() -> None:
    assert len(PRODUCTION) >= 2


def test_the_production_setup_has_a_service_for_every_agent() -> None:
    """A new agent needs its service in the compose file of the production
    setup and its settings example beside it, or an operator cannot run it.
    The cockpit is the one service besides them."""
    setup = ROOT / "containers" / "production" / "mailbox-agents"
    compose = (setup / "compose.yaml").read_text(encoding="utf-8")
    services = compose.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    named = set(re.findall(r"^  ([a-z_]+):$", services, re.MULTILINE))

    assert named == {*discover(), "cockpit"}
    for name in named - {"cockpit"}:
        assert (setup / "agents" / name / ".env.example").is_file(), name
    assert (setup / "cockpit" / ".env.example").is_file()


AGENT_SETTINGS = ROOT / "containers" / "production" / "mailbox-agents" / "agents"
POSTGRES_BLOCK = "# The state in a database of its own on a PostgreSQL server"


def _postgres_block(agent: str) -> str:
    """The lines of ``agent``'s .env.example from its PostgreSQL block to
    its end, the name of the agent replaced."""
    text = (AGENT_SETTINGS / agent / ".env.example").read_text(encoding="utf-8")
    assert POSTGRES_BLOCK in text, agent
    return text[text.index(POSTGRES_BLOCK) :].replace(agent, "<agent>")


def test_the_postgresql_block_of_every_agent_is_the_same() -> None:
    """Each agent has a settings file of its own, and the block of a state
    on PostgreSQL in each differs by the name of the agent alone."""
    agents = sorted(path.name for path in AGENT_SETTINGS.iterdir() if path.is_dir())
    assert len(agents) >= 6
    blocks = {agent: _postgres_block(agent) for agent in agents}
    assert len(set(blocks.values())) == 1, blocks
