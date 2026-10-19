"""What the tests of the packages, of the publish workflow and of the
places a release is listed share: the packages, a package's project table
and dependencies, and a job of the publish workflow."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
PACKAGES = [
    ROOT / "packages" / "mailbox-service",
    ROOT / "packages" / "mailbox-client",
    ROOT / "packages" / "mailbox-mcp",
    ROOT / "packages" / "mailbox-common",
]


def project_of(package: Path) -> dict[str, Any]:
    """The table ``project`` of a package's ``pyproject.toml``."""
    data = tomllib.loads((package / "pyproject.toml").read_text("utf-8"))
    return dict(data["project"])


def module_of(package: Path) -> str:
    """The import name of a package."""
    return str(project_of(package)["name"]).replace("-", "_")


def needs_of(package: Path) -> list[str]:
    """The dependencies of a package as its pyproject.toml writes them."""
    needs = project_of(package)["dependencies"]
    assert isinstance(needs, list)
    return [str(need) for need in needs]


def workspace_needs(package: Path) -> set[str]:
    """The packages of the workspace that ``package`` depends on."""
    names = {str(project_of(p)["name"]) for p in PACKAGES}
    return {
        name
        for need in needs_of(package)
        if (name := re.split(r"[=<>!~\[; ]", need, maxsplit=1)[0]) in names
    }


def workflow_job(name: str) -> str:
    """The lines of one job of the publish workflow."""
    text = WORKFLOW.read_text("utf-8")
    found = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", text, re.M)
    assert found, name
    return found.group(1)
