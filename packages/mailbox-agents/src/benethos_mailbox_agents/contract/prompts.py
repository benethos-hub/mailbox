"""System prompts as Markdown files beside an agent, each with a version.

A prompt lives in ``agents/<name>/prompts/<prompt>.<version>.md``. The
version is part of the name, so a changed prompt is a new file and a new
version, and the step runner takes it as new work. See
docs/mailbox-agents/concept/agent-contract.md.
"""

from __future__ import annotations

from importlib import resources

from ..errors import ContractError

__all__ = ["load_prompt"]


def load_prompt(package: str, name: str, version: str) -> str:
    """The text of ``prompts/<name>.<version>.md`` in ``package``."""
    found = resources.files(package).joinpath("prompts", f"{name}.{version}.md")
    try:
        return found.read_text(encoding="utf-8")
    except OSError:
        raise ContractError(f"{package} has no prompt {name}.{version}.md") from None
