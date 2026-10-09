"""QR codes on a page: ``segno`` draws them, imported here alone.

A code is an SVG image in a data URI, which the content security policy
takes as an image (``img-src data:``). No inline markup reaches the page.
Dark on white with its quiet zone, so a camera reads it in either theme.
"""

from __future__ import annotations

import segno

# Pixels per module: a code of an otpauth URI is about 200 pixels wide.
SCALE = 5


def data_uri(text: str) -> str:
    """``text`` as a QR code, error correction M, for an ``img`` tag."""
    code = segno.make(text, error="m", micro=False)
    uri: str = code.svg_data_uri(scale=SCALE, dark="#000", light="#fff")
    return uri
