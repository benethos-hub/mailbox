"""Make the shipped images from the sources in ``brand/``.

``uv run python assets/build.py`` writes them anew, ``--check`` only
names the ones that differ from what it would write. The sources stay
as they came, with their C2PA manifest. What is made from them goes
without it:

- the icon of the configuration UI, its sidebar and favicon, from the
  3D icon.
- the logo above the sign-in card, from the 3D logo, and for dark
  mode the same with a light word mark.
- ``brand/social-preview.png``, the image GitHub shows when the
  repository is linked: the 3D logo, what the project is and the
  providers it reaches, the 3D icon faint behind. ``--social`` renders it with
  a Chromium browser (Chrome, Edge or Chromium), which ``--check``
  cannot repeat byte for byte. It goes up by hand, under Settings,
  General, Social preview.
- ``brand/icon.png``, the 3D icon at 512 by 512 on no background, for
  the MCP Registry and the Claude Desktop bundle. ``--icon`` renders it
  the same way.
- ``architecture/architecture.png`` and ``architecture-dark.png``, the
  diagram of the README, from ``architecture/architecture.html``.
  ``--diagram`` renders both the same way, at twice the size for sharp
  text.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
REPOSITORY = ASSETS.parent
STATIC = (
    REPOSITORY
    / "packages/mailbox-service/src/benethos_mailbox_service/web/pages/static"
)

# The C2PA manifest and its namespace: provenance of the source only.
_MANIFEST = re.compile(r"<metadata>.*?</metadata>\n?", re.S)
_NAMESPACE = ' xmlns:c2pa="http://c2pa.org/manifest"'


def plain(svg: str) -> str:
    """The image without its manifest."""
    text, count = _MANIFEST.subn("", svg)
    if count != 1:
        raise ValueError(f"expected one manifest, found {count}")
    return text.replace(_NAMESPACE, "")


# The word mark of the 3D logo in dark mode: its face, the gradient
# "word", in light blues, and its depth, the path drawn 2 below the
# face, in the blue of the icon. The icon keeps its colours.
_LIGHT_WORD = (
    (
        re.compile(
            r'(<linearGradient id="word"[^>]*><stop offset="0" stop-color=")'
            r'#4A78F0("/><stop offset=".55" stop-color=")#2A50D2("/>'
            r'<stop offset="1" stop-color=")#1A369F(")'
        ),
        r"\g<1>#DBEAFE\g<2>#BFDBFE\g<3>#93C5FD\g<4>",
    ),
    (
        re.compile(
            r'(<path transform="translate\(230,133\)" d="[^"]*" fill=")#132E86(")'
        ),
        r"\g<1>#1D4ED8\g<2>",
    ),
)


def light_word(svg: str) -> str:
    """The 3D logo with a light word mark, for a dark page."""
    text = plain(svg)
    for pattern, replacement in _LIGHT_WORD:
        text, count = pattern.subn(replacement, text)
        if count != 1:
            raise ValueError(f"expected {pattern.pattern} once, found {count}")
    return text


# What is made, from which source, and how.
BUILT: dict[Path, tuple[Path, Callable[[str], str]]] = {
    STATIC / "img/icon.svg": (ASSETS / "brand/icon.svg", plain),
    STATIC / "img/logo.svg": (ASSETS / "brand/logo.svg", plain),
    STATIC / "img/logo-dark.svg": (ASSETS / "brand/logo.svg", light_word),
}


def _made(source: Path, make: Callable[[str], str]) -> bytes:
    return make(source.read_text("utf-8")).encode("utf-8")


def stale() -> list[Path]:
    """The made images that differ from what their source makes."""
    return [
        target
        for target, (source, make) in BUILT.items()
        if not target.exists() or target.read_bytes() != _made(source, make)
    ]


def build() -> None:
    for target, (source, make) in BUILT.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_made(source, make))


# --- the social preview ---------------------------------------------------

SOCIAL = ASSETS / "brand/social-preview.png"
SOCIAL_SOURCE = ASSETS / "brand/logo.svg"
SOCIAL_MARK = ASSETS / "brand/icon.svg"
# GitHub's size. It may crop the edges, so the content keeps 96 pixels
# away from them.
SOCIAL_SIZE = (1280, 640)
_ROOT_SIZE = re.compile(r'^(<svg [^>]*?)width="([\d.]+)" height="([\d.]+)"')
# What the page says, from the README's first lines.
SOCIAL_TITLE = "One REST API for all your mailboxes"
SOCIAL_LINE = "Python client &middot; MCP server for AI agents &middot; self-hosted"
SOCIAL_PROVIDERS = ("IMAP", "JMAP", "POP3", "Gmail", "Microsoft 365", "Outlook.com")
SOCIAL_ADDRESS = "github.com/benethos-hub/mailbox"

_SOCIAL_STYLE = """
  html, body { margin: 0; width: 1280px; height: 640px; overflow: hidden; }
  body {
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    background:
      radial-gradient(circle at 88% 18%, rgba(51,95,219,.16) 0,
        rgba(51,95,219,0) 38%),
      radial-gradient(circle at 78% 92%, rgba(22,60,168,.12) 0,
        rgba(22,60,168,0) 42%),
      linear-gradient(135deg, #FBFCFF 0%, #EEF3FD 55%, #E3ECFB 100%);
    position: relative;
  }
  .grid {
    position: absolute; inset: 0;
    background-image: radial-gradient(rgba(22,60,168,.13) 1.2px,
      transparent 1.2px);
    background-size: 26px 26px;
    -webkit-mask-image: linear-gradient(90deg, transparent 35%, #000 100%);
  }
  .mark {
    position: absolute; right: -150px; top: 80px; width: 540px;
    opacity: .08; transform: rotate(-8deg);
  }
  .mark svg { width: 100%; height: auto; }
  .lines { position: absolute; left: 0; top: 0; }
  .content { position: absolute; left: 96px; top: 92px; right: 96px; }
  .logo svg { width: 520px; height: auto; display: block; }
  h1 {
    margin: 46px 0 0; font-size: 50px; line-height: 1.1; font-weight: 700;
    color: #0F2A76; letter-spacing: -.5px;
  }
  p { margin: 16px 0 0; font-size: 27px; color: #335FDB; font-weight: 500; }
  .chips { margin-top: 40px; display: flex; gap: 12px; flex-wrap: wrap; }
  .chip {
    font-size: 20px; font-weight: 600; color: #163CA8;
    background: rgba(255,255,255,.85); border: 1.5px solid #C9D8F5;
    border-radius: 999px; padding: 8px 20px;
    box-shadow: 0 2px 6px rgba(22,60,168,.08);
  }
  .foot {
    position: absolute; left: 96px; bottom: 44px; font-size: 20px;
    color: #5B6B8C; letter-spacing: .2px;
  }
"""


# Flowing lines from the left edge that fade out towards the middle: the
# height where each starts, how far it swings, its stroke width and the
# radius of the half circle it starts at.
_SOCIAL_LINES = (
    (70, 70, 1.6, 5),
    (150, -50, 2.4, 9),
    (235, 80, 1.2, 4),
    (320, -70, 2.0, 7),
    (405, 60, 1.4, 4.5),
    (490, -60, 2.2, 11),
    (575, 50, 1.2, 5.5),
)


def _social_lines() -> str:
    """The lines as an SVG over the whole page, fading out to the right.
    Each starts at a half circle whose straight side lies on the left
    edge, from the top of its arc."""
    paths = "".join(
        f'<path d="M {r} {y} C 200 {y}, 340 {y + swing}, '
        f'560 {y + swing} S 780 {y + swing * 0.3:g}, 900 {y}" '
        f'stroke-width="{width}"/>'
        for y, swing, width, r in _SOCIAL_LINES
    )
    starts = "".join(
        f'<path d="M 0 {y - r} A {r} {r} 0 0 1 0 {y + r} Z"/>'
        for y, _, _, r in _SOCIAL_LINES
    )
    return (
        '<svg class="lines" width="1280" height="640" viewBox="0 0 1280 640">'
        '<defs><linearGradient id="fade" gradientUnits="userSpaceOnUse" '
        'x1="0" y1="0" x2="900" y2="0">'
        '<stop offset="0" stop-color="#335FDB" stop-opacity=".34"/>'
        '<stop offset=".55" stop-color="#335FDB" stop-opacity=".12"/>'
        '<stop offset="1" stop-color="#335FDB" stop-opacity="0"/>'
        "</linearGradient></defs>"
        f'<g fill="none" stroke="url(#fade)" stroke-linecap="round">{paths}</g>'
        f'<g fill="#335FDB" fill-opacity=".30">{starts}</g>'
        "</svg>"
    )


def social(logo: str, mark: str) -> str:
    """The page of the social preview: the 3D logo, what the project is,
    the providers it reaches and where it lives, on a light blue ground
    with flowing lines from the left and the 3D icon large and faint at
    the right."""
    chips = "".join(f'<span class="chip">{p}</span>' for p in SOCIAL_PROVIDERS)
    return (
        '<!doctype html>\n<html><head><meta charset="utf-8">'
        f"<style>{_SOCIAL_STYLE}</style></head>\n<body>\n"
        '<div class="grid"></div>\n'
        f"{_social_lines()}\n"
        f'<div class="mark">{plain(mark)}</div>\n'
        '<div class="content">\n'
        f'<div class="logo">{plain(logo)}</div>\n'
        f"<h1>{SOCIAL_TITLE}</h1>\n<p>{SOCIAL_LINE}</p>\n"
        f'<div class="chips">{chips}</div>\n</div>\n'
        f'<div class="foot">{SOCIAL_ADDRESS}</div>\n</body></html>\n'
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


def _screenshot(
    address: str,
    target: Path,
    size: tuple[int, int],
    scale: int = 1,
    transparent: bool = False,
) -> None:
    """Render a page as a PNG with a headless browser. A transparent page
    keeps its alpha channel instead of the browser's white."""
    width, height = size
    background = ["--default-background-color=00000000"] if transparent else []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        subprocess.run(
            [
                _browser(),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                *background,
                f"--force-device-scale-factor={scale}",
                f"--user-data-dir={Path(folder) / 'profile'}",
                f"--window-size={width},{height}",
                f"--screenshot={target}",
                address,
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )


def render_social() -> None:
    """Render the social preview as a PNG."""
    logo = SOCIAL_SOURCE.read_text("utf-8")
    mark = SOCIAL_MARK.read_text("utf-8")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        page = Path(folder) / "social-preview.html"
        page.write_text(social(logo, mark), "utf-8")
        _screenshot(page.as_uri(), SOCIAL, SOCIAL_SIZE)


# --- the icon as PNG ------------------------------------------------------

# For whom an SVG is not enough: the MCP Registry and the Claude Desktop
# bundle of the MCP server.
ICON = ASSETS / "brand/icon.png"
ICON_SOURCE = ASSETS / "brand/icon.svg"
ICON_SIZE = (512, 512)


def icon(svg: str) -> str:
    """The 3D icon in the middle of a square page, as high as the page,
    on no background."""
    drawn = plain(svg)
    found = _ROOT_SIZE.match(drawn)
    if not found:
        raise ValueError("the icon names no width and height")
    size, _ = ICON_SIZE
    width = size * float(found[2]) / float(found[3])
    placed = (
        f'{found[1]}x="{(size - width) / 2:g}" y="0" width="{width:g}" '
        f'height="{size}"' + drawn[found.end() :]
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" '
        f'height="{size}" viewBox="0 0 {size} {size}">\n{placed}</svg>\n'
    )


def render_icon() -> None:
    """Render the icon as a PNG with a transparent background."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        page = Path(folder) / "icon.svg"
        page.write_text(icon(ICON_SOURCE.read_text("utf-8")), "utf-8")
        _screenshot(page.as_uri(), ICON, ICON_SIZE, transparent=True)


# --- the architecture diagram ---------------------------------------------

DIAGRAM_SOURCE = ASSETS / "architecture/architecture.html"
# The page's size in CSS pixels, drawn at twice that.
DIAGRAM_SIZE = (1430, 700)
DIAGRAM_SCALE = 2
# Each image and the fragment that picks its colours on the page.
DIAGRAMS = {
    ASSETS / "architecture/architecture.png": "",
    ASSETS / "architecture/architecture-dark.png": "#dark",
}


def render_diagram() -> None:
    """Render the architecture diagram as a PNG, light and dark."""
    for target, fragment in DIAGRAMS.items():
        address = DIAGRAM_SOURCE.as_uri() + fragment
        _screenshot(address, target, DIAGRAM_SIZE, DIAGRAM_SCALE)


def main(arguments: list[str]) -> int:
    if arguments == ["--check"]:
        names = [path.relative_to(REPOSITORY).as_posix() for path in stale()]
        for name in names:
            print(f"out of date: {name}", file=sys.stderr)
        return 1 if names else 0
    if arguments == ["--social"]:
        render_social()
        return 0
    if arguments == ["--diagram"]:
        render_diagram()
        return 0
    if arguments == ["--icon"]:
        render_icon()
        return 0
    if arguments:
        print(
            "usage: build.py [--check | --social | --diagram | --icon]",
            file=sys.stderr,
        )
        return 2
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
