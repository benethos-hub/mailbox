"""The MCP package reaches mail through the REST API only.

It must neither depend on nor import the service package. The dependency
list is what enforces this for an installed wheel, and this test is what
keeps a workspace checkout, where both are importable, from hiding a slip.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SERVICE = "benethos_mailbox_service"


def test_no_dependency_on_the_service() -> None:
    project = tomllib.loads((PACKAGE / "pyproject.toml").read_text("utf-8"))
    names = [
        d.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
        for d in project["project"]["dependencies"]
    ]
    assert "benethos-mailbox-service" not in names


def test_no_import_of_the_service() -> None:
    offenders = []
    for path in (PACKAGE / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            offenders += [
                f"{path.name}: {m}"
                for m in modules
                if m == SERVICE or m.startswith(SERVICE + ".")
            ]
    assert offenders == []
