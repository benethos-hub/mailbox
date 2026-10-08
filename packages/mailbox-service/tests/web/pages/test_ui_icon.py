"""The project's icon: in the configuration UI, in the heading of every
README, and the script that makes the shipped copy from the source in
``assets/logo/``."""

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


def test_the_ui_shows_the_3d_icon() -> None:
    assert list(_build().BUILT.values()) == [REPOSITORY / "assets/logo/icon-3d.svg"]


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


def test_the_sign_in_page_shows_the_icon(app_client: TestClient) -> None:
    page = app_client.get("/ui/login").text
    assert f'<link rel="icon" href="{ICON}"' in page
    assert f'<img class="mark" src="{ICON}"' in page


def test_every_page_shows_the_icon(ui: TestClient) -> None:
    page = ui.get("/ui").text
    assert f'<link rel="icon" href="{ICON}"' in page
    assert f'<img class="mark" src="{ICON}"' in page
