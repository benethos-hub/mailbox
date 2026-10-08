"""The project's icon in the configuration UI, and the script that makes
the shipped copy from the source in ``assets/logo/``."""

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


def test_the_dark_logo_differs_in_the_word_mark_only() -> None:
    build = _build()
    logo = (REPOSITORY / "assets/logo/logo.svg").read_text("utf-8")
    # The word mark is the last element, after the icon's own dark blue.
    head, _, tail = build.plain(logo).rpartition('fill="#1D4ED8"')
    assert build.dark(logo) == f'{head}fill="{build.LIGHT}"{tail}'


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
