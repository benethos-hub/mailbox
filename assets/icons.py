"""Make the icons of the configuration UI: one sprite of the Bootstrap
Icons named in ``ICONS``, with their licence beside it.

``uv run python assets/icons.py`` downloads the package of the pinned
version from npm, checks its SHA-256 and picks the icons from it, read
in memory, nothing unpacked. ``--check`` only says whether the sprite
holds exactly ``ICONS``, without the network. Nothing is loaded from
elsewhere when the UI runs (docs/UI.md 7).

A new icon is a line in ``ICONS``, then the sprite is made anew.
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
STATIC = (
    ASSETS.parent
    / "packages/mailbox-service/src/benethos_mailbox_service/web/pages/static"
)

VERSION = "1.13.1"
URL = f"https://registry.npmjs.org/bootstrap-icons/-/bootstrap-icons-{VERSION}.tgz"
SHA256 = "5ec2a52a7de279ac2f26d193dd5748343ec00ba613413bd5ab9202b36d06a8e2"
SPRITE = STATIC / "img/icons.svg"
LICENSE = STATIC / "img/icons-LICENSE.txt"

# The icons the pages use, by their name in Bootstrap Icons.
ICONS = (
    # the sidebar
    "house",
    "search",
    "at",
    "send",
    "broadcast",
    "people",
    "person-badge",
    "journal-text",
    "terminal",
    "key",
    "layout-sidebar",
    # the account menu
    "person-circle",
    "shield-lock",
    "box-arrow-right",
    "chevron-up",
    # actions
    "plus-lg",
    "pencil",
    "trash",
    "x-octagon",
    "check-lg",
    "x-lg",
    "clipboard",
    "clipboard-check",
    "download",
    "envelope",
    "envelope-open",
    "reply",
    "reply-all",
    "forward",
    "star",
    "star-fill",
    "paperclip",
    "folder",
    "folder-symlink",
    "arrow-repeat",
    "arrow-clockwise",
    "slash-circle",
    "check-circle",
    "person-plus",
    "person-dash",
    "tag",
    "exclamation-circle",
)

_SYMBOL = re.compile(r'^<svg [^>]*viewBox="([^"]+)"[^>]*>(.*)</svg>\s*$', re.S)
_NAMES = re.compile(r'<symbol id="([^"]+)"')


def symbol(name: str, svg: str) -> str:
    """One icon of the package as a ``<symbol>`` of the sprite."""
    found = _SYMBOL.match(svg.strip())
    if not found:
        raise ValueError(f"{name}: not an icon of the expected shape")
    paths = " ".join(line.strip() for line in found[2].strip().splitlines())
    return f'<symbol id="{name}" viewBox="{found[1]}">{paths}</symbol>'


def sprite(read: Callable[[str], str]) -> str:
    """The sprite of ``ICONS``, each read by its path in the package."""
    symbols = "\n".join(symbol(n, read(f"package/icons/{n}.svg")) for n in ICONS)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        f"<!-- Bootstrap Icons {VERSION}, MIT licence: icons-LICENSE.txt."
        " Made by assets/icons.py. -->\n"
        f"{symbols}\n</svg>\n"
    )


def names(text: str) -> list[str]:
    """The icons a sprite holds, in its order."""
    return _NAMES.findall(text)


def build() -> None:
    with urllib.request.urlopen(URL, timeout=60) as answer:
        package = answer.read()
    digest = hashlib.sha256(package).hexdigest()
    if digest != SHA256:
        raise ValueError(f"the package's SHA-256 is {digest}, not the pinned one")
    with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as archive:

        def read(path: str) -> str:
            member = archive.extractfile(path)
            if member is None:
                raise ValueError(f"{path}: not a file")
            return member.read().decode("utf-8")

        made = sprite(read)
        licence = read("package/LICENSE")
    SPRITE.write_bytes(made.encode("utf-8"))
    LICENSE.write_bytes(licence.encode("utf-8"))


def main(arguments: list[str]) -> int:
    if arguments == ["--check"]:
        held = names(SPRITE.read_text("utf-8")) if SPRITE.exists() else []
        if held != list(ICONS):
            print("out of date: the sprite, run assets/icons.py", file=sys.stderr)
            return 1
        return 0
    if arguments:
        print("usage: icons.py [--check]", file=sys.stderr)
        return 2
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
