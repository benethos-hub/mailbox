"""What the two distributions ship beside their code.

Each package carries a copy of the repository's LICENSE, since a wheel can
only include files from its own folder, and both are released together
under one version. The documentation quotes that version in several
places, and those examples must follow it.
"""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = [ROOT / "packages" / "mailbox-service", ROOT / "packages" / "mailbox-mcp"]


def _project(package: Path) -> dict[str, object]:
    data = tomllib.loads((package / "pyproject.toml").read_text("utf-8"))
    return dict(data["project"])


def _version() -> str:
    return str(_project(PACKAGES[0])["version"])


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_the_license_is_the_repositorys(package: Path) -> None:
    assert (package / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert _project(package)["license-files"] == ["LICENSE"]


def test_both_packages_share_one_version() -> None:
    versions = {_project(package)["version"] for package in PACKAGES}
    assert len(versions) == 1, versions


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_the_installed_version_is_the_projects(package: Path) -> None:
    """After a version bump without ``uv sync``, the code still reports
    the old version in /health, the OpenAPI document and ``--version``."""
    project = _project(package)
    assert version(str(project["name"])) == project["version"]


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_the_type_marker_ships_empty(package: Path) -> None:
    """Without ``py.typed`` a type checker treats the installed package as
    untyped (PEP 561). The file is a marker and has no content."""
    module = str(_project(package)["name"]).replace("-", "_")
    marker = package / "src" / module / "py.typed"
    assert marker.is_file(), f"{marker} is missing"
    assert marker.read_bytes() == b""


# Every place the documentation names the current version, as a file and a
# pattern whose group is that version. The pattern must still match, or the
# test would pass while it checks nothing.
PATTERNS = {
    "status": r"version (\d+\.\d+\.\d+)\.",
    "tag": r"the version \(`(\d+\.\d+\.\d+)`\)",
    "image": r"ghcr\.io/benethos-hub/benethos-mailbox-(?:service|mcp):(\d+\.\d+\.\d+)",
    # The image tag of the minor line. It stays across a patch release and
    # moves with a minor one, so it is compared with the first two parts.
    "minor": r"the minor version\s+\(`(\d+\.\d+)`\)",
}
VERSION_EXAMPLES = [
    ("README.md", "status"),
    ("containers/README.md", "status"),
    ("docs/CONCEPT.md", "status"),
    ("docs/ROADMAP.md", "status"),
    ("docs/microsoft.md", "status"),
    ("packages/mailbox-service/README.md", "status"),
    ("packages/mailbox-service/README.md", "tag"),
    ("packages/mailbox-service/README.md", "image"),
    ("packages/mailbox-mcp/README.md", "status"),
    ("packages/mailbox-mcp/README.md", "tag"),
    ("packages/mailbox-mcp/README.md", "image"),
]

MINOR_EXAMPLES = [
    ("packages/mailbox-service/README.md", "minor"),
    ("packages/mailbox-mcp/README.md", "minor"),
]


def _ids(examples: list[tuple[str, str]]) -> list[str]:
    return [f"{relative}:{kind}" for relative, kind in examples]


def _found(relative: str, kind: str) -> set[str]:
    text = (ROOT / relative).read_text("utf-8")
    found = set(re.findall(PATTERNS[kind], text))
    assert found, f"{relative} no longer contains {PATTERNS[kind]!r}"
    return found


@pytest.mark.parametrize(
    ("relative", "kind"), VERSION_EXAMPLES, ids=_ids(VERSION_EXAMPLES)
)
def test_version_examples_are_current(relative: str, kind: str) -> None:
    stale = _found(relative, kind) - {_version()}
    assert not stale, f"{relative} still shows {sorted(stale)}, not {_version()}"


@pytest.mark.parametrize(("relative", "kind"), MINOR_EXAMPLES, ids=_ids(MINOR_EXAMPLES))
def test_minor_line_examples_are_current(relative: str, kind: str) -> None:
    minor = ".".join(_version().split(".")[:2])
    stale = _found(relative, kind) - {minor}
    assert not stale, f"{relative} still shows {sorted(stale)}, not {minor}"
