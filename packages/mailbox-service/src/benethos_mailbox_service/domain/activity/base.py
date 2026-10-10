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

from ...data.models import Account, ActivityOutcome, User
from ...errors import MailboxServiceError
from ..rights import Access


@dataclass(frozen=True, slots=True)
class Actor:
    """Who acted: a user, with the name of its token when it came with
    one, and the client address of the request. Or a part of the service
    itself, such as the worker, which has no id. ``credential`` is how it
    came, for the audit: ``token:<id>``, ``password`` for the UI, ``host``
    for a command on the host."""

    name: str
    user_id: str | None = None
    token: str | None = None
    source: str | None = None
    credential: str | None = None

    @classmethod
    def of(cls, access: Access) -> Actor:
        credential = (
            f"token:{access.credential_id}" if access.credential_id else PASSWORD
        )
        return cls(
            access.name,
            access.user_id,
            access.credential_name,
            access.source,
            credential,
        )

    @classmethod
    def signed_in(
        cls, name: str, user_id: str, source: str | None, credential: str = ""
    ) -> Actor:
        """A user who just signed in to the UI: with its password, or with
        a second factor as well, as ``credential`` says."""
        return cls(name, user_id, source=source, credential=credential or PASSWORD)

    def __str__(self) -> str:
        if self.user_id is None:
            return self.name
        token = f", token {self.token}" if self.token else ""
        return f"{self.name} ({self.user_id}{token})"


# How a user of the UI came.
PASSWORD = "password"

SERVICE = Actor("the service")
HOST = Actor("the host", credential="host")
WORKER = Actor("the worker")
DISPATCHER = Actor("the dispatcher")


def someone(source: str | None) -> Actor:
    """A caller not known yet, e.g. one who failed to sign in."""
    return Actor("someone", source=source)


@dataclass(frozen=True, kw_only=True, slots=True)
class Activity:
    """One activity. ``name`` is set by each class and stays when the class
    is renamed: the log, an operator's filters and the audit know it
    (docs/LOGGING.md 7.2). ``level`` is its level in the log, ``audited``
    whether the audit of docs/AUDIT.md keeps it, and ``outcome`` what it
    says there. ``at`` is set by the recorder."""

    # The module's name in the catalogue: auth, users, ...
    area: ClassVar[str] = ""
    name: ClassVar[str] = ""
    level: ClassVar[int] = logging.INFO
    audited: ClassVar[bool] = False
    outcome: ClassVar[ActivityOutcome] = "done"

    by: Actor
    at: datetime | None = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Named: slots=True makes a new class, which a bare super() of
        # Python before 3.13 does not know.
        super(Activity, cls).__init_subclass__(**kwargs)
        cls.area = cls.__module__.rpartition(".")[2]

    @classmethod
    def source(cls) -> str:
        """``activity.<area>.<name>``, the logger it writes to below the
        service's package."""
        return f"activity.{cls.kind()}"

    def says(self) -> str:
        """What was done to which record, e.g. ``created user Anna (usr_...)``."""
        raise NotImplementedError

    def why(self) -> str | None:
        """The reason after a colon, when there is one."""
        return None

    def touched(self) -> str | None:
        """The id of the record the activity is about, for the audit: a
        user, a token, a role, an account or a webhook."""
        return None

    @classmethod
    def kind(cls) -> str:
        """``<area>.<name>``: how the audit names it."""
        return f"{cls.area}.{cls.name}"

    def line(self) -> str:
        text = f"{self.by} {self.says()}"
        if self.by.source:
            text += f" from {self.by.source}"
        return self._with_why(text)

    def detail(self) -> str:
        """The line without who and from where, which the audit keeps
        apart."""
        return self._with_why(self.says())

    def _with_why(self, text: str) -> str:
        why = self.why()
        return f"{text}: {why}" if why else text


@dataclass(frozen=True, kw_only=True, slots=True)
class Failure(Activity):
    """An activity that failed, with its error. One of ours is a warning
    with its message. Anything else the recorder writes as an error, with
    its traceback."""

    level: ClassVar[int] = logging.WARNING
    outcome: ClassVar[ActivityOutcome] = "failed"

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
