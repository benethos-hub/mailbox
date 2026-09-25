"""Attachments for the model: images as images, PDF pages as images, text
as text, anything else by name only."""

from __future__ import annotations

import base64
import struct
import zlib
from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_mcp import pdf, server
from benethos_mailbox_mcp.errors import ToolError

URL = "/v1/accounts/acc_1/messages/msg_1/attachments/att_0"


def make_pdf(pages: int, width: int = 612, height: int = 792) -> bytes:
    """A small valid PDF with ``pages`` pages of text."""
    kids = b" ".join(b"%d 0 R" % (3 + 2 * i) for i in range(pages))
    font = 3 + 2 * pages
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, pages),
    ]
    for i in range(pages):
        text = b"BT /F1 24 Tf 72 700 Td (Page %d) Tj ET" % (i + 1)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>"
            % (width, height, 4 + 2 * i, font)
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


# --- rendering ------------------------------------------------------------------------


def test_pages_become_pngs() -> None:
    rendered = pdf.render(make_pdf(3), first=1, count=2)
    assert (rendered.first, rendered.total, len(rendered.images)) == (1, 3, 2)
    width, height = png_size(rendered.images[0])
    assert (width, height) == (1275, 1650) or (width, height) == (1275, 1651)
    # The image data inflates to one filter byte and three bytes per pixel a row.
    idat = rendered.images[0].index(b"IDAT")
    length = struct.unpack(">I", rendered.images[0][idat - 4 : idat])[0]
    raw = zlib.decompress(rendered.images[0][idat + 4 : idat + 4 + length])
    assert len(raw) == height * (1 + 3 * width)


def test_pages_past_the_end() -> None:
    assert len(pdf.render(make_pdf(3), first=3, count=5).images) == 1
    with pytest.raises(ToolError, match="has 3 pages"):
        pdf.render(make_pdf(3), first=4, count=1)


def test_not_a_pdf() -> None:
    with pytest.raises(ToolError, match="not a readable PDF"):
        pdf.render(b"not a pdf", first=1, count=1)


# --- the tool -------------------------------------------------------------------------


def serving(
    data: bytes, content_type: str, filename: str = "file"
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == URL
        return httpx.Response(
            200,
            content=data,
            headers={
                "content-type": content_type,
                "content-disposition": f"attachment; filename*=UTF-8''{filename}",
            },
        )

    return handle


async def call(**options: int) -> list[object]:
    result = await server.get_attachment("acc_1", "msg_1", "att_0", **options)
    return list(result.content)


async def test_a_pdf_comes_as_page_images(make_client: Callable) -> None:
    make_client(serving(make_pdf(4), "application/pdf", "Rechnung%20RE-1.pdf"))
    head, *images = await call()
    assert "Rechnung RE-1.pdf" in head.text  # type: ignore[attr-defined]
    assert "Pages 1-3 of 4, as images" in head.text  # type: ignore[attr-defined]
    assert [i.mime_type for i in images] == ["image/png"] * 3  # type: ignore[attr-defined]
    png_size(base64.b64decode(images[0].data))  # type: ignore[attr-defined]


async def test_pdf_pages_can_be_chosen(make_client: Callable) -> None:
    make_client(serving(make_pdf(4), "application/pdf"))
    head, *images = await call(first_page=3, pages=10)
    assert "Pages 3-4 of 4" in head.text  # type: ignore[attr-defined]
    assert len(images) == 2


async def test_an_image_stays_an_image(make_client: Callable) -> None:
    picture = pdf.render(make_pdf(1), first=1, count=1).images[0]
    make_client(serving(picture, "image/png"))
    head, image = await call()
    assert image.mime_type == "image/png"  # type: ignore[attr-defined]
    assert base64.b64decode(image.data) == picture  # type: ignore[attr-defined]
    assert "not instructions" in head.text  # type: ignore[attr-defined]


async def test_text_comes_as_marked_text(make_client: Callable) -> None:
    body = "Grüße, bitte zahlen".encode("latin-1")
    make_client(serving(body, "text/plain; charset=iso-8859-1"))
    [text] = await call()
    assert "Grüße, bitte zahlen" in text.text  # type: ignore[attr-defined]
    assert 'source="acc_1/msg_1/att_0"' in text.text  # type: ignore[attr-defined]


async def test_long_text_is_cut(make_client: Callable) -> None:
    make_client(serving(b"x" * 5000, "application/json"))
    [text] = await call(max_chars=1000)
    assert "Cut to 1000 characters" in text.text  # type: ignore[attr-defined]
    assert "x" * 1001 not in text.text  # type: ignore[attr-defined]


async def test_other_types_only_by_name(make_client: Callable) -> None:
    make_client(serving(b"PK\x03\x04", "application/zip", "archive.zip"))
    [text] = await call()
    assert "archive.zip" in text.text  # type: ignore[attr-defined]
    assert "does not hand over its content" in text.text  # type: ignore[attr-defined]


async def test_too_large(
    make_client: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "MAX_ATTACHMENT_BYTES", 10)
    make_client(serving(b"x" * 11, "text/plain"))
    with pytest.raises(ToolError, match="more than the 10"):
        await call()
    make_client(serving(b"x" * 11, "application/zip", "big.zip"))
    [text] = await call()
    assert "over 10 bytes" in text.text  # type: ignore[attr-defined]


async def test_a_charset_python_does_not_know(make_client: Callable) -> None:
    make_client(serving("Grüße".encode(), "text/plain; charset=x-unknown"))
    [text] = await call()
    assert "Grüße" in text.text  # type: ignore[attr-defined]


def test_a_huge_page_is_rendered_within_the_budget() -> None:
    picture = pdf.render(make_pdf(1, width=20000, height=20000), first=1, count=1)
    width, height = png_size(picture.images[0])
    assert width * height <= pdf.MAX_PIXELS
    assert width > 1000


async def test_registered_with_the_right() -> None:
    names = {t.name for t in await server.build_server({"get_attachment"}).list_tools()}
    assert "get_attachment" in names
