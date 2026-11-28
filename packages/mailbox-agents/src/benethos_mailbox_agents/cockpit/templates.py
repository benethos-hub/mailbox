"""The templates of the cockpit: the Jinja2 environment, its filters and
``render``. The only module of the cockpit that imports ``jinja2``.

Everything a page shows is escaped as HTML, and no template marks a text
as safe. Formatting happens in the filters here, never in a template.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jinja2
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import __version__

__all__ = ["STATIC_DIR", "TEMPLATE_DIR", "render"]

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"
MISSING = "—"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
# A typo in a template raises instead of rendering an empty cell.
templates.env.undefined = jinja2.StrictUndefined


def when(value: datetime | None) -> str:
    """A time to the minute, in UTC, as the state files keep it."""
    if value is None:
        return MISSING
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def or_missing(value: Any) -> Any:
    return MISSING if value is None or value == "" else value


def found(value: bool | None) -> str:
    """Whether a quote was found in the mail, as the page of a message says
    it."""
    if value is None:
        return "not checked"
    return "found" if value else "not found"


templates.env.filters.update(when=when, or_missing=or_missing, found=found)
templates.env.globals.update(APP_NAME="Mailbox agents", VERSION=__version__)


def render(
    request: Request, template: str, *, status_code: int = 200, **context: Any
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, template, context, status_code=status_code
    )
