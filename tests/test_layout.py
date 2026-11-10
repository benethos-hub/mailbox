"""The project layout of CLAUDE.md held to the disk.

``test_module_tree.py`` holds the trees of docs/ARCHITECTURE.md to the code
of the packages. The layout of CLAUDE.md names what lies around them: the
files at the root, the workflows, the documents and the tests of the
repository. Every path it names exists, and every file directly in
``docs/``, ``.github/workflows/`` and ``tests/`` is named there, but for
the helpers of the tests.
"""

from __future__ import annotations

import re

from .repository_helpers import ROOT, WORKFLOWS

CLAUDE = (ROOT / "CLAUDE.md").read_text("utf-8")
# The block of the layout, between its fences.
BLOCK = re.search(r"^## Project layout\n.*?^```\n(.*?)^```", CLAUDE, re.M | re.S)


def _block() -> str:
    assert BLOCK is not None, "CLAUDE.md has no project layout"
    return BLOCK.group(1)


def _named() -> list[str]:
    """Every path the layout names, its folders resolved by indentation."""
    found = []
    folders: list[tuple[int, str]] = []
    for line in _block().splitlines():
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        indent = len(line) - len(line.lstrip())
        while folders and folders[-1][0] >= indent:
            folders.pop()
        path = (folders[-1][1] if folders else "") + entry
        found.append(path)
        if entry.endswith("/"):
            folders.append((indent, path))
    return found


def test_every_path_it_names_exists() -> None:
    named = _named()
    assert len(named) > 50
    missing = [path for path in named if not (ROOT / path).exists()]
    assert not missing, "named in CLAUDE.md, not on disk:\n  " + "\n  ".join(missing)


def test_every_document_and_test_of_the_repository_is_named() -> None:
    named = set(_named())
    on_disk = [
        *(f"docs/{p.name}" for p in (ROOT / "docs").iterdir() if p.is_file()),
        *(
            f"tests/{p.name}"
            for p in (ROOT / "tests").glob("*.py")
            if not p.stem.endswith("_helpers") and p.stem != "__init__"
        ),
    ]
    unnamed = sorted(path for path in on_disk if path not in named)
    assert not unnamed, "not in CLAUDE.md's layout:\n  " + "\n  ".join(unnamed)


def test_every_workflow_is_described() -> None:
    block = _block()
    unnamed = sorted(
        p.name for p in WORKFLOWS.glob("*.yml") if f"{p.name}:" not in block
    )
    assert not unnamed, "workflows CLAUDE.md does not describe: " + ", ".join(unnamed)
