"""Make the PNG files of ``brand/`` from ``brand/icon.svg``, and those of
``architecture/`` from ``architecture/architecture.html``.

    uv run python assets/mailbox-agents/build.py
        all of them
    uv run python assets/mailbox-agents/build.py --icon
        brand/icon.png, 512 by 512
    uv run python assets/mailbox-agents/build.py --diagram
        architecture/architecture.png and architecture-dark.png

All are rendered with a headless Chromium browser (Chrome, Edge or
Chromium). Export them again whenever ``icon.svg`` changes, and the
diagram whenever its page changes as well, and commit them with it.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Mapping
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
ICON_SOURCE = ASSETS / "brand/icon.svg"
ICON = ASSETS / "brand/icon.png"
ICON_SIZE = (512, 512)
DIAGRAM_SOURCE = ASSETS / "architecture/architecture.html"
# The size of the page in CSS pixels, drawn at twice that.
DIAGRAM_SIZE = (1430, 776)
DIAGRAM_SCALE = 2
# Each image and the fragment that picks its colours on the page.
DIAGRAMS = {
    ASSETS / "architecture/architecture.png": "",
    ASSETS / "architecture/architecture-dark.png": "#dark",
}

_ROOT_SIZE = re.compile(r'^(<svg [^>]*?)width="([\d.]+)" height="([\d.]+)"')


def placed(svg: str, size: int) -> str:
    """The icon in the middle of a square of ``size``, as high as it."""
    found = _ROOT_SIZE.match(svg)
    if not found:
        raise ValueError("the icon names no width and height")
    width = size * float(found[2]) / float(found[3])
    inner = (
        f'{found[1]}x="{(size - width) / 2:g}" y="0" width="{width:g}" '
        f'height="{size}"' + svg[found.end() :]
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" '
        f'height="{size}" viewBox="0 0 {size} {size}">\n{inner}</svg>\n'
    )


_BROWSERS = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "chrome",
    "msedge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def _browser() -> str:
    for name in _BROWSERS:
        found = shutil.which(name) or (name if Path(name).is_file() else None)
        if found:
            return found
    raise RuntimeError("no Chromium browser found: Chrome, Edge or Chromium")


def _capture(
    address: str,
    target: Path,
    size: tuple[int, int],
    *,
    transparent: bool = False,
    scale: int = 1,
) -> None:
    """Render the page at an address as a PNG with a headless browser, of
    ``scale`` pixels for each of its own. A transparent page keeps its
    alpha channel instead of the browser's white. The browser writes into
    a folder of its own first: a browser that ends well and writes nothing
    raises, and the PNG there before stays untouched."""
    width, height = size
    background = ["--default-background-color=00000000"] if transparent else []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        shot = Path(profile) / "screenshot.png"
        subprocess.run(
            [
                _browser(),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                *background,
                f"--force-device-scale-factor={scale}",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
                f"--screenshot={shot}",
                address,
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        if not shot.is_file() or shot.stat().st_size == 0:
            raise RuntimeError(f"the browser wrote no screenshot for {target.name}")
        shutil.move(shot, target)


def _screenshot(
    page: str,
    name: str,
    target: Path,
    size: tuple[int, int],
    *,
    transparent: bool,
) -> None:
    """Render a page given as text, from a file of that name."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        source = Path(folder) / name
        source.write_text(page, "utf-8")
        _capture(source.as_uri(), target, size, transparent=transparent)


def stamped(png: bytes, sources: Mapping[str, str]) -> bytes:
    """``png`` with a text chunk after its header for each source it was
    rendered from, by name, naming the hash of its text, any such chunk
    before replaced. So a change of a source that leaves the pixels as
    they were, such as the title of the SVG, still changes the PNG, and
    the PNG is never older than its sources, as the brand check of the
    organisation asks."""
    signature, header_end = b"\x89PNG\r\n\x1a\n", 8 + 4 + 4 + 13 + 4
    if not png.startswith(signature) or png[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    chunks = b"".join(_stamp(name, text) for name, text in sources.items())
    rest, position = png[header_end:], 0
    kept: list[bytes] = []
    while position < len(rest):
        end = position + 12
        if end <= len(rest):
            (length,) = struct.unpack(">I", rest[position : position + 4])
            end += length
        if end > len(rest):
            raise ValueError("a chunk of the PNG is cut short")
        piece = rest[position:end]
        if not (piece[4:8] == b"tEXt" and piece[8:].startswith(b"Source\0")):
            kept.append(piece)
        position = end
        if piece[4:8] == b"IEND":
            break
    if position != len(rest) or not kept or kept[-1][4:8] != b"IEND":
        raise ValueError("the PNG does not end with its IEND chunk")
    return png[:header_end] + chunks + b"".join(kept)


def _stamp(name: str, text: str) -> bytes:
    """The text chunk that names the hash of the source ``name``."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    data = b"Source\0" + f"{name} sha256:{digest}".encode("ascii")
    return (
        struct.pack(">I", len(data))
        + b"tEXt"
        + data
        + struct.pack(">I", zlib.crc32(b"tEXt" + data))
    )


def render_icon() -> None:
    svg = ICON_SOURCE.read_text("utf-8")
    _screenshot(
        placed(svg, ICON_SIZE[0]), "icon.svg", ICON, ICON_SIZE, transparent=True
    )
    ICON.write_bytes(stamped(ICON.read_bytes(), {ICON_SOURCE.name: svg}))


def render_diagram() -> None:
    """The architecture diagram, light and dark. The page stays where it
    is, as it takes the icon from beside it, and both are its sources."""
    sources = {
        DIAGRAM_SOURCE.name: DIAGRAM_SOURCE.read_text("utf-8"),
        ICON_SOURCE.name: ICON_SOURCE.read_text("utf-8"),
    }
    for target, fragment in DIAGRAMS.items():
        _capture(
            DIAGRAM_SOURCE.as_uri() + fragment,
            target,
            DIAGRAM_SIZE,
            scale=DIAGRAM_SCALE,
        )
        target.write_bytes(stamped(target.read_bytes(), sources))


def main(arguments: list[str]) -> int:
    if arguments not in ([], ["--icon"], ["--diagram"]):
        print("usage: build.py [--icon | --diagram]", file=sys.stderr)
        return 2
    if arguments in ([], ["--icon"]):
        render_icon()
    if arguments in ([], ["--diagram"]):
        render_diagram()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
