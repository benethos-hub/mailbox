"""The path of a folder as a list of an agent names it: names between
``/``, and every folder above it. The runtime checks a path again before
it acts on it."""

from __future__ import annotations

__all__ = ["folder_path", "from_top"]


def folder_path(value: str) -> str:
    """``value`` when it is names between /, none empty, . or .., else a
    ValueError."""
    parts = value.split("/")
    if any(not p.strip() or p in (".", "..") or p != p.strip() for p in parts):
        raise ValueError("a folder is names between /, none empty, . or ..")
    return value


def from_top(path: str) -> tuple[str, ...]:
    """``path`` and every folder above it, the top first."""
    parts = path.split("/")
    return tuple("/".join(parts[: i + 1]) for i in range(len(parts)))
