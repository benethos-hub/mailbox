"""A script of the repository, which is no package, loaded as a module."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def script_module(name: str, path: Path) -> ModuleType:
    """The script at ``path``, run once as the module ``name``."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
