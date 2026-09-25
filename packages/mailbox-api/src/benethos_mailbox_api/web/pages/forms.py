"""What a submitted form can be wrong about, said in one way."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import ValidationError

from ...errors import MailboxApiError


class FormError(ValueError):
    """What the form holds is not what the domain takes yet. ``message``
    reads like a domain error's, so a page shows either the same way."""

    @property
    def message(self) -> str:
        return str(self)


def first_problem(exc: ValidationError) -> str:
    """The first thing a model refused, as ``field: reason``."""
    problem = exc.errors()[0]
    where = ".".join(str(part) for part in problem["loc"])
    reason = str(problem["msg"]).removeprefix("Value error, ")
    return f"{where}: {reason}" if where else reason


class Failed(Exception):
    """A form did not go through: the browser goes back to ``path`` with
    ``error``. The pages' error handler turns it into the redirect."""

    def __init__(self, path: str, error: str) -> None:
        super().__init__(error)
        self.path = path
        self.error = error


@contextmanager
def failing(path: str, prefix: str = "") -> Iterator[None]:
    """A domain error or a form error inside sends the browser back to
    ``path`` with the message, ``prefix`` in front of it."""
    try:
        yield
    except (MailboxApiError, FormError) as exc:
        raise Failed(path, f"{prefix}{exc.message}") from None
