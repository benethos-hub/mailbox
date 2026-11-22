"""The scripts of ``assets/``: ``build.py`` makes the shipped images
from the sources in ``assets/brand/`` and renders the architecture
diagram of the READMEs, ``icons.py`` makes the UI's icon sprite from a
pinned Bootstrap Icons package."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from .repository_helpers import ROOT
from .scripts_helpers import script_module


def _build() -> ModuleType:
    return script_module("assets_build", ROOT / "assets" / "build.py")


def _icons() -> ModuleType:
    return script_module(
        "assets_icons", ROOT / "assets" / "mailbox-service" / "icons.py"
    )


# --- build.py -------------------------------------------------------------------------


def test_every_shipped_image_is_made_from_its_source() -> None:
    # After a change in assets/brand/: uv run python assets/build.py
    assert _build().stale() == []


def test_a_shipped_image_has_no_manifest() -> None:
    build = _build()
    for target in build.BUILT:
        assert "c2pa" not in target.read_text("utf-8"), target.name


def test_the_ui_shows_the_3d_icon_and_logo() -> None:
    sources = {source.name for source, _ in _build().BUILT.values()}
    assert sources == {"icon.svg", "logo.svg"}


def test_the_dark_logo_differs_in_the_word_mark_only() -> None:
    build = _build()
    logo = (ROOT / "assets/brand/logo.svg").read_text("utf-8")
    plain, light = build.plain(logo).split(">"), build.light_word(logo).split(">")
    changed = [(a, b) for a, b in zip(plain, light, strict=True) if a != b]
    # The three stops of the face's gradient, the depth below the face and
    # the claim under the word mark.
    ends = (
        'stop-color="#DBEAFE"/',
        'stop-color="#BFDBFE"/',
        'stop-color="#93C5FD"/',
        ' fill="#1D4ED8"/',
        ' fill="#BFDBFE"/',
    )
    assert len(changed) == len(ends)
    for (_, made), end in zip(changed, ends, strict=True):
        assert made.endswith(end), made[-40:]
    assert 'transform="translate(230,124)"' in changed[3][0]
    assert 'transform="translate(230,158)"' in changed[4][0]


def test_the_social_preview_has_githubs_size() -> None:
    # After a change of the 3D logo: uv run python assets/build.py --social
    build = _build()
    png = build.SOCIAL.read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = (int.from_bytes(png[at : at + 4], "big") for at in (16, 20))
    assert (width, height) == build.SOCIAL_SIZE == (1280, 640)


def test_the_social_preview_shows_the_3d_logo_and_what_it_is() -> None:
    build = _build()
    assert (build.SOCIAL_SOURCE.name, build.SOCIAL_MARK.name) == (
        "logo.svg",
        "icon.svg",
    )
    page = build.social(
        build.SOCIAL_SOURCE.read_text("utf-8"), build.SOCIAL_MARK.read_text("utf-8")
    )
    assert "width: 1280px; height: 640px;" in page
    # The logo, the faint icon, the lines behind and a sign for each use.
    assert page.count("<svg ") == 3 + len(build.SOCIAL_USES)
    # Each line starts at a half circle on the left edge.
    assert page.count('<path d="M 0 ') == len(build._SOCIAL_LINES)
    assert "c2pa" not in page
    # The claim is part of the logo, under its word mark.
    assert 'transform="translate(230,158)"' in build.plain(
        build.SOCIAL_SOURCE.read_text("utf-8")
    )
    for provider in build.SOCIAL_PROVIDERS:
        assert f'<span class="chip">{provider}</span>' in page
    # GitHub may crop the edges: the content keeps away from them.
    assert "position: absolute; left: 96px; right: 96px; top: 84px;" in page


def test_the_png_icon_is_square_and_transparent() -> None:
    # After a change of the 3D icon: uv run python assets/build.py --icon
    build = _build()
    png = build.ICON.read_bytes()
    width, height = (int.from_bytes(png[at : at + 4], "big") for at in (16, 20))
    assert (width, height) == build.ICON_SIZE == (512, 512)
    # Colour type 6: RGB with an alpha channel.
    assert png[25] == 6


def test_the_png_icon_places_the_3d_icon_in_the_middle() -> None:
    build = _build()
    page = build.icon(build.ICON_SOURCE.read_text("utf-8"))
    assert build.ICON_SOURCE.name == "icon.svg"
    # 216 by 224 drawn 512 high: 493.7 wide, 9.1 from the left.
    assert 'x="9.14286" y="0" width="493.714" height="512"' in page
    # No background: the icon follows the page directly.
    assert "c2pa" not in page
    assert page.splitlines()[1].startswith("<svg ")


def test_the_architecture_diagram_has_the_size_of_its_page() -> None:
    # After a change of the diagram: uv run python assets/build.py --diagram
    build = _build()
    width, height = build.DIAGRAM_SIZE
    page = build.DIAGRAM_SOURCE.read_text("utf-8")
    assert f"width: {width}px; height: {height}px;" in page
    assert f'viewBox="0 0 {width} {height}"' in page
    for image in build.DIAGRAMS:
        png = image.read_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n"), image.name
        size = tuple(int.from_bytes(png[at : at + 4], "big") for at in (16, 20))
        assert size == (width * build.DIAGRAM_SCALE, height * build.DIAGRAM_SCALE)


def test_the_diagram_without_its_page_is_not_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = _build()
    shot: list[str] = []
    monkeypatch.setattr(build, "DIAGRAM_SOURCE", tmp_path / "gone.html")
    monkeypatch.setattr(build, "_screenshot", lambda *args, **kw: shot.append("x"))
    with pytest.raises(SystemExit, match="no page of the diagram"):
        build.render_diagram()
    assert shot == []


def test_a_browser_that_writes_nothing_ends_the_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = _build()
    monkeypatch.setattr(build, "_browser", lambda: "browser")
    monkeypatch.setattr(build.subprocess, "run", lambda *args, **kw: None)
    with pytest.raises(SystemExit, match="wrote no image"):
        build._screenshot("about:blank", tmp_path / "shot.png", (10, 10))


def test_a_source_without_its_manifest_is_refused() -> None:
    with pytest.raises(ValueError, match="manifest"):
        _build().plain('<svg xmlns="http://www.w3.org/2000/svg"></svg>')


# --- icons.py -------------------------------------------------------------------------


def test_the_sprite_holds_the_icons_the_script_names() -> None:
    # After a change of ICONS: uv run python assets/mailbox-service/icons.py
    icons = _icons()
    assert icons.main(["--check"]) == 0
    sprite = icons.SPRITE.read_text("utf-8")
    assert f"Bootstrap Icons {icons.VERSION}, MIT licence" in sprite
    assert "<script" not in sprite and "style=" not in sprite
    assert "MIT License" in icons.LICENSE.read_text("utf-8")


def test_an_icon_of_another_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="expected shape"):
        _icons().symbol("x", "<svg><path/></svg>")


def test_the_script_turns_an_icon_into_a_symbol() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"'
        ' fill="currentColor" class="bi bi-plus" viewBox="0 0 16 16">\n'
        '  <path d="M8 4"/>\n  <path d="M1 1"/>\n</svg>'
    )
    made = _icons().symbol("plus", svg)
    assert made == (
        '<symbol id="plus" viewBox="0 0 16 16">'
        '<path d="M8 4"/> <path d="M1 1"/></symbol>'
    )
