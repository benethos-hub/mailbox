"""Rules for the code of the agents beside their layers: the size of a
module and of a class, in the package and its tests
(docs/mailbox-service/ARCHITECTURE.md 15)."""

from __future__ import annotations

import ast
from pathlib import Path

import benethos_mailbox_agents

SOURCE = Path(benethos_mailbox_agents.__file__).parent
TESTS = Path(__file__).resolve().parent

# Hard limits: what grows beyond them is split by subject.
MAX_LINES = 500
MAX_METHODS = 30


def _beyond(path: Path, text: str) -> list[str]:
    """What of ``text``, read as ``path``, is beyond the limits."""
    found = []
    lines = len(text.splitlines())
    if lines > MAX_LINES:
        found.append(f"{path.as_posix()}: {lines} lines")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ClassDef):
            methods = sum(
                isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in node.body
            )
            if methods > MAX_METHODS:
                found.append(f"{path.as_posix()}: {node.name} has {methods} methods")
    return found


def test_modules_and_classes_stay_small() -> None:
    """The package and its tests."""
    violations = [
        found
        for folder in (SOURCE, TESTS)
        for path in sorted(folder.rglob("*.py"))
        for found in _beyond(path.relative_to(folder.parent), path.read_text("utf-8"))
    ]
    assert not violations, "beyond the limits:\n  " + "\n  ".join(violations)


def test_the_limits_find_a_long_module_and_a_large_class() -> None:
    methods = "".join(f"    def m{i}(self) -> None: ...\n" for i in range(31))
    large = "class Large:\n" + methods
    long = "x = 1\n" * 501

    assert _beyond(Path("large.py"), large) == ["large.py: Large has 31 methods"]
    assert _beyond(Path("long.py"), long) == ["long.py: 501 lines"]
