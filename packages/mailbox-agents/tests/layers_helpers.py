"""What the tests of the layers read from the source: the modules of
the package, the layer of each, and what each imports, a relative
import resolved."""

from __future__ import annotations

import ast
from pathlib import Path

import benethos_mailbox_agents

PACKAGE = "benethos_mailbox_agents"
SOURCE = Path(benethos_mailbox_agents.__file__).parent


def layer(module: str) -> str:
    """``benethos_mailbox_agents.store.store`` is in the layer ``store``."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def module_from(path: Path, node: ast.ImportFrom) -> str:
    """The module ``node`` in ``path`` imports from, a relative one resolved."""
    if not node.level:
        return node.module or ""
    relative = path.relative_to(SOURCE).with_suffix("").parts
    base = [PACKAGE, *relative][:-1]
    anchor = base[: len(base) - (node.level - 1)]
    return ".".join([*anchor, *([node.module] if node.module else [])])


def imports_of(path: Path) -> list[tuple[str, int]]:
    """Every module of this package that ``path`` imports, with its line."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            module = module_from(path, node)
            if module != PACKAGE and not module.startswith(f"{PACKAGE}."):
                continue
            if module == PACKAGE:
                found += [
                    (f"{module}.{alias.name}", node.lineno) for alias in node.names
                ]
            else:
                found.append((module, node.lineno))
        elif isinstance(node, ast.Import):
            found += [
                (alias.name, node.lineno)
                for alias in node.names
                if alias.name.startswith(f"{PACKAGE}.")
            ]
    return found


def modules() -> list[Path]:
    return sorted(SOURCE.rglob("*.py"))


def layer_of(path: Path) -> str:
    return path.relative_to(SOURCE).parts[0].removesuffix(".py")


def third_party(path: Path) -> set[str]:
    """The top-level names of what ``path`` imports from outside the package."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
    return found
