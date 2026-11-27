"""The profile of an agent: what a process that reads the state file from
outside cannot know, as it does not hold the settings of the worker."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict

__all__ = ["Profile"]


class Profile(BaseModel):
    """The row of the table ``profile``, docs/mailbox-agents/concept/state.md.

    Written by the worker when it starts. ``accounts`` empty means every
    account the service user is granted. No secret, no text of a list and
    no address of the service is in it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str
    instance: str | None
    agent_version: str
    package_version: str
    stage: str
    accounts: tuple[str, ...]
    keyword: str
    poll_seconds: float
    gateway_timeout_seconds: float
    model_alias: str
    prompt_version: str
    started: AwareDatetime
