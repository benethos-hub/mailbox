"""The activities of the catalogue, read from its package."""

from __future__ import annotations

import importlib
import pkgutil

from benethos_mailbox_service.domain.activity import (
    Activity,
    catalogue,
)


def activities() -> list[type[Activity]]:
    found = []
    for info in pkgutil.iter_modules(catalogue.__path__):
        module = importlib.import_module(f"{catalogue.__name__}.{info.name}")
        found += [
            value
            for value in vars(module).values()
            if isinstance(value, type)
            and issubclass(value, Activity)
            and value.__module__ == module.__name__
        ]
    return found
