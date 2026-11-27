"""The agent contract: what an agent declares and implements, what it may
reach, and the registry that finds the agents. See
docs/mailbox-agents/concept/agent-contract.md."""

from __future__ import annotations

from .agent import (
    KEYWORD_FORM,
    REVERSED_BY,
    Action,
    ActionRequest,
    Agent,
    Limits,
    Requires,
    Route,
    Shown,
    ShownAction,
    TracePart,
    Trigger,
    state_name,
)
from .context import Context, Items, Model, Reader
from .paths import folder_path, from_top
from .placed import Placed
from .prompts import load_prompt
from .registry import discover, load_agent
from .waiting import is_pattern, waits_for

__all__ = [
    "KEYWORD_FORM",
    "REVERSED_BY",
    "Action",
    "ActionRequest",
    "Agent",
    "Context",
    "Items",
    "Limits",
    "Model",
    "Placed",
    "Reader",
    "Requires",
    "Route",
    "Shown",
    "ShownAction",
    "TracePart",
    "Trigger",
    "discover",
    "folder_path",
    "from_top",
    "is_pattern",
    "load_agent",
    "load_prompt",
    "state_name",
    "waits_for",
]
