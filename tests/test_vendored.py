"""The JavaScript packages the UI ships against the lockfile that records them.

``assets/vendor/package-lock.json`` is read by the freshness report and by
nothing else. Nothing installs from it, so nothing keeps it true but this: a
version that moved in one place only would have the report watch a version the
UI does not ship.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .publish_helpers import ROOT

FOLDER = ROOT / "assets" / "vendor"
HTMX_NOTE = (
    ROOT
    / "packages/mailbox-service/src/benethos_mailbox_service/web/pages/static"
    / "vendor/htmx/README.md"
)
ICONS = ROOT / "assets" / "icons.py"


def _lock() -> dict[str, Any]:
    packages = json.loads((FOLDER / "package-lock.json").read_text("utf-8"))["packages"]
    return dict(packages)


def _named(pattern: str, text: str) -> str:
    found = re.search(pattern, text, re.M)
    assert found is not None, pattern
    return found.group(1)


def test_the_lockfile_records_what_the_ui_ships() -> None:
    """In dependencies, since the report hides what is only for development."""
    shipped = {
        "htmx.org": _named(r"^htmx (\d+\.\d+\.\d+),", HTMX_NOTE.read_text("utf-8")),
        "bootstrap-icons": _named(
            r'^VERSION = "(\d+\.\d+\.\d+)"$', ICONS.read_text("utf-8")
        ),
    }
    assert _lock()[""]["dependencies"] == shipped


def test_the_manifest_and_the_lockfile_agree() -> None:
    manifest = json.loads((FOLDER / "package.json").read_text("utf-8"))
    assert manifest["private"] is True
    assert manifest["dependencies"] == _lock()[""]["dependencies"]


def test_each_entry_is_locked_at_its_version_from_the_npm_registry() -> None:
    """The report's action names no finding for an entry from anywhere else."""
    lock = _lock()
    for name, version in lock[""]["dependencies"].items():
        entry = lock[f"node_modules/{name}"]
        assert entry["version"] == version
        assert entry["resolved"].startswith(f"https://registry.npmjs.org/{name}/-/")
