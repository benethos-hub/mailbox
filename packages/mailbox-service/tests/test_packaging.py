"""What the two distributions ship beside their code.

Each package carries a copy of the repository's LICENSE, since a wheel can
only include files from its own folder, and both are released together
under one version. The documentation quotes that version in several
places, and those examples must follow it.
"""

from __future__ import annotations

import json
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
    # The version the compose file of operation runs.
    "env": r"MAILBOX_VERSION=(\d+\.\d+\.\d+)",
    # The image tag of the minor line. It stays across a patch release and
    # moves with a minor one, so it is compared with the first two parts.
    "minor": r"the minor version\s+\(`(\d+\.\d+)`\)",
}
VERSION_EXAMPLES = [
    ("README.md", "status"),
    ("containers/README.md", "status"),
    ("containers/production/.env.example", "env"),
    ("containers/production/README.md", "image"),
    ("packages/mailbox-service/README.md", "env"),
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


# --- every place, not only the listed ones ---------------------------------------

# Text files are searched whole for the patterns above. The changelog keeps
# the old versions on purpose, the lockfile is checked on its own.
SEARCHED = {".md", ".toml", ".yaml", ".yml", ".json", ".example", ".html", ".txt"}
SKIPPED_DIRS = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "data",
    "dist",
    "node_modules",
}
SKIPPED_FILES = {"CHANGELOG.md", "uv.lock"}


def _text_files() -> list[Path]:
    found = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in SKIPPED_DIRS for part in relative.parts[:-1]):
            continue
        if not path.is_file() or path.name in SKIPPED_FILES:
            continue
        if path.suffix in SEARCHED or path.name == "Dockerfile":
            found.append(path)
    return found


def test_no_file_names_another_version() -> None:
    """A place that names the version anywhere in the repository, also
    one not in the lists above, names the current one."""
    current = _version()
    minor = ".".join(current.split(".")[:2])
    stale = []
    for path in _text_files():
        text = path.read_text("utf-8", errors="replace")
        for kind, pattern in PATTERNS.items():
            wanted = minor if kind == "minor" else current
            for value in set(re.findall(pattern, text)) - {wanted}:
                stale.append(f"{path.relative_to(ROOT)}: {kind} {value}")
    assert not stale, "not the current version:\n  " + "\n  ".join(sorted(stale))


def test_the_openapi_document_has_the_version() -> None:
    document = json.loads((ROOT / "docs" / "openapi.json").read_text("utf-8"))
    assert document["info"]["version"] == _version()


def test_the_lockfile_has_the_version_of_both_packages() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text("utf-8"))
    names = {str(_project(package)["name"]) for package in PACKAGES}
    locked = {p["name"]: p["version"] for p in lock["package"] if p["name"] in names}
    assert locked == dict.fromkeys(names, _version())


def test_the_changelog_names_the_version_as_its_newest_release() -> None:
    text = (ROOT / "CHANGELOG.md").read_text("utf-8")
    current = _version()
    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d\d-\d\d$", text, re.M)
    assert released, "CHANGELOG.md names no release"
    assert released[0] == current
    base = "https://github.com/benethos-hub/mailbox"
    assert f"[Unreleased]: {base}/compare/v{current}...HEAD" in text
    assert re.search(rf"^\[{re.escape(current)}\]: {base}/", text, re.M)


def test_the_status_follows_the_classifier() -> None:
    """``Development Status :: 3 - Alpha`` in both packages, and "alpha"
    in every status line of the documentation."""
    statuses = set()
    for package in PACKAGES:
        classifiers = _project(package)["classifiers"]
        assert isinstance(classifiers, list)
        statuses |= {
            c.rpartition(" - ")[2].lower()
            for c in classifiers
            if c.startswith("Development Status ::")
        }
    assert len(statuses) == 1, statuses
    status = statuses.pop()
    wrong = []
    for relative, kind in VERSION_EXAMPLES:
        if kind != "status":
            continue
        text = (ROOT / relative).read_text("utf-8")
        words = re.findall(r"([\w-]+), version \d+\.\d+\.\d+\.", text)
        wrong += [f"{relative}: {w}" for w in words if w.lower() != status]
    assert not wrong, f"not {status!r}:\n  " + "\n  ".join(wrong)
