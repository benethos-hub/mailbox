"""The rules of the documents that CLAUDE.md states: the names and the
first lines of the concept's parts, the overview that lists them, the
table of the agents, and the drawing of docs/mailbox-agents/ARCHITECTURE.md."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import get_args

import pytest

from benethos_mailbox_agents.contract import discover
from benethos_mailbox_agents.settings import Stage

from .agents_helpers import DOCS, PACKAGE_DIR, ROOT

CONCEPT = DOCS / "concept"
PARTS = sorted(CONCEPT.glob("*.md"))
# The one part named agent- that is no agent: the contract every agent
# keeps.
CONTRACT = "agent-contract.md"


def _overview() -> str:
    return (DOCS / "CONCEPT.md").read_text("utf-8")


@pytest.mark.parametrize("part", PARTS, ids=[p.name for p in PARTS])
def test_a_part_is_named_in_lowercase_and_leads_back(part: Path) -> None:
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md", part.name)
    lines = part.read_text("utf-8").splitlines()
    assert lines[0].startswith("# Concept: ")
    assert "Part of the [concept](../CONCEPT.md)." in lines[:4]


def test_the_overview_lists_every_part() -> None:
    listed = set(re.findall(r"\(concept/([a-z0-9-]+\.md)\)", _overview()))

    assert listed == {part.name for part in PARTS}


def test_a_document_directly_in_docs_is_named_in_capitals() -> None:
    for document in DOCS.glob("*.md"):
        assert document.stem.isupper(), document.name


def test_each_agent_part_is_an_agent_and_each_agent_has_one() -> None:
    agents = {
        part.stem.removeprefix("agent-").replace("-", "_")
        for part in PARTS
        if part.name.startswith("agent-") and part.name != CONTRACT
    }

    assert agents == set(discover())


def test_the_table_of_the_agents_is_what_discovery_finds() -> None:
    table = _overview().split("## The agents", 1)[1].split("\n## ", 1)[0]
    rows = {
        found.group(1): found.group(0)
        for found in re.finditer(r"^\| `(\w+)` \|.*$", table, re.MULTILINE)
    }

    assert set(rows) == set(discover())
    for name, cls in discover().items():
        version = re.search(r"version (\d+)", rows[name])
        prompt = re.search(r"prompt `(v\d+)`", rows[name])
        if version:
            assert version.group(1) == str(cls.version), name
        if prompt:
            assert prompt.group(1) == cls.prompt_version, name


def _markdown() -> list[str]:
    """The documents of the agents: their folder under docs/ and the
    Markdown of the package, the prompts among it."""
    found = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    mine = (
        DOCS.relative_to(ROOT).as_posix() + "/",
        PACKAGE_DIR.relative_to(ROOT).as_posix() + "/",
    )
    return [name for name in found.stdout.split() if name.startswith(mine)]


@pytest.mark.parametrize("name", _markdown())
def test_no_heading_stands_twice_in_a_document(name: str) -> None:
    """The changelog repeats Added, Changed and Fixed in each release, and
    is left out."""
    headings, fenced = [], False
    for line in (ROOT / name).read_text("utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#{1,6} ", line):
            headings.append(line)

    assert [h for h, n in Counter(headings).items() if n > 1] == []


def test_the_drawing_names_the_stages_as_the_effect() -> None:
    page = (DOCS / "ARCHITECTURE.md").read_text("utf-8")
    drawing = page.split("trigger          selection", 1)[1].split("```", 1)[0]
    header, rule, *lines = ("trigger          selection" + drawing).splitlines()
    column = header.index("effect")
    # The rows of the drawing end at its first empty line.
    rows = lines[: lines.index("")] if "" in lines else lines
    effects = [line[column:].strip() for line in rows if line[column:].strip()]

    assert set(rule) == {"-"}

    assert effects == list(get_args(Stage))
