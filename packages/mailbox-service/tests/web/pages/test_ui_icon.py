"""The project's icon and logo in the configuration UI. The script that
makes them from ``assets/brand/`` is held by ``tests/test_assets.py``
at the repository's root."""

from __future__ import annotations

from fastapi.testclient import TestClient

ICON = "/ui/static/img/icon.svg"


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
