"""Roles: named sets of rights a user can hold."""

from __future__ import annotations

from dataclasses import dataclass

from .rights import Grant


@dataclass(frozen=True, slots=True)
class Role:
    """A role's ``service`` rights, bound to no account, and its grants."""

    id: str
    service: tuple[str, ...]
    grants: tuple[Grant, ...]
