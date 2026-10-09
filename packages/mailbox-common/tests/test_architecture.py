"""The package stands below the others: it imports none of them, and
nothing but the standard library and the libraries named here."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = "benethos_mailbox_common"
ROOT = Path(__file__).resolve().parents[1] / "src" / PACKAGE

# Where each library beyond the standard library may be imported.
LIBRARY_HOMES: dict[str, set[str]] = {
    "platformdirs": {"folders"},
}


def _imports(path: Path) -> list[tuple[str, int]]:
    """What the module imports from outside the package, by its top name."""
    found = []
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            found += [(alias.name.split(".")[0], node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            found.append(((node.module or "").split(".")[0], node.lineno))
    return [(name, line) for name, line in found if name not in ("__future__", PACKAGE)]


def test_only_the_standard_library_and_the_named_libraries() -> None:
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        module = path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        for name, line in _imports(path):
            if name in sys.stdlib_module_names:
                continue
            if module not in LIBRARY_HOMES.get(name, set()):
                violations.append(f"{module}:{line} imports {name}")
    assert not violations, "outside the allowed:\n  " + "\n  ".join(violations)


def test_no_module_is_long() -> None:
    """The limit of the other packages (docs/ARCHITECTURE.md 15)."""
    long = [
        f"{path.name}: {n}"
        for path in sorted(ROOT.rglob("*.py"))
        if (n := len(path.read_text("utf-8").splitlines())) > 500
    ]
    assert not long
