"""Responses both front ends build the same way."""

from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import Response


def download(data: bytes, filename: str, media_type: str) -> Response:
    """Bytes to save as a file, never rendered in the browser."""
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
