"""What the tests of the repository share: its root, its files, its
workflows and the organisation's workflows and actions they call."""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
# Where the organisation's reusable workflows and actions live.
ORG = "benethos-hub/.github/"


@cache
def repository_files() -> tuple[Path, ...]:
    """Every file of the repository as git lists it: the tracked ones and
    new ones .gitignore does not leave out. So a cache, a virtual
    environment or a database never counts."""
    git = shutil.which("git")
    if git is None:
        pytest.fail("the repository is read through git, which is missing")
    done = subprocess.run(
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.fail("the repository is read through git: not a git checkout")
    names = sorted(set(filter(None, done.stdout.decode().split("\0"))))
    return tuple(path for name in names if (path := ROOT / name).is_file())


@cache
def tracked() -> tuple[Path, ...]:
    """The files of the repository, as text. A binary file is left out."""
    return tuple(p for p in repository_files() if b"\0" not in p.read_bytes())


def read(name: str) -> str:
    """The text of the workflow file ``name``, such as ``ci.yml``."""
    return (WORKFLOWS / name).read_text("utf-8")


def job_of(text: str, name: str) -> str:
    """The lines of one job of a workflow, below the line that names it,
    blank lines inside it included."""
    found = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", text, re.M)
    assert found, name
    return found.group(1)
