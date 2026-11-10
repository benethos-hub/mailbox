"""What the tests of the repository share: its root, its workflows and
the organisation's workflows and actions they call."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
# Where the organisation's reusable workflows and actions live.
ORG = "benethos-hub/.github/"


def read(name: str) -> str:
    """The text of the workflow file ``name``, such as ``ci.yml``."""
    return (WORKFLOWS / name).read_text("utf-8")


def job_of(text: str, name: str) -> str:
    """The lines of one job of a workflow, below the line that names it,
    blank lines inside it included."""
    found = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", text, re.M)
    assert found, name
    return found.group(1)
