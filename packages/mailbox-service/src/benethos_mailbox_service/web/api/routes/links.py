"""A link to an attachment, used: the one route under ``/v1`` without a
token. Its secret is the credential, so the access log names its path
masked (``web.urls.logged_path``), and every refusal is the same `404`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ...responses import download
from ...urls import client_address
from ..deps import Links
from ..errors import LINK_ERRORS

router = APIRouter(prefix="/links", tags=["links"])


@router.get(
    "/{secret}",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "Content"},
        **LINK_ERRORS,
    },
)
async def get_linked_attachment(
    secret: str, request: Request, links: Links
) -> Response:
    """The attachment a link from `share_attachment` hands out, once. No
    Authorization: whoever holds the URL fetches it. A link unknown,
    used, ended or no longer allowed answers the same `404`, and so does
    an address that failed too often. Where the mail server fails, the
    link holds and the answer is `502 provider_unavailable`: try again."""
    found = await links.redeem(secret, client_address(request))
    response = download(found.data, found.filename or "attachment", found.content_type)
    # A credential in a URL: nothing on the way keeps the answer.
    response.headers["Cache-Control"] = "no-store"
    return response
