"""The layout of the client package, checked instead of only written down
(docs/ARCHITECTURE.md 3).

It knows the service through the REST API alone: it neither depends on
nor imports the service or the MCP server. Each module imports only the
lines below its own, and httpx is imported where requests are made or
read, nowhere else.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

PACKAGE = "benethos_mailbox_client"
PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "src" / PACKAGE
OTHERS = ("benethos_mailbox_service", "benethos_mailbox_mcp")

# The modules of the package in lines, the top first.
LINES = (
    {"client", "sync"},
    {"endpoints"},
    {"wire"},
    {"models", "errors"},
)
HTTPX_HOMES = {"client", "sync", "wire"}


def _modules() -> list[tuple[str, ast.Module]]:
    return [
        (path.stem, ast.parse(path.read_text("utf-8")))
        for path in sorted(ROOT.glob("*.py"))
        if path.stem != "__init__"
    ]


def _imports(tree: ast.Module) -> list[tuple[str, int, bool]]:
    """What a module imports: the name, the line, and whether it is ours."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno, False) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names = [node.module] if node.module else [a.name for a in node.names]
                found += [(name, node.lineno, True) for name in names]
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
        f"{name}:{line} imports {imported}"
        for name, tree in _modules()
        for imported, line, ours in _imports(tree)
        if not ours and imported.split(".")[0] in OTHERS
    ]
    assert offenders == []


def test_every_module_is_in_a_line() -> None:
    assert {name for name, _ in _modules()} == set().union(*LINES)


def test_a_module_imports_only_lines_below() -> None:
    violations = []
    for name, tree in _modules():
        for imported, line, ours in _imports(tree):
            if ours and (_line(imported) or 0) <= (_line(name) or 0):
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "against the lines:\n  " + "\n  ".join(violations)


def test_httpx_where_requests_are_made_or_read() -> None:
    violations = [
        f"{name}:{line}"
        for name, tree in _modules()
        for imported, line, ours in _imports(tree)
        if not ours and imported.split(".")[0] == "httpx" and name not in HTTPX_HOMES
    ]
    assert not violations, "httpx outside its homes:\n  " + "\n  ".join(violations)


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
