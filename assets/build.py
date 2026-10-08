"""Make the shipped images from the sources in ``logo/``.

``uv run python assets/build.py`` writes them anew, ``--check`` only
names the ones that differ from what it would write. The sources stay
as they came, with their C2PA manifest. What is made from them goes
without it:

- the icon of the configuration UI, its sidebar and favicon, from the
  3D icon.
"""

from __future__ import annotations

import re
import sys
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
