"""The layout of the MCP package, checked instead of only written down
(docs/REFACTORING.md 10.2 and 10.3).

Each module imports only the lines below its own. The tools are reached
through their package's ``__init__.py``, and inside it each kind imports
only what lies below. Each library has one home.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = "benethos_mailbox_mcp"
ROOT = Path(__file__).resolve().parents[1] / "src" / PACKAGE

# The modules of the package in lines, the top first.
LINES = (
    {"cli"},
    {"server", "transport"},
    {"tools"},
    {"client", "render", "pdf"},
    {"models", "errors", "config", "plaintext"},
)
# The same inside tools/.
TOOL_LINES = (
    {"accounts"},
    {"reading", "writing", "drafts", "sending"},
    {"compose"},
    {"base"},
)
# Where each library may be imported: a module, or a package with all its
# modules.
LIBRARY_HOMES = {
    # The REST client, and its records and errors. The server speaks no
    # HTTP to the service itself, so httpx has no home.
    "benethos_mailbox_client": {"client", "models", "errors"},
    "httpx": set(),
    "pypdfium2": {"pdf"},
    "starlette": {"transport"},
    "uvicorn": {"transport"},
    "mcp": {"server", "transport", "errors", "tools.base"},
    "platformdirs": {"config"},
    "dotenv": {"config"},
}


def _modules() -> list[tuple[str, Path]]:
    """Every module as its dotted name below the package: ``server``,
    ``tools.reading``, ``tools`` for ``tools/__init__.py``."""
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        parts = list(path.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts and parts != ["__main__"]:
            found.append((".".join(parts), path))
    return found


def _imports(name: str, path: Path) -> list[tuple[str, int]]:
    """What the module imports, as dotted names: ours below the package,
    a library by its full name with a ``!`` in front."""
    package = name.split(".")[:-1] if path.name != "__init__.py" else name.split(".")
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [("!" + alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                module = node.module or ""
                if module.startswith(PACKAGE + "."):
                    found.append((module[len(PACKAGE) + 1 :], node.lineno))
                elif module != "__future__":
                    found.append(("!" + module, node.lineno))
                continue
            base = package[: len(package) - node.level + 1]
            target = ".".join([*base, *([node.module] if node.module else [])])
            if node.module:
                found.append((target, node.lineno))
            # ``from . import x`` imports a module by name.
            for alias in node.names:
                sub = f"{target}.{alias.name}" if target else alias.name
                if _is_module(sub):
                    found.append((sub, node.lineno))
    return found


def _is_module(dotted: str) -> bool:
    base = ROOT.joinpath(*dotted.split("."))
    return base.with_suffix(".py").exists() or (base / "__init__.py").exists()


def _line(lines: tuple[set[str], ...], part: str) -> int | None:
    return next((n for n, line in enumerate(lines) if part in line), None)


def test_every_module_is_in_a_line() -> None:
    top = {name.split(".")[0] for name, _ in _modules()}
    inside = {name.split(".")[1] for name, _ in _modules() if name.count(".") == 1}
    assert top == set().union(*LINES)
    assert inside == set().union(*TOOL_LINES)


def test_a_module_imports_only_lines_below() -> None:
    violations = []
    for name, path in _modules():
        own = _line(LINES, name.split(".")[0])
        for imported, line in _imports(name, path):
            if imported.startswith("!") or not imported:
                continue
            first = imported.split(".")[0]
            other = _line(LINES, first)
            if first == name.split(".")[0] or other is None or own is None:
                continue
            if other <= own:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "against the lines:\n  " + "\n  ".join(violations)


def test_inside_tools_each_kind_imports_only_below() -> None:
    violations = []
    for name, path in _modules():
        if not name.startswith("tools."):
            continue
        own = _line(TOOL_LINES, name.split(".")[1])
        for imported, line in _imports(name, path):
            if not imported.startswith("tools."):
                continue
            other = _line(TOOL_LINES, imported.split(".")[1])
            if other is not None and own is not None and other <= own:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "against the lines:\n  " + "\n  ".join(violations)


def test_the_tools_are_reached_through_their_package() -> None:
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in _modules()
        if not name.startswith("tools")
        for imported, line in _imports(name, path)
        if imported.startswith("tools.")
    ]
    assert not violations, "a module inside tools/:\n  " + "\n  ".join(violations)


def test_each_library_has_one_home() -> None:
    violations = []
    for name, path in _modules():
        for imported, line in _imports(name, path):
            if not imported.startswith("!"):
                continue
            library = imported[1:].split(".")[0]
            homes = LIBRARY_HOMES.get(library)
            if homes is not None and name not in homes:
                violations.append(f"{name}:{line} imports {imported[1:]}")
    assert not violations, "library outside its home:\n  " + "\n  ".join(violations)


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
