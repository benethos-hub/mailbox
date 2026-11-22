"""The error ``GatewayUnavailableError``."""

from __future__ import annotations

from .unavailable import UnavailableError

__all__ = ["GatewayUnavailableError"]


class GatewayUnavailableError(UnavailableError):
    """The model gateway did not answer, or answered with a 5xx, 408 or
    429."""

    code = "gateway_unavailable"
