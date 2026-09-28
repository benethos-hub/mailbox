"""An activity: something done in the service, and who did it.

One sentence per activity, in the past tense (docs/LOGGING.md section 3):
``<who> <did what> <to which> [from <where>][: <why>]``. A subclass
says the middle part in ``says``, the rest comes from here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from ...data.models import Account, User
from ...errors import MailboxServiceError
from ..access import Access


@dataclass(frozen=True)
class Actor:
    """Who acted: a user, with the name of its token when it came with
    one, and the client address of the request. Or a part of the service
    itself, such as the worker, which has no id."""

    name: str
    user_id: str | None = None
    token: str | None = None
    source: str | None = None

    @classmethod
    def of(cls, access: Access) -> Actor:
        return cls(access.name, access.user_id, access.credential_name, access.source)

    def __str__(self) -> str:
        if self.user_id is None:
            return self.name
        token = f", token {self.token}" if self.token else ""
        return f"{self.name} ({self.user_id}{token})"


SERVICE = Actor("the service")
HOST = Actor("the host")
WORKER = Actor("the worker")
DISPATCHER = Actor("the dispatcher")


def someone(source: str | None) -> Actor:
    """A caller not known yet, e.g. one who failed to sign in."""
    return Actor("someone", source=source)


@dataclass(frozen=True, kw_only=True)
class Activity:
    """One activity. ``name`` is set by each class and stays when the class
    is renamed: the log, an operator's filters and the audit know it
    (docs/LOGGING.md 7.2). ``level`` is its level in the log, ``audited``
    whether the audit of docs/AUDIT.md keeps it. ``at`` is set by the
    recorder."""

    # The module's name in the catalogue: auth, users, ...
    area: ClassVar[str] = ""
    name: ClassVar[str] = ""
    level: ClassVar[int] = logging.INFO
    audited: ClassVar[bool] = False

    by: Actor
    at: datetime | None = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls.area = cls.__module__.rpartition(".")[2]

    @classmethod
    def source(cls) -> str:
        """``activity.<area>.<name>``, the logger it writes to below the
        service's package."""
        return f"activity.{cls.area}.{cls.name}"

    def says(self) -> str:
        """What was done to which record, e.g. ``created user Anna (usr_...)``."""
        raise NotImplementedError

    def why(self) -> str | None:
        """The reason after a colon, when there is one."""
        return None

    def line(self) -> str:
        text = f"{self.by} {self.says()}"
        if self.by.source:
            text += f" from {self.by.source}"
        why = self.why()
        return f"{text}: {why}" if why else text


@dataclass(frozen=True, kw_only=True)
class Failure(Activity):
    """An activity that failed, with its error. One of ours is a warning
    with its message. Anything else the recorder writes as an error, with
    its traceback."""

    level: ClassVar[int] = logging.WARNING

    error: BaseException

    def why(self) -> str | None:
        return reason(self.error)

    @property
    def ours(self) -> bool:
        return isinstance(self.error, MailboxServiceError)


def reason(error: BaseException) -> str:
    """The message of one of our errors, else the kind of the failure."""
    if isinstance(error, MailboxServiceError):
        return error.message
    return type(error).__name__


def account(record: Account) -> str:
    """An account as a line names it: its address and its id."""
    return f"{record.email} ({record.id})"


def user(record: User) -> str:
    """A user as a line names it: its name and its id."""
    return f"{record.name} ({record.id})"


def plural(count: int, word: str) -> str:
    """``1 webhook``, ``2 webhooks``."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
