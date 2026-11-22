"""The registry: the agents that exist, found as ``agents/<name>/agent.py``.

An agent module has no side effects at import, so finding every agent
imports every agent module and nothing more happens.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import pkgutil

from ..errors import ContractError
from .agent import Agent

__all__ = ["AGENTS_PACKAGE", "discover", "load"]

AGENTS_PACKAGE = __name__.rsplit(".", 2)[0] + ".agents"


def _agent_class(module_name: str) -> type[Agent]:
    module = importlib.import_module(module_name)
    found = [
        value
        for value in vars(module).values()
        if inspect.isclass(value)
        and issubclass(value, Agent)
        and not inspect.isabstract(value)
        and value.__module__ == module.__name__
    ]
    if len(found) != 1:
        raise ContractError(
            f"{module_name} defines {len(found)} agent classes, one is required"
        )
    return found[0]


def discover(package: str = AGENTS_PACKAGE) -> dict[str, type[Agent]]:
    """Every agent below ``package``, by name."""
    root = importlib.import_module(package)
    found: dict[str, type[Agent]] = {}
    for info in pkgutil.iter_modules(root.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = f"{package}.{info.name}.agent"
        if importlib.util.find_spec(module) is None:
            continue  # a package without agent.py is not an agent
        cls = _agent_class(module)
        cls.validate_definition()
        found[cls.name] = cls
    return dict(sorted(found.items()))


def load(name: str, package: str = AGENTS_PACKAGE) -> type[Agent]:
    """The agent called ``name``, or a :class:`ContractError` naming those
    that exist."""
    agents = discover(package)
    if name not in agents:
        raise ContractError(
            f"no agent {name!r}, there are: {', '.join(agents) or 'none'}"
        )
    return agents[name]
