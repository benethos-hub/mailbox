"""The trees of docs/mailbox-service/ARCHITECTURE.md section 3, which are in
docs/mailbox-service/architecture/, against the disk.

Each package's tree names its modules: some as lines of their own, some
in the comment of the folder that holds them. A module added or moved
goes unnoticed there, so this checks:

- every path the trees name is there;
- every package of the code is named in the part of the tree of the
  nearest folder named above it, as a line or in a comment;
- a folder that names some of its modules as lines names all of them.
"""

from __future__ import annotations

import re
from pathlib import Path

from .repository_helpers import ROOT

ARCHITECTURE = ROOT / "docs" / "mailbox-service" / "architecture"
# Section 3, the trees, and sections 5 to 17, the rules.
TREES = (
    ARCHITECTURE / "modules-service.md",
    ROOT / "docs" / "architecture" / "modules-packages.md",
)
RULES = ARCHITECTURE / "rules.md"
PACKAGES = ("mailbox-service", "mailbox-client", "mailbox-mcp", "mailbox-common")

_TREE = re.compile(r"^```\n(packages/.*?)^```", re.M | re.S)
# A line of a tree: its indent, a path (a folder ends in /), a comment.
_ENTRY = re.compile(r"^( *)([\w.\-]+(?:/[\w.\-]+)*/?)(?:\s+#.*)?$")


def _parts() -> dict[Path, str]:
    """Each path the trees name, with its part of the tree: its line and
    every line below it up to the next one at its indent or less."""
    section = "".join(path.read_text(encoding="utf-8") for path in TREES)
    parts: dict[Path, str] = {}
    for tree in _TREE.findall(section):
        lines = tree.splitlines()
        folders: list[tuple[int, Path]] = []
        entries: list[tuple[int, int, Path]] = []
        for number, line in enumerate(lines):
            match = _ENTRY.match(line)
            if match is None:
                continue
            indent, name = len(match.group(1)), match.group(2)
            while folders and folders[-1][0] >= indent:
                folders.pop()
            path = (folders[-1][1] if folders else Path()) / name.rstrip("/")
            entries.append((number, indent, path))
            if name.endswith("/"):
                folders.append((indent, path))
        for k, (number, indent, path) in enumerate(entries):
            end = next((e[0] for e in entries[k + 1 :] if e[1] <= indent), len(lines))
            parts[path] = "\n".join(lines[number:end])
    return parts


def _sources() -> list[Path]:
    """The code of each package, from the repository's root."""
    found = []
    for package in PACKAGES:
        (code,) = (
            p for p in (ROOT / "packages" / package / "src").iterdir() if p.is_dir()
        )
        found += [
            p.relative_to(ROOT)
            for p in sorted(code.rglob("*"))
            if "__pycache__" not in p.parts
        ]
    return found


def _names(part: str, name: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(name)}\b", part) is not None


def test_every_path_named_is_there() -> None:
    missing = [p.as_posix() for p in _parts() if not (ROOT / p).exists()]
    assert missing == [], f"named in ARCHITECTURE 3, not on disk: {missing}"


def test_every_package_is_named() -> None:
    parts = _parts()
    unnamed = []
    for path in _sources():
        if path in parts or not (ROOT / path / "__init__.py").is_file():
            continue
        above = next((a for a in path.parents if a in parts), None)
        if above is None or not _names(parts[above], path.name):
            unnamed.append(path.as_posix())
    assert unnamed == [], f"packages ARCHITECTURE 3 does not name: {unnamed}"


def test_a_folder_that_lists_modules_lists_all() -> None:
    parts = _parts()
    listing = {p.parent for p in parts if p.suffix == ".py"}
    unnamed = [
        path.as_posix()
        for path in _sources()
        if path.suffix == ".py"
        and path.name != "__init__.py"
        and path.parent in listing
        and path not in parts
    ]
    assert unnamed == [], f"modules missing from their folder's lines: {unnamed}"


SERVICE = ROOT / "packages" / "mailbox-service" / "src" / "benethos_mailbox_service"


def test_every_seam_is_in_the_table_of_section_8() -> None:
    """Each protocol of ``data/providers/base.py`` and each repository
    ``data/storage`` exports is named in the table of the seams."""
    text = RULES.read_text(encoding="utf-8")
    table = text[text.index("\n## 8. ") : text.index("\n## 9. ")]
    base = (SERVICE / "data" / "providers" / "base.py").read_text(encoding="utf-8")
    protocols = re.findall(r"^class (\w+)\(.*Protocol.*\):", base, re.M)
    storage = (SERVICE / "data" / "storage" / "__init__.py").read_text("utf-8")
    exported = re.findall(r'^    "(\w+Repository)",', storage, re.M)
    repositories = [n for n in exported if not n.startswith(("InMemory", "Sqlite"))]
    assert protocols and repositories
    missing = [n for n in protocols + repositories if f"`{n}`" not in table]
    assert missing == [], "not in ARCHITECTURE 8"
