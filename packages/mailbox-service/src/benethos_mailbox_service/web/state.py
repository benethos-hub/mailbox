"""What the app keeps on ``app.state``, read with its type.

Starlette's ``State`` takes any attribute and answers ``Any``. Each one
is read here and nowhere else, so its type is said once. ``assembly.web``
puts the settings and the services there, ``install`` of ``web`` and of
``pages`` the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.applications import Starlette

    from ..config import Settings
    from .limits import RequestLimits
    from .pages.session import SessionStore
    from .services import Services


def app_settings(app: Starlette) -> Settings:
    settings: Settings = app.state.settings
    return settings


def app_services(app: Starlette) -> Services:
    services: Services = app.state.services
    return services


def app_limits(app: Starlette) -> RequestLimits:
    limits: RequestLimits = app.state.request_limits
    return limits


def app_sessions(app: Starlette) -> SessionStore:
    """The sessions of the configuration UI."""
    store: SessionStore = app.state.ui_sessions
    return store
