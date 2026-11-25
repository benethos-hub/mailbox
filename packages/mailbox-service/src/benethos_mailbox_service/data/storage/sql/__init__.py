"""The storage spoken through SQLAlchemy Core: the types and what differs
between databases (``dialect``), the tables of the schema (``schema``),
the database the repositories use (``database``), the rows of a table
keyed by ``id`` (``rows``) and the repositories, one module per subject.
The only package that imports ``sqlalchemy``."""

from __future__ import annotations

from .accounts import SqlAccountRepository
from .passkeys import SqlPasskeyRepository
from .passwords import SqlPasswordRepository
from .totp import SqlTotpRepository
from .users import SqlRoleRepository, SqlTokenRepository, SqlUserRepository

__all__ = [
    "SqlAccountRepository",
    "SqlPasskeyRepository",
    "SqlPasswordRepository",
    "SqlRoleRepository",
    "SqlTokenRepository",
    "SqlTotpRepository",
    "SqlUserRepository",
]
