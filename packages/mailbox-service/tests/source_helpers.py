"""The service's source as the checks of the whole service read it."""

from __future__ import annotations

from pathlib import Path

PACKAGE = "benethos_mailbox_service"
ROOT = Path(__file__).resolve().parents[1] / "src" / PACKAGE

HELPERS = "common"


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
