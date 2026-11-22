"""What assets/mailbox-agents/build.py writes into the PNG files: the hash
of each source, so a change of the SVG or the diagram's page always changes them, as the
brand check asks, and a screenshot only when the browser wrote one."""

from __future__ import annotations

import hashlib
import re
import struct
import subprocess
import zlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from benethos_mailbox_agents.contract import discover

from .helpers import ROOT, load_script

BUILD = ROOT / "assets" / "mailbox-agents" / "build.py"


@pytest.fixture(scope="module")
def build() -> Iterator[ModuleType]:
    with load_script(BUILD, "assets_build") as module:
        yield module


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    + _chunk(b"IDAT", zlib.compress(b"\0\0\0\0\0"))
    + _chunk(b"IEND", b"")
)


def _texts(png: bytes) -> list[bytes]:
    position, found = 8, []
    while position < len(png):
        (length,) = struct.unpack(">I", png[position : position + 4])
        if png[position + 4 : position + 8] == b"tEXt":
            found.append(png[position + 8 : position + 8 + length])
        position += 12 + length
    return found


def test_the_stamp_names_the_hash_of_the_svg(build: ModuleType) -> None:
    stamped = build.stamped(PNG, {"icon.svg": "<svg/>"})

    (text,) = _texts(stamped)
    assert text.startswith(b"Source\0icon.svg sha256:")
    assert stamped.endswith(PNG[33:])


def test_another_svg_gives_another_png_and_one_stamp_only(build: ModuleType) -> None:
    first = build.stamped(PNG, {"icon.svg": "<svg><title>a</title></svg>"})
    second = build.stamped(first, {"icon.svg": "<svg><title>b</title></svg>"})

    assert first != second
    assert len(_texts(second)) == 1
    assert build.stamped(second, {"icon.svg": "<svg><title>b</title></svg>"}) == second


@pytest.mark.parametrize(
    "png",
    [PNG[:35], PNG[:60], PNG + b"\0\1", PNG[:-12]],
    ids=["length-cut", "chunk-cut", "after-iend", "no-iend"],
)
def test_a_png_cut_short_or_with_bytes_after_its_end_is_refused(
    build: ModuleType, png: bytes
) -> None:
    with pytest.raises(ValueError, match="PNG"):
        build.stamped(png, {"icon.svg": "<svg/>"})


def test_a_browser_that_writes_no_screenshot_leaves_the_png_as_it_was(
    build: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    icon = tmp_path / "icon.png"
    icon.write_bytes(PNG)
    monkeypatch.setattr(build, "ICON", icon)
    monkeypatch.setattr(build, "_browser", lambda: "chromium")
    monkeypatch.setattr(
        build.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )

    with pytest.raises(RuntimeError, match="no screenshot for icon.png"):
        build.render_icon()

    assert icon.read_bytes() == PNG


def test_a_file_that_is_no_png_is_refused(build: ModuleType) -> None:
    with pytest.raises(ValueError):
        build.stamped(b"GIF89a", {"icon.svg": "<svg/>"})


def test_each_source_gets_a_stamp_of_its_own_in_order(build: ModuleType) -> None:
    sources = {"page.html": "<html></html>", "icon.svg": "<svg/>"}

    found = _texts(build.stamped(build.stamped(PNG, {"x": "y"}), sources))

    assert [text.split(b" ")[0] for text in found] == [
        b"Source\0page.html",
        b"Source\0icon.svg",
    ]


def _expected(*sources: Path) -> list[bytes]:
    return [
        b"Source\0"
        + f"{source.name} sha256:".encode()
        + hashlib.sha256(source.read_text("utf-8").encode("utf-8")).hexdigest().encode()
        for source in sources
    ]


def test_each_versioned_png_carries_the_stamp_of_its_sources(
    build: ModuleType,
) -> None:
    icon, page = build.ICON_SOURCE, build.DIAGRAM_SOURCE
    expected = {
        build.ICON: _expected(icon),
        **{target: _expected(page, icon) for target in build.DIAGRAMS},
    }

    for png, stamps in expected.items():
        assert _texts(png.read_bytes()) == stamps, png.name


def test_the_diagram_names_every_agent(build: ModuleType) -> None:
    page = build.DIAGRAM_SOURCE.read_text("utf-8")
    listed = re.search(r'<ul class="agents">(.*?)</ul>', page, flags=re.DOTALL)

    assert listed is not None
    names = re.findall(r"<li><code>(\w+)</code></li>", listed.group(1))
    assert sorted(names) == sorted(discover())


def _css_size(page: str) -> tuple[int, int]:
    found = re.search(r"html, body \{[^}]*width: (\d+)px; height: (\d+)px", page)
    assert found is not None
    return int(found.group(1)), int(found.group(2))


def test_each_png_has_the_size_its_page_is_drawn_at(build: ModuleType) -> None:
    sizes = {
        build.ICON: (build.ICON_SIZE, 1),
        **{png: (build.DIAGRAM_SIZE, build.DIAGRAM_SCALE) for png in build.DIAGRAMS},
    }

    for png, ((width, height), scale) in sizes.items():
        header = png.read_bytes()[16:24]
        assert struct.unpack(">II", header) == (width * scale, height * scale), png.name
    assert _css_size(build.DIAGRAM_SOURCE.read_text("utf-8")) == build.DIAGRAM_SIZE
