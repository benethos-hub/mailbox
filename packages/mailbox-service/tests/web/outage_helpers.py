"""A database that is away, for the tests of what the service answers
then: every call of the repositories a test names fails as the place of
a database server fails while it cannot reach the server."""

from __future__ import annotations

from typing import NoReturn

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.errors import StorageUnavailableError

# Seconds until the next attempt, as the error of the place says.
RETRY = 7
# What failed, for the log alone: never in an answer.
CAUSE = "OperationalError (08006)"


def fail(*args: object, **kwargs: object) -> NoReturn:
    raise StorageUnavailableError(RETRY, CAUSE)


def away(
    services: Services, monkeypatch: pytest.MonkeyPatch, *repositories: str
) -> None:
    """Every method of the repositories ``repositories`` of ``services``
    fails, the users at least: each request asks them first."""
    for name in {"users", *repositories}:
        repository = getattr(services.repositories, name)
        for method in dir(repository):
            if not method.startswith("_") and callable(getattr(repository, method)):
                monkeypatch.setattr(repository, method, fail)


def known_away(services: Services, monkeypatch: pytest.MonkeyPatch) -> None:
    """The store says the database is away, as the place of a server
    does after a failure: without a call to the database."""
    monkeypatch.setattr(
        services.status, "_storage", lambda: StorageUnavailableError(RETRY, CAUSE)
    )
