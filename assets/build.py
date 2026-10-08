"""Make the shipped images from the sources in ``logo/``.

``uv run python assets/build.py`` writes them anew, ``--check`` only
names the ones that differ from what it would write. The sources stay
as they came, with their C2PA manifest. What is made from them goes
without it:

- the icon of the configuration UI, its sidebar and favicon, from the
  3D icon.
- the logo above the sign-in card, from the 3D logo, and for dark
  mode the same with a light word mark.
- ``logo/social-preview.png``, the image GitHub shows when the
  repository is linked, from the 3D logo. ``--social`` renders it with
  a Chromium browser (Chrome, Edge or Chromium), which ``--check``
  cannot repeat byte for byte. It goes up by hand, under Settings,
  General, Social preview.
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
# "word", in light blues, and its depth, the path drawn 3 below the
# face, in the blue of the icon. The icon keeps its colours.
_LIGHT_WORD = (
    (
        re.compile(
            r'(<linearGradient id="word"[^>]*><stop offset="0" stop-color=")'
            r'#335FDB("/><stop offset="1" stop-color=")#163CA8(")'
        ),
        r"\g<1>#DBEAFE\g<2>#93C5FD\g<3>",
    ),
    (
        re.compile(
            r'(<path transform="translate\(230,134\)" d="[^"]*" fill=")#0F2A76(")'
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
    STATIC / "img/icon.svg": (ASSETS / "logo/icon-3d.svg", plain),
    STATIC / "img/logo.svg": (ASSETS / "logo/logo-3d.svg", plain),
    STATIC / "img/logo-dark.svg": (ASSETS / "logo/logo-3d.svg", light_word),
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

SOCIAL = ASSETS / "logo/social-preview.png"
SOCIAL_SOURCE = ASSETS / "logo/logo-3d.svg"
# GitHub's size, and the light background of the configuration UI.
SOCIAL_SIZE = (1280, 640)
_BACKGROUND = "#F9FBFE"
# The logo's width on the page: GitHub may crop the edges.
_LOGO_WIDTH = 960
_ROOT_SIZE = re.compile(r'^(<svg [^>]*?)width="([\d.]+)" height="([\d.]+)"')


def social(svg: str) -> str:
    """The logo in the middle of a page of the social preview's size."""
    logo = plain(svg)
    found = _ROOT_SIZE.match(logo)
    if not found:
        raise ValueError("the logo names no width and height")
    width, height = SOCIAL_SIZE
    logo_height = _LOGO_WIDTH * float(found[3]) / float(found[2])
    x, y = (width - _LOGO_WIDTH) / 2, (height - logo_height) / 2
    placed = (
        f'{found[1]}x="{x:g}" y="{y:g}" width="{_LOGO_WIDTH}" '
        f'height="{logo_height:g}"' + logo[found.end() :]
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">\n'
        f'<rect width="{width}" height="{height}" fill="{_BACKGROUND}"/>\n'
        f"{placed}</svg>\n"
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


def render_social() -> None:
    """Render the social preview as a PNG with a headless browser."""
    width, height = SOCIAL_SIZE
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        page = Path(folder) / "social-preview.svg"
        page.write_text(social(SOCIAL_SOURCE.read_text("utf-8")), "utf-8")
        subprocess.run(
            [
                _browser(),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--user-data-dir={Path(folder) / 'profile'}",
                f"--window-size={width},{height}",
                f"--screenshot={SOCIAL}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )


def main(arguments: list[str]) -> int:
    if arguments == ["--check"]:
        names = [path.relative_to(REPOSITORY).as_posix() for path in stale()]
        for name in names:
            print(f"out of date: {name}", file=sys.stderr)
        return 1 if names else 0
    if arguments == ["--social"]:
        render_social()
        return 0
    if arguments:
        print("usage: build.py [--check | --social]", file=sys.stderr)
        return 2
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
