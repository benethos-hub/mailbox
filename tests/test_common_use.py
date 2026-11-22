"""How the service, the MCP server and the agents use mailbox-common:
a module from its group, never a private name of it, and no function of
it defined again (docs/mailbox-service/ARCHITECTURE.md 13)."""

from __future__ import annotations

import ast
from pathlib import Path

from .repository_helpers import ROOT

COMMON = "benethos_mailbox_common"
COMMON_SOURCE = ROOT / "packages/mailbox-common/src" / COMMON
# The packages that use the common package.
CONSUMERS = ("mailbox-service", "mailbox-mcp", "mailbox-agents")
PACKAGES = ROOT / "packages"


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
                    if name.startswith(f"{COMMON}.") and name.count(".") > 1:
                        where = path.relative_to(PACKAGES).as_posix()
                        violations.append(f"{where}:{node.lineno} {name}")
    assert not violations, "deeper than a group:\n  " + "\n  ".join(violations)


def _private_common_reads(path: Path) -> list[str]:
    """Where ``path`` reads a name with an underscore of a module of
    ``benethos_mailbox_common``, as ``line name``."""
    tree = ast.parse(path.read_text("utf-8"))
    bound: set[str] = set()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "benethos_mailbox_common"
        ):
            for alias in node.names:
                if _private(alias.name):
                    found.append(f"{node.lineno} {alias.name}")
                bound.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("benethos_mailbox_common"):
                    bound.add(alias.asname or alias.name.split(".")[0])
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in bound
            and _private(node.attr)
        ):
            found.append(f"{node.lineno} {node.value.id}.{node.attr}")
    return found


def test_no_other_package_reads_a_private_name_of_the_common_one() -> None:
    """What the common package keeps to itself stays there: the others,
    their tests, the tests here and the live checks use its public names
    (ARCHITECTURE 13)."""
    common = ROOT / "packages" / "mailbox-common"
    places = [ROOT / "packages", ROOT / "tests", ROOT / "live"]
    violations = [
        f"{path.relative_to(ROOT).as_posix()}:{read}"
        for place in places
        for path in sorted(place.rglob("*.py"))
        if common not in path.parents and ".venv" not in path.parts
        for read in _private_common_reads(path)
    ]
    assert not violations, "a private name of mailbox-common:\n  " + "\n  ".join(
        violations
    )


def test_a_function_of_the_package_exists_once() -> None:
    """No module of the service or the MCP server defines a function of
    the common package again, under its name or with a leading underscore."""
    shared = set().union(*(_functions(p) for p in COMMON_SOURCE.rglob("*.py")))
    violations = []
    for consumer in CONSUMERS:
        source = PACKAGES / consumer / "src"
        for path in sorted(source.rglob("*.py")):
            name = path.relative_to(PACKAGES).as_posix()
            for function in sorted(_functions(path) & shared):
                violations.append(f"{name}: {function}")
    assert not violations, "a copy of a helper:\n  " + "\n  ".join(violations)


def _functions(path: Path) -> set[str]:
    """The functions a module defines at its top level, without a leading
    underscore."""
    tree = ast.parse(path.read_text("utf-8"))
    return {
        node.name.lstrip("_")
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")
