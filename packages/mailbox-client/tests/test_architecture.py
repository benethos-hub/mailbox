"""The layout of the client package, checked instead of only written down
(docs/ARCHITECTURE.md 3).

It knows the service through the REST API alone: it neither depends on
nor imports the service or the MCP server. Each module imports only the
lines below its own, a package counting as one, and httpx is imported
where a request is made or read or an address is checked, nowhere else:
the endpoints, the records and the errors know no HTTP library.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

PACKAGE = "benethos_mailbox_client"
PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "src" / PACKAGE
OTHERS = ("benethos_mailbox_service", "benethos_mailbox_mcp")

# The modules and packages in lines, the top first. A package is one unit:
# its modules import each other as they like.
LINES = (
    {"client", "sync"},
    {"endpoints"},
    {"answers", "attachments", "environment"},
    {"calls"},
    {"models", "errors"},
)
HTTPX_HOMES = {"client", "sync", "calls", "answers", "attachments", "environment"}


def _modules() -> list[tuple[str, str, ast.Module]]:
    """Each module but the root ``__init__``: the unit it belongs to (the
    module, or its package), its path below the package, its tree."""
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        parts = path.relative_to(ROOT).with_suffix("").parts
        if parts == ("__init__",):
            continue
        found.append((parts[0], "/".join(parts), ast.parse(path.read_text("utf-8"))))
    return found


def _imports(where: str, tree: ast.Module) -> list[tuple[str, int, bool]]:
    """What a module imports: the unit, the line, and whether it is ours.
    A relative import is resolved from the module's place in the
    package to the unit it reaches."""
    found = []
    package = where.split("/")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno, False) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                names = [node.module] if node.module else [a.name for a in node.names]
                for name in names:
                    target = [*base, *name.split(".")]
                    found.append((target[0], node.lineno, True))
            elif node.module != "__future__":
                found.append((node.module or "", node.lineno, False))
    return found


def _line(name: str) -> int | None:
    return next((n for n, line in enumerate(LINES) if name in line), None)


def test_no_dependency_on_the_service_or_the_mcp_server() -> None:
    project = tomllib.loads((PROJECT / "pyproject.toml").read_text("utf-8"))
    names = [
        d.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
        for d in project["project"]["dependencies"]
    ]
    assert names == ["httpx"]


def test_no_import_of_the_service_or_the_mcp_server() -> None:
    offenders = [
        f"{where}:{line} imports {imported}"
        for _, where, tree in _modules()
        for imported, line, ours in _imports(where, tree)
        if not ours and imported.split(".")[0] in OTHERS
    ]
    assert offenders == []


def test_every_module_is_in_a_line() -> None:
    assert {unit for unit, _, _ in _modules()} == set().union(*LINES)


def test_a_module_imports_only_lines_below() -> None:
    violations = []
    for unit, where, tree in _modules():
        for imported, line, ours in _imports(where, tree):
            if ours and imported == unit:
                continue
            if ours and (_line(imported) or 0) <= (_line(unit) or 0):
                violations.append(f"{where}:{line} imports {imported}")
    assert not violations, "against the lines:\n  " + "\n  ".join(violations)


def test_httpx_where_requests_are_made_or_read() -> None:
    violations = [
        f"{where}:{line}"
        for unit, where, tree in _modules()
        for imported, line, ours in _imports(where, tree)
        if not ours and imported.split(".")[0] == "httpx" and unit not in HTTPX_HOMES
    ]
    assert not violations, "httpx outside its homes:\n  " + "\n  ".join(violations)


def test_the_endpoints_are_imported_through_their_package() -> None:
    """A module of ``endpoints/`` is reached from outside through the
    package alone, so the package can split or merge its modules."""
    violations = [
        f"{where}:{line}"
        for unit, where, tree in _modules()
        if unit != "endpoints"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level
        and node.module
        and node.module.startswith("endpoints.")
        for line in [node.lineno]
    ]
    assert violations == []


# Hard limits (docs/ARCHITECTURE.md 15): what grows beyond them is split
# by subject.
MAX_LINES = 500
MAX_METHODS = 30


def test_modules_and_classes_stay_small() -> None:
    """The package and its tests."""
    tests = Path(__file__).resolve().parent
    violations = []
    for path in sorted([*ROOT.rglob("*.py"), *tests.rglob("*.py")]):
        text = path.read_text("utf-8")
        name = path.relative_to(tests.parent).as_posix()
        lines = len(text.splitlines())
        if lines > MAX_LINES:
            violations.append(f"{name}: {lines} lines")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ClassDef):
                methods = sum(
                    isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                    for n in node.body
                )
                if methods > MAX_METHODS:
                    violations.append(f"{name}: {node.name} has {methods} methods")
    assert not violations, "beyond the limits:\n  " + "\n  ".join(violations)
