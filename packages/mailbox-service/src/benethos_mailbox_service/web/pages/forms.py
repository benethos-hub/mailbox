"""What a submitted form can be wrong about, said in one way."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from fastapi.responses import Response
from pydantic import ValidationError

from ...common.redact import redact
from ...errors import MailboxServiceError


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


# The page of a form again, with what was typed and the reason it was
# refused.
Again = Callable[[str], Response | Awaitable[Response]]


class Failed(Exception):
    """A form did not go through. With ``again`` its page is shown again
    with what was typed and ``error``, else the browser goes back to
    ``path`` with ``error``. The pages' error handler does either."""

    def __init__(self, path: str, error: str, again: Again | None = None) -> None:
        super().__init__(error)
        self.path = path
        self.error = error
        self.again = again


@contextmanager
def failing(path: str, prefix: str = "", again: Again | None = None) -> Iterator[None]:
    """A domain error or a form error inside sends the browser back to
    ``path`` with the message, ``prefix`` in front of it, or shows the
    form's page ``again``: an editor keeps what was typed (docs/UI.md 4.7)."""
    try:
        yield
    except (MailboxServiceError, FormError) as exc:
        raise Failed(path, redact(f"{prefix}{exc.message}"), again) from None
