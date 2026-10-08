"""Make the shipped images from the sources in ``logo/``.

``uv run python assets/build.py`` writes them anew, ``--check`` only
names the ones that differ from what it would write. The sources stay
as they came, with their C2PA manifest. What is made from them goes
without it:

- ``logo/logo-dark.svg``: the logo with a light word mark, for a page
  in dark mode (the README on GitHub).
- the icon of the configuration UI, its sidebar and favicon.
"""

from __future__ import annotations

import re
import sys
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
# The word mark is the one path placed with a translation.
_WORD_MARK = re.compile(
    r'(<path transform="translate\([^)]*\)" d="[^"]*" fill=")#1D4ED8(")'
)
# The light blue of the icon's lines, readable on a dark page.
LIGHT = "#93C5FD"


def plain(svg: str) -> str:
    """The image without its manifest."""
    text, count = _MANIFEST.subn("", svg)
    if count != 1:
        raise ValueError(f"expected one manifest, found {count}")
    return text.replace(_NAMESPACE, "")


def dark(svg: str) -> str:
    """The logo with a light word mark."""
    text, count = _WORD_MARK.subn(rf"\g<1>{LIGHT}\g<2>", plain(svg))
    if count != 1:
        raise ValueError(f"expected one word mark, found {count}")
    return text


# What is made, from which source, and how.
BUILT: dict[Path, tuple[Path, Callable[[str], str]]] = {
    ASSETS / "logo/logo-dark.svg": (ASSETS / "logo/logo.svg", dark),
    STATIC / "img/icon.svg": (ASSETS / "logo/icon.svg", plain),
}


def stale() -> list[Path]:
    """The made images that differ from what their source makes."""
    return [
        target
        for target, (source, make) in BUILT.items()
        if not target.exists()
        or target.read_bytes() != make(source.read_text("utf-8")).encode("utf-8")
    ]


def build() -> None:
    for target, (source, make) in BUILT.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(make(source.read_text("utf-8")).encode("utf-8"))


def main(arguments: list[str]) -> int:
    if arguments == ["--check"]:
        names = [path.relative_to(REPOSITORY).as_posix() for path in stale()]
        for name in names:
            print(f"out of date: {name}", file=sys.stderr)
        return 1 if names else 0
    if arguments:
        print("usage: build.py [--check]", file=sys.stderr)
        return 2
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
