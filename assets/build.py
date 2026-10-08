"""Make the shipped images from the sources in ``logo/``.

``uv run python assets/build.py`` writes them anew, ``--check`` only
names the ones that differ from what it would write. The sources stay
as they came, with their C2PA manifest. What is made from them goes
without it:

- the icon of the configuration UI, its sidebar and favicon, from the
  3D icon.
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


# What is made, and from which source.
BUILT: dict[Path, Path] = {
    STATIC / "img/icon.svg": ASSETS / "logo/icon-3d.svg",
}


def stale() -> list[Path]:
    """The made images that differ from what their source makes."""
    return [
        target
        for target, source in BUILT.items()
        if not target.exists()
        or target.read_bytes() != plain(source.read_text("utf-8")).encode("utf-8")
    ]


def build() -> None:
    for target, source in BUILT.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(plain(source.read_text("utf-8")).encode("utf-8"))


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
