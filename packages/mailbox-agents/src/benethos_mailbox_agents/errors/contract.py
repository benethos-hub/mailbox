"""The error ``ContractError``."""

from __future__ import annotations

from .base import MailboxAgentError

__all__ = ["ContractError"]


class ContractError(MailboxAgentError):
    """An agent class breaks the contract of
    docs/mailbox-agents/concept/agent-contract.md, or the registry cannot find the agent
    named."""

    code = "contract"
