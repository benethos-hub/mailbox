"""What never belongs in a versioned file, checked over every tracked file.

The pre-commit hook in .githooks/ looks at staged lines, and only where it
is enabled. This test reads the files git tracks, on every run of the
suite and so in CI, and fails on:

- a path of a machine or of a user, also in the form Git Bash and WSL
  write it,
- an id as the service gives it to a real account, user or token,
- a credential in the forms the pre-commit hook knows: a token by its
  prefix, and a value given to a name such as ``*_TOKEN`` or ``password``.

A line that must show such a form ends with ``pragma: allowlist secret``,
as for the hook. See CLAUDE.md, golden rules 5 and 8.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

from .content_helpers import ALLOW, CREDENTIALS, REFERENCES, problems
from .repository_helpers import ROOT


@cache
def tracked() -> tuple[Path, ...]:
    """The files git tracks, as text. A binary file is left out."""
    git = shutil.which("git")
    if git is None:
        pytest.fail("the repository content is read through git, which is missing")
    done = subprocess.run(
        [git, "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
    )
    if done.returncode != 0:
        pytest.fail("the repository content is read through git: not a git checkout")
    found = []
    for name in filter(None, done.stdout.decode().split("\0")):
        path = ROOT / name
        if path.is_file() and b"\0" not in path.read_bytes():
            found.append(path)
    return tuple(found)


def test_the_repository_holds_none_of_it() -> None:
    files = tracked()
    assert len(files) > 500, "git listed too few files to be this repository"
    hits = []
    for path in files:
        text = path.read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            hits += [
                f"{path.relative_to(ROOT).as_posix()}:{number}: {problem}"
                for problem in problems(line)
            ]
    assert hits == [], "\n".join(hits)


# -- the rules themselves, on lines put together so the scan above does
# -- not find them in this file.


@pytest.mark.parametrize(
    "line",
    [
        "C:" + "\\Users\\someone\\project",
        "D:/" + "Users/someone/x",
        "/" + "Users/someone/project",
        "/" + "home/someone/.local",
        "sh /" + "mnt/d/projects/x/setup.sh",
        "/" + "c/Users/someone/project",
        "cd /" + "d/projects/mailbox",
        "D:" + "\\projects\\mailbox\\data",
        "d:" + "/projects/mailbox",
    ],
)
def test_a_path_of_a_machine_is_found(line: str) -> None:
    assert problems(line)


@pytest.mark.parametrize(
    "line",
    [
        "containers/production/secrets/master.key",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "      - ./caddy.d:/etc/caddy/caddy.d:ro",
        r"re.compile(r'\d:\d')",
        "see https://example.org/home/page",
    ],
)
def test_a_path_inside_the_project_passes(line: str) -> None:
    assert problems(line) == []


def test_an_id_of_the_service_is_found() -> None:
    assert problems("account " + "acc" + "_" + "3f9a" * 16)
    assert problems("token " + "tok" + "_" + "0b1c" * 16)
    assert problems("account acc_1, message m1, the commit 3f9a0b1c") == []


@pytest.mark.parametrize("line", CREDENTIALS.values(), ids=CREDENTIALS.keys())
def test_a_credential_is_found(line: str) -> None:
    assert problems(line)


@pytest.mark.parametrize("line", REFERENCES)
def test_a_name_that_is_given_no_value_passes(line: str) -> None:
    assert problems(line) == []


def test_an_allowlisted_line_passes() -> None:
    line = next(iter(CREDENTIALS.values()))
    assert problems(line + "  # " + ALLOW) == []
