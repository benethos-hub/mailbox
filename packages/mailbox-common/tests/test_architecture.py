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


# The packages that use this one.
CONSUMERS = ("mailbox-service", "mailbox-mcp")


def _functions(path: Path) -> set[str]:
    """The functions a module defines at its top level, without a leading
    underscore."""
    tree = ast.parse(path.read_text("utf-8"))
    return {
        node.name.lstrip("_")
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_a_function_of_the_package_exists_once() -> None:
    """No module of the service or the MCP server defines a function of
    this package again, under its name or with a leading underscore."""
    shared = set().union(*(_functions(p) for p in ROOT.rglob("*.py")))
    packages = ROOT.parents[2]
    violations = []
    for consumer in CONSUMERS:
        source = packages / consumer / "src"
        for path in sorted(source.rglob("*.py")):
            name = path.relative_to(packages).as_posix()
            for function in sorted(_functions(path) & shared):
                violations.append(f"{name}: {function}")
    assert not violations, "a copy of a helper:\n  " + "\n  ".join(violations)
