"""The service's source as the checks of the whole service read it."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = "benethos_mailbox_service"
ROOT = Path(__file__).resolve().parents[1] / "src" / PACKAGE

HELPERS = "common"
# Assemble the app from the layers and may therefore reach anywhere.
ASSEMBLY = {"assembly", "cli", "__main__", "logs"}


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def own_part(module: str) -> str | None:
    """'benethos_mailbox_service.domain.accounts' -> 'domain'."""
    parts = module.split(".")
    if parts[0] != PACKAGE or len(parts) < 2:
        return None
    return parts[1]


def modules() -> list[tuple[str, Path]]:
    return [(module_name(p), p) for p in sorted(ROOT.rglob("*.py"))]


def from_imports(path: Path) -> list[tuple[str, ast.ImportFrom]]:
    """Every ``from ... import`` of this file, its module resolved."""
    module = module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            found.append((name, node))
    return found


def imports(path: Path) -> list[tuple[str, int]]:
    """Every imported module of this file, relative imports resolved."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno) for alias in node.names]
    for name, node in from_imports(path):
        found.append((name, node.lineno))
        # `from . import x` imports a submodule by name, resolve it too.
        if not node.module:
            found += [(f"{name}.{alias.name}", node.lineno) for alias in node.names]
    return found
