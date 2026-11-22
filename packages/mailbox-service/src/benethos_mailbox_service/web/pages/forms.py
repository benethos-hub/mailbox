"""What a submitted form can be wrong about, said in one way."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, TypeVar

from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from benethos_mailbox_common.log import redact

from ...errors import MailboxServiceError

# A refused form comes back with this status, what was typed, the reason.
REFUSED = 400


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


def text_of(form: Mapping[str, object], key: str, *, strip: bool = True) -> str:
    """A field of a submitted form as text, empty when it is not there,
    without the spaces around it unless ``strip`` is false."""
    value = str(form.get(key) or "")
    return value.strip() if strip else value


M = TypeVar("M", bound=BaseModel)


def model_of(
    model: type[M],
    fields: Mapping[str, Any],
    *,
    error: type[FormError] = FormError,
    message: str | None = None,
) -> M:
    """``model`` from what a form holds. What it refuses raises ``error``,
    with ``message`` or else the first problem."""
    try:
        return model.model_validate(fields)
    except ValidationError as exc:
        raise error(message or first_problem(exc)) from None


# The page of a form again, with what was typed and the reason it was
# refused.
Again = Callable[[str], Response | Awaitable[Response]]


class FormFailedError(Exception):
    """A form did not go through. With ``again`` its page is shown again
    with what was typed and ``error``, else the browser goes back to
    ``path`` with ``error``, and with ``dialog`` that page opens the
    dialog of this id again, the error in it. ``first``: the method of
    the second factor that page shows first. The pages' error handler
    does either."""

    def __init__(
        self,
        path: str,
        error: str,
        again: Again | None = None,
        dialog: str | None = None,
        first: str | None = None,
    ) -> None:
        super().__init__(error)
        self.path = path
        self.error = error
        self.again = again
        self.dialog = dialog
        self.first = first


@contextmanager
def failing(
    path: str,
    prefix: str = "",
    again: Again | None = None,
    dialog: str | None = None,
    first: str | None = None,
) -> Iterator[None]:
    """A domain error or a form error inside sends the browser back to
    ``path`` with the message, ``prefix`` in front of it, or shows the
    form's page ``again``: an editor keeps what was typed (docs/mailbox-service/UI.md
    4.7). A form sent from a dialog names it as ``dialog``: the page opens it
    again with the message. A form with a second factor names the
    method it came by as ``first`` (``first_way``): the page shows it
    first again."""
    try:
        yield
    except (MailboxServiceError, FormError) as exc:
        raise FormFailedError(
            path, redact.redact(f"{prefix}{exc.message}"), again, dialog, first
        ) from None
