"""PDF pages as PNG images. The only module that imports ``pypdfium2``.

Claude reads images but refuses a PDF handed over as an embedded resource,
so a PDF attachment reaches the model as pictures of its pages. The PNG is
written here with ``zlib``, so no imaging library is needed.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import pypdfium2 as pdfium

from .errors import ToolError

DPI = 150


@dataclass(frozen=True)
class Pages:
    images: list[bytes]  # PNG, one per rendered page
    first: int  # number of the first rendered page, from 1
    total: int  # pages in the document


def render(data: bytes, first: int, count: int, dpi: int = DPI) -> Pages:
    """Pages ``first`` to ``first + count - 1`` as PNG, as far as they exist."""
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise ToolError(f"the attachment is not a readable PDF: {exc}") from None
    try:
        total = len(document)
        if first > total:
            raise ToolError(f"the PDF has {total} pages, there is no page {first}")
        images = []
        for number in range(first, min(first + count, total + 1)):
            page = document[number - 1]
            try:
                bitmap = page.render(scale=dpi / 72, rev_byteorder=True)
                images.append(
                    _png(
                        bytes(bitmap.buffer),
                        bitmap.width,
                        bitmap.height,
                        bitmap.stride,
                        bitmap.n_channels,
                    )
                )
            finally:
                page.close()
        return Pages(images, first, total)
    finally:
        document.close()


def _png(pixels: bytes, width: int, height: int, stride: int, channels: int) -> bytes:
    """An 8-bit RGB or RGBA PNG of rows ``stride`` bytes apart."""
    colour = {3: 2, 4: 6}[channels]
    row = width * channels
    raw = b"".join(
        b"\x00" + pixels[y * stride : y * stride + row] for y in range(height)
    )

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
