"""The pre-commit hook, run in a repository of its own in a temporary
folder. It is held to the same lines of credentials and addresses as
the rules of ``content_helpers.py``, which check every tracked file."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from .content_helpers import (
    ADDRESSES,
    ALLOW,
    CREDENTIALS,
    EXAMPLE_ADDRESSES,
    REFERENCES,
)
from .repository_helpers import ROOT

HOOK = ROOT / ".githooks" / "pre-commit"
GIT = shutil.which("git")


def _shell() -> str | None:
    """The shell git runs a hook with. Git for Windows brings its own,
    which is not on the path of every terminal."""
    found = shutil.which("sh")
    if found is None and GIT is not None:
        home = Path(GIT).resolve().parent.parent
        for place in ("bin/sh.exe", "usr/bin/sh.exe"):
            if (home / place).is_file():
                return str(home / place)
    return found


SH = _shell()

pytestmark = pytest.mark.skipif(
    SH is None or GIT is None, reason="the hook needs sh and git"
)


def _git(repo: Path, *args: str) -> None:
    assert GIT is not None
    subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True)


def _hook(repo: Path) -> subprocess.CompletedProcess[str]:
    assert SH is not None
    return subprocess.run(
        [SH, HOOK.as_posix()],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def _stage(repo: Path, name: str, content: str = "x\n") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    _git(repo, "add", "-f", name)


def test_the_hook_is_executable_in_the_repository() -> None:
    assert GIT is not None
    listed = subprocess.run(
        [GIT, "ls-files", "-s", ".githooks/pre-commit"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert listed.startswith("100755 "), listed


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        "live/.env",
        "config/benethos-mailbox-service/.env",
        "config/benethos-mailbox-service/master.key",
        "config/benethos-mailbox-service/google_client_secret",
        ".env.local",
        "data/benethos-mailbox-service/mailbox.db",
        "data/benethos-mailbox-service/backups/2026.bak",
        "somewhere/backups/copy.bak",
        "state.db-wal",
        "somewhere/cache.sqlite",
        "containers/production/mailbox-service/secrets/master.key",
        "containers/test-mail-server/secrets/ca.crt",
        "containers/production/mailbox-service/service.env",
        "containers/production/mailbox-service/compose.override.yaml",
        "containers/production/mailbox-service/caddy.d/mcp.caddy",
        "account.token.json",
        "somewhere/server.pem",
        "config/x/schlüssel.key",
        "config/benethos-mailbox-agents/categorization.json",
        "packages/mailbox-agents/tests/data/other.pem",
        "sicherung/März.db",
        "containers/production/mailbox-agents/agents/categorization/categorization.json",
        "containers/production/mailbox-agents/agents/inquiries/inquiries.json",
    ],
)
def test_refuses_files_that_never_belong(repo: Path, name: str) -> None:
    _stage(repo, name)

    answer = _hook(repo)

    assert answer.returncode == 1
    assert name in answer.stderr


@pytest.mark.parametrize(
    "name",
    [
        "config/benethos-mailbox-service/.env.example",
        "config/benethos-mailbox-agents/categorization.example.json",
        "packages/mailbox-agents/tests/data/test-ca.pem",
        "live/.env.example",
        "data/benethos-mailbox-service/.gitkeep",
        "containers/production/mailbox-service/service.env.example",
        "containers/production/mailbox-service/compose.override.yaml.example",
        "containers/production/mailbox-service/caddy.d/mcp.caddy.example",
        "containers/production/mailbox-service/compose.yaml",
        "packages/mailbox-service/src/benethos_mailbox_service/data/secrets/keys.py",
        "packages/mailbox-service/src/benethos_mailbox_service/data/models/x.py",
        "containers/production/mailbox-agents/agents/categorization/categorization.example.json",
        "containers/production/mailbox-agents/agents/invoices/.env.example",
    ],
)
def test_lets_the_rest_pass(repo: Path, name: str) -> None:
    _stage(repo, name)

    assert _hook(repo).returncode == 0


@pytest.mark.parametrize("line", CREDENTIALS.values(), ids=CREDENTIALS.keys())
def test_refuses_a_line_that_looks_like_a_credential(repo: Path, line: str) -> None:
    _stage(repo, "notes.txt", line + "\n")

    answer = _hook(repo)

    assert answer.returncode == 1
    assert "credential" in answer.stderr


def test_shows_only_the_start_of_a_credential(repo: Path) -> None:
    line = CREDENTIALS["service-token"]
    _stage(repo, "notes.txt", line + "0123456789" * 5 + "\n")

    answer = _hook(repo)

    assert answer.returncode == 1
    assert "0123456789" * 3 not in answer.stderr
    assert line.split(" = ")[1] not in answer.stderr


@pytest.mark.parametrize("line", REFERENCES)
def test_a_reference_to_a_secret_passes(repo: Path, line: str) -> None:
    _stage(repo, "notes.txt", line + "\n")

    answer = _hook(repo)

    assert answer.returncode == 0, answer.stderr


def test_all_the_references_together_pass(repo: Path) -> None:
    _stage(repo, "notes.txt", "\n".join(REFERENCES) + "\n")

    answer = _hook(repo)

    assert answer.returncode == 0, answer.stderr


@pytest.mark.parametrize("line", ADDRESSES.values(), ids=ADDRESSES.keys())
def test_refuses_an_address_on_a_domain_of_someone(repo: Path, line: str) -> None:
    _stage(repo, "notes.txt", line + "\n")

    answer = _hook(repo)

    assert answer.returncode == 1
    assert "address" in answer.stderr


def test_an_added_line_that_looks_like_a_header_is_read(repo: Path) -> None:
    _stage(repo, "notes.txt", "++ b/notes: " + ADDRESSES["address"] + "\n")

    answer = _hook(repo)

    assert answer.returncode == 1
    assert "address" in answer.stderr


def test_an_address_for_examples_passes(repo: Path) -> None:
    _stage(repo, "notes.txt", "\n".join(EXAMPLE_ADDRESSES) + "\n")

    answer = _hook(repo)

    assert answer.returncode == 0, answer.stderr


def test_an_allowlisted_line_passes(repo: Path) -> None:
    line = CREDENTIALS["env-bare"] + "  # " + ALLOW + "\n"
    _stage(repo, "notes.txt", line)

    assert _hook(repo).returncode == 0


def test_a_removed_line_is_not_looked_at(repo: Path) -> None:
    _stage(repo, "notes.txt", CREDENTIALS["env-bare"] + "\n")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t.example",
        "commit",
        "-q",
        "--no-verify",
        "-m",
        "x",
    )
    _stage(repo, "notes.txt", "nothing\n")

    assert _hook(repo).returncode == 0


def test_nothing_staged_passes(repo: Path) -> None:
    assert _hook(repo).returncode == 0


@pytest.mark.parametrize("setting", ["color.ui=always", "diff.external=echo"])
@pytest.mark.parametrize(
    "line",
    [CREDENTIALS["env-bare"], ADDRESSES["address"]],
    ids=["credential", "address"],
)
def test_the_settings_of_git_change_nothing(
    repo: Path, setting: str, line: str
) -> None:
    name, value = setting.split("=")
    _git(repo, "config", name, value)
    _stage(repo, "notes.txt", line + "\n")

    assert _hook(repo).returncode == 1
