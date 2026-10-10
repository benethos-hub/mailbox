"""The package stands below the others: it imports none of them, and
nothing but the standard library and the libraries named here. It is
made of groups: a module imports only inside its own, and a caller
imports a module from its group, never deeper (docs/ARCHITECTURE.md 5.3
and 5.4)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = "benethos_mailbox_common"
ROOT = Path(__file__).resolve().parents[1] / "src" / PACKAGE

# Where each library beyond the standard library may be imported.
LIBRARY_HOMES: dict[str, set[str]] = {
    "platformdirs": {"paths.folders"},
    "pydantic_settings": {"settings.files"},
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
PACKAGES = ROOT.parents[2]


def _groups() -> list[Path]:
    return sorted(p for p in ROOT.iterdir() if (p / "__init__.py").is_file())


def test_the_root_imports_no_group() -> None:
    """``import benethos_mailbox_common`` loads no group and no library."""
    tree = ast.parse((ROOT / "__init__.py").read_text("utf-8"))
    ours = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.level or (node.module or "").startswith(PACKAGE))
    ]
    assert not ours
    assert {p.name for p in ROOT.glob("*.py")} == {"__init__.py"}


def test_a_group_offers_its_modules() -> None:
    """Its ``__all__`` names every module of the group, nothing else."""
    for group in _groups():
        modules = {p.stem for p in group.glob("*.py") if p.name != "__init__.py"}
        tree = ast.parse((group / "__init__.py").read_text("utf-8"))
        offered = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "__all__" for t in node.targets)
        )
        assert set(offered) == modules, group.name


def test_a_module_imports_only_inside_its_group() -> None:
    violations = []
    for group in _groups():
        for path in sorted(group.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text("utf-8"))):
                if not isinstance(node, ast.ImportFrom):
                    continue
                module = node.module or ""
                crosses = node.level > 1 or (
                    not node.level
                    and module.startswith(PACKAGE)
                    and not module.startswith(f"{PACKAGE}.{group.name}")
                )
                if crosses:
                    violations.append(f"{group.name}/{path.name}:{node.lineno}")
    assert not violations, "across groups:\n  " + "\n  ".join(violations)


def test_a_caller_imports_a_module_from_its_group() -> None:
    """``from benethos_mailbox_common.log import lines``, never
    ``benethos_mailbox_common.log.lines``. Tests may reach inside."""
    violations = []
    for consumer in CONSUMERS:
        for path in sorted((PACKAGES / consumer / "src").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text("utf-8"))):
                if isinstance(node, ast.ImportFrom) and not node.level:
                    names = [node.module or ""]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                for name in names:
                    if name.startswith(f"{PACKAGE}.") and name.count(".") > 1:
                        where = path.relative_to(PACKAGES).as_posix()
                        violations.append(f"{where}:{node.lineno} {name}")
    assert not violations, "deeper than a group:\n  " + "\n  ".join(violations)


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
    violations = []
    for consumer in CONSUMERS:
        source = PACKAGES / consumer / "src"
        for path in sorted(source.rglob("*.py")):
            name = path.relative_to(PACKAGES).as_posix()
            for function in sorted(_functions(path) & shared):
                violations.append(f"{name}: {function}")
    assert not violations, "a copy of a helper:\n  " + "\n  ".join(violations)
