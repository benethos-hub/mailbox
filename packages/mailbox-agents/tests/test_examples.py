"""Every example list in the repository parses with the loader it is for,
and the copies the production setup carries are the same as their sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_agents.agents.categorization.lists import load_chain
from benethos_mailbox_agents.agents.inquiries.patterns import load_patterns

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
