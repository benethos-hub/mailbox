"""containers/live/mailbox-agents/clear-secrets.sh, which setup.sh runs
before it removes anything: it clears what the setup makes in secrets/
and stops when anything else lies there."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .agents_helpers import ROOT

SCRIPT = ROOT / "containers" / "live" / "mailbox-agents" / "clear-secrets.sh"
SETUP = SCRIPT.parent / "setup.sh"

MADE = [
    "agent.env",
    "service-token",
    "service-admin",
    "stalwart-admin",
    "master_key",
    "gateway.env",
    "gateway-db.env",
    "gold-invoices.jsonl",
    "gold-categorization.jsonl",
]


def secrets(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "secrets"
    (folder / "tls").mkdir(parents=True)
    (folder / "tls" / "ca.pem").write_text("ca", encoding="utf-8")
    (folder / "data" / "categorization").mkdir(parents=True)
    (folder / "anthropic_api_key").write_text("key", encoding="utf-8")
    for name in (*MADE, *names):
        target = folder / name
        if name.endswith("/"):
            target.mkdir()
        else:
            target.write_text("x", encoding="utf-8")
    return folder


def clear(folder: Path) -> subprocess.CompletedProcess[str]:
    sh = shutil.which("sh")
    assert sh is not None, "the live setup needs a POSIX shell"
    return subprocess.run(
        [sh, SCRIPT.as_posix(), folder.as_posix()],
        capture_output=True,
        text=True,
        check=False,
    )


def test_what_the_setup_makes_is_cleared_and_the_key_kept(tmp_path: Path) -> None:
    folder = secrets(tmp_path)

    done = clear(folder)

    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in folder.iterdir()) == ["anthropic_api_key"]


def test_anything_else_stops_it_and_nothing_is_removed(tmp_path: Path) -> None:
    folder = secrets(tmp_path, "shadow.env", "shadow-data/", ".hidden")
    before = sorted(p.name for p in folder.iterdir())

    done = clear(folder)

    assert done.returncode == 2
    assert "shadow.env" in done.stderr
    assert "shadow-data" in done.stderr
    assert ".hidden" in done.stderr
    assert "Nothing was removed" in done.stderr
    assert sorted(p.name for p in folder.iterdir()) == before


def test_a_missing_folder_is_nothing_to_clear(tmp_path: Path) -> None:
    assert clear(tmp_path / "none").returncode == 0


def test_setup_clears_through_it_before_it_removes_anything() -> None:
    text = SETUP.read_text(encoding="utf-8")

    assert 'rm -rf "$secrets"' not in text
    assert text.index("clear-secrets.sh") < text.index("down --volumes")


def test_setup_builds_the_service_from_the_checkout_before_it_runs_it() -> None:
    """compose takes an image of the same name as it is: without the
    build an earlier one would run an older service."""
    text = SETUP.read_text(encoding="utf-8")

    assert text.index("build mailbox-service") < text.index("keys generate")
