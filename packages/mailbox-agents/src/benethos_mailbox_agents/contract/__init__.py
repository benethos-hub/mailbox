"""The agent contract: what an agent declares and implements, what it may
reach, and the registry that finds the agents. See
docs/mailbox-agents/concept/agent-contract.md."""

from __future__ import annotations

from .agent import (
    REVERSED_BY,
    Action,
    ActionRequest,
    Agent,
    Limits,
    Requires,
    Route,
    Shown,
    ShownAction,
    Trigger,
)
from .context import Context, Items, Model, Reader
from .prompts import load_prompt
from .registry import discover, load_agent

__all__ = [
    "REVERSED_BY",
    "Action",
    "ActionRequest",
    "Agent",
    "Context",
    "Items",
    "Limits",
    "Model",
    "Reader",
    "Requires",
    "Route",
    "Shown",
    "ShownAction",
    "Trigger",
    "discover",
    "load_agent",
    "load_prompt",
]
