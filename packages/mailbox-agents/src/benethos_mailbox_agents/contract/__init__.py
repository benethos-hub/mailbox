"""The agent contract: what an agent declares and implements, what it may
reach, and the registry that finds the agents. See
docs/mailbox-agents/concept/agent-contract.md."""

from __future__ import annotations

from .actions import (
    FORMER_STAGES,
    REVERSED_BY,
    STAGE_ALLOWS,
    Action,
    ActionRequest,
    ForwardForm,
)
from .actor import PASSED_BY, Actor, list_version
from .agent import (
    KEYWORD_FORM,
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
from .classifier import Classifier
from .context import Context, Items, Model, Reader
from .paths import folder_path, from_top
from .placed import Placed
from .prompts import load_prompt
from .registry import discover, load_agent
from .waiting import is_pattern, waits_for

__all__ = [
    "FORMER_STAGES",
    "KEYWORD_FORM",
    "PASSED_BY",
    "REVERSED_BY",
    "STAGE_ALLOWS",
    "Action",
    "Actor",
    "ActionRequest",
    "Agent",
    "ForwardForm",
    "Classifier",
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
    "list_version",
    "load_agent",
    "load_prompt",
    "state_name",
    "waits_for",
]
