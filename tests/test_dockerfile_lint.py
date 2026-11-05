"""The Dockerfile lint: the wiring of the dockerfile-lint job in ci.yml.

hadolint runs through the organisation's workflow, which proves itself there.
What can go wrong here is the call: a pattern that misses a Dockerfile, a
registry a FROM line pulls from that the call does not trust, or a permission
beyond the upload.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from .publish_helpers import ROOT

CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
JOB = CI.split("\n  dockerfile-lint:\n", 1)[1].split("\n\n  ", 1)[0]


def _input(name: str) -> str:
    match = re.search(rf"^\s+{name}: (.+)$", JOB, re.M)
    assert match, f"the job passes no {name}"
    return match.group(1).strip()


def _dockerfiles() -> list[Path]:
    files = [
        path
        for path in ROOT.rglob("Dockerfile*")
        if ".venv" not in path.parts and ".git" not in path.parts
    ]
    assert files, "no Dockerfile in the repository"
    return files


def test_the_job_calls_the_organisations_workflow() -> None:
    assert (
        "uses: benethos-hub/.github/.github/workflows/dockerfile-lint.yml@main" in JOB
    )


def test_the_patterns_match_every_dockerfile_of_the_repository() -> None:
    patterns = _input("files").split()
    for path in _dockerfiles():
        relative = path.relative_to(ROOT).as_posix()
        assert any(fnmatch(relative, pattern) for pattern in patterns), relative


def test_every_registry_a_from_line_pulls_from_is_trusted() -> None:
    """An image from elsewhere is a finding, so the list names what is used."""
    trusted = set(_input("trusted-registries").split())
    for path in _dockerfiles():
        for line in path.read_text("utf-8").splitlines():
            if not line.startswith("FROM "):
                continue
            image = line.split()[1]
            # A registry is the first path component, and only when there is
            # one and it looks like a host: python:3.15-slim is Docker Hub.
            first, slash, _ = image.partition("/")
            is_host = slash and ("." in first or ":" in first or first == "localhost")
            registry = first if is_host else "docker.io"
            assert registry in trusted, f"{path.name}: {image} comes from {registry}"


def test_the_upload_permission_and_nothing_more() -> None:
    assert "security-events: write" in JOB
    assert "contents: read" in JOB
    assert "write" not in JOB.replace("security-events: write", "")
