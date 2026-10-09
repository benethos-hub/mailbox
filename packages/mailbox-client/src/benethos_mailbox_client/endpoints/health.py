"""Whether the service answers: ``/health``, outside ``/v1`` and open
without a token. The client sends its token there all the same."""

from __future__ import annotations

from ..calls import Call
from ..models import Health


def health() -> Call[Health]:
    return Call(
        "GET",
        "/health",
        lambda found: Health(
            status=str(found["status"]), version=str(found["version"])
        ),
    )
