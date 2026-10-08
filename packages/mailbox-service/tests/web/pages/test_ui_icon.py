"""The project's icon: in the configuration UI, in the heading of every
README, and the script that makes the shipped copy from the source in
``assets/logo/``. Also the README's architecture diagram, which the same
script renders."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

REPOSITORY = Path(__file__).resolve().parents[5]
ICON = "/ui/static/img/icon.svg"


def _build() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "assets_build", REPOSITORY / "assets" / "build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_shipped_image_is_made_from_its_source() -> None:
    # After a change in assets/logo/: uv run python assets/build.py
    assert _build().stale() == []


def test_a_shipped_image_has_no_manifest() -> None:
    build = _build()
    for target in build.BUILT:
        assert "c2pa" not in target.read_text("utf-8"), target.name


def test_the_ui_shows_the_3d_icon_and_logo() -> None:
    sources = {source.name for source, _ in _build().BUILT.values()}
    assert sources == {"icon-3d.svg", "logo-3d.svg"}


def test_the_dark_logo_differs_in_the_word_mark_only() -> None:
    build = _build()
    logo = (REPOSITORY / "assets/logo/logo-3d.svg").read_text("utf-8")
    plain, light = build.plain(logo).split(">"), build.light_word(logo).split(">")
    changed = [(a, b) for a, b in zip(plain, light, strict=True) if a != b]
    # The two stops of the face's gradient, and the depth below the face.
    ends = ('stop-color="#DBEAFE"/', 'stop-color="#93C5FD"/', ' fill="#1D4ED8"/')
    assert len(changed) == len(ends)
    for (_, made), end in zip(changed, ends, strict=True):
        assert made.endswith(end), made[-40:]
    assert 'transform="translate(230,134)"' in changed[2][0]


def test_the_social_preview_has_githubs_size() -> None:
    # After a change of the 3D logo: uv run python assets/build.py --social
    build = _build()
    png = build.SOCIAL.read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = (int.from_bytes(png[at : at + 4], "big") for at in (16, 20))
    assert (width, height) == build.SOCIAL_SIZE == (1280, 640)


def test_the_social_preview_places_the_3d_logo_in_the_middle() -> None:
    build = _build()
    page = build.social(build.SOCIAL_SOURCE.read_text("utf-8"))
    assert build.SOCIAL_SOURCE.name == "logo-3d.svg"
    assert page.startswith('<svg xmlns="http://www.w3.org/2000/svg" width="1280"')
    # 658 by 224 drawn 960 wide: 326.8 high, 156.6 from the top.
    assert 'x="160" y="156.596" width="960" height="326.809"' in page
    assert "c2pa" not in page


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


def test_the_readme_shows_the_diagram_light_and_dark() -> None:
    readme = (REPOSITORY / "README.md").read_text("utf-8")
    assert (
        '<source srcset="assets/architecture/architecture-dark.png"'
        ' media="(prefers-color-scheme: dark)">' in readme
    )
    assert '<img src="assets/architecture/architecture.png" alt="' in readme


# PyPI shows no relative image: a package's README names it in full.
_RAW = "https://raw.githubusercontent.com/benethos-hub/mailbox/main/"
READMES = {
    "README.md": "",
    "containers/README.md": "../",
    "containers/production/README.md": "../../",
    "containers/test-mail-server/README.md": "../../",
    "packages/mailbox-service/README.md": _RAW,
    "packages/mailbox-client/README.md": _RAW,
    "packages/mailbox-mcp/README.md": _RAW,
}


@pytest.mark.parametrize(("readme", "prefix"), READMES.items())
def test_every_readme_has_the_3d_icon_in_its_heading(readme: str, prefix: str) -> None:
    first = (REPOSITORY / readme).read_text("utf-8").splitlines()[0]
    assert first.startswith(
        f'# <img src="{prefix}assets/logo/icon-3d.svg" alt="" height="36"'
        ' align="absmiddle"> '
    ), first


def test_every_readme_is_named() -> None:
    found = {
        path.relative_to(REPOSITORY).as_posix()
        for folder in ("", "containers/", "packages/")
        for path in (REPOSITORY / folder).glob(
            "**/README.md" if folder else "README.md"
        )
        if "vendor" not in path.parts
    }
    assert found == set(READMES)


def test_a_source_without_its_manifest_is_refused() -> None:
    with pytest.raises(ValueError, match="manifest"):
        _build().plain('<svg xmlns="http://www.w3.org/2000/svg"></svg>')


def test_the_icon_is_served(app_client: TestClient) -> None:
    answer = app_client.get(ICON)
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("image/svg+xml")


def test_the_sign_in_page_shows_the_logo(app_client: TestClient) -> None:
    page = app_client.get("/ui/login").text
    assert f'<link rel="icon" href="{ICON}"' in page
    assert (
        '<source srcset="/ui/static/img/logo-dark.svg"'
        ' media="(prefers-color-scheme: dark)" />' in page
    )
    assert '<img src="/ui/static/img/logo.svg" alt="Mailbox"' in page
    for logo in ("logo.svg", "logo-dark.svg"):
        assert app_client.get(f"/ui/static/img/{logo}").status_code == 200, logo


def test_every_page_shows_the_icon(ui: TestClient) -> None:
    page = ui.get("/ui").text
    assert f'<link rel="icon" href="{ICON}"' in page
    assert f'<img class="mark" src="{ICON}"' in page
