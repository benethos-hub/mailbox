"""What the tests of the packages and of the places a release is listed
share: a package's project table and a job of the publish workflow."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"


def project_of(package: Path) -> dict[str, Any]:
    """The table ``project`` of a package's ``pyproject.toml``."""
    data = tomllib.loads((package / "pyproject.toml").read_text("utf-8"))
    return dict(data["project"])


def workflow_job(name: str) -> str:
    """The lines of one job of the publish workflow."""
    text = WORKFLOW.read_text("utf-8")
    found = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", text, re.M)
    assert found, name
    return found.group(1)
