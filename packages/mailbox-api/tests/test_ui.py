"""The configuration UI: signing in, the session, CSRF, the frame."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import Grant
from benethos_mailbox_api.main import Services
from benethos_mailbox_api.web.pages.session import IDLE, SessionStore

from .conftest import API_KEY, bearer_for
from .ui_helpers import csrf_of, sign_in

# --- signing in -----------------------------------------------------------------------


def test_a_page_without_a_session_asks_to_sign_in(app_client: TestClient) -> None:
    answer = app_client.get("/ui", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/ui/login?next=/ui"


def test_htmx_is_sent_to_the_sign_in_page(app_client: TestClient) -> None:
    answer = app_client.get("/ui", headers={"HX-Request": "true"})
    assert answer.status_code == 204
    assert answer.headers["HX-Redirect"].startswith("/ui/login")


def test_sign_in_sets_a_strict_session_cookie(app_client: TestClient) -> None:
    page = app_client.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    answer = app_client.post(
        "/ui/login",
        data={"token": API_KEY, "nonce": nonce.group(1)},
        follow_redirects=False,
    )
    cookie = answer.headers["set-cookie"]
    assert "mailbox_ui_session=" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/ui" in cookie
    assert API_KEY not in cookie
    assert app_client.get("/ui").status_code == 200


def test_a_wrong_token_is_refused(app_client: TestClient) -> None:
    page = app_client.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    answer = app_client.post(
        "/ui/login", data={"token": "wrong", "nonce": nonce.group(1)}
    )
    assert "That token is not valid." in answer.text
    assert app_client.get("/ui", follow_redirects=False).status_code == 303


def test_the_sign_in_form_needs_its_nonce(app_client: TestClient) -> None:
    """Another site cannot sign this browser in to an account of its own."""
    answer = app_client.post(
        "/ui/login", data={"token": API_KEY, "nonce": "forged"}, follow_redirects=False
    )
    assert "err=" in answer.headers["location"]
    assert app_client.get("/ui", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    ("next", "lands"),
    [("/ui", "/ui"), ("//evil.example/ui", "/ui"), ("https://evil.example", "/ui")],
)
def test_after_sign_in_only_pages_of_the_ui(
    app_client: TestClient, next: str, lands: str
) -> None:
    page = app_client.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    answer = app_client.post(
        "/ui/login",
        data={"token": API_KEY, "nonce": nonce.group(1), "next": next},
        follow_redirects=False,
    )
    assert answer.headers["location"] == lands


def test_a_user_token_signs_in_with_its_rights(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(services, Grant(accounts=[account_id], allow=["mail.read"]))
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    page = app_client.get("/ui").text
    assert "Signed in as <strong>limited</strong>" in page
    assert "mail.read" in page
    assert "reads and sends anywhere" not in page


def test_the_admin_key_is_warned(ui: TestClient, account_id: str) -> None:
    assert "reads and sends anywhere" in ui.get("/ui").text


# --- the session ----------------------------------------------------------------------


def test_sign_out_needs_the_csrf_token(ui: TestClient) -> None:
    refused = ui.post("/ui/logout", data={"csrf_token": "forged"})
    assert refused.status_code == 403
    assert "Form expired" in refused.text
    assert ui.get("/ui").status_code == 200
    token = csrf_of(ui.get("/ui").text)
    answer = ui.post("/ui/logout", data={"csrf_token": token}, follow_redirects=False)
    assert answer.status_code == 303
    assert ui.get("/ui", follow_redirects=False).status_code == 303


def test_the_csrf_token_also_comes_as_a_header(ui: TestClient) -> None:
    token = csrf_of(ui.get("/ui").text)
    answer = ui.post(
        "/ui/logout", headers={"X-CSRF-Token": token}, follow_redirects=False
    )
    assert answer.status_code == 303


def test_a_revoked_token_ends_the_session(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    user = services.users.create_user(
        services.auth.authenticate(API_KEY),
        "reader",
        [],
        [Grant(accounts=[account_id], allow=["mail.read"])],
    )
    issued, plain = services.auth.issue_token(user.id, "ui")
    sign_in(app_client, plain)
    assert app_client.get("/ui").status_code == 200
    services.auth.revoke_token(issued.id)
    assert app_client.get("/ui", follow_redirects=False).status_code == 303


def test_an_idle_session_expires() -> None:
    now = [datetime(2026, 9, 24, 12)]
    store = SessionStore(clock=lambda: now[0])
    session_id = store.create("token")
    now[0] += IDLE - timedelta(minutes=1)
    assert store.get(session_id) is not None
    now[0] += IDLE + timedelta(minutes=1)
    assert store.get(session_id) is None
    assert store.get(session_id) is None
    assert store.get(None) is None


# --- the frame ------------------------------------------------------------------------


def test_security_headers_on_the_ui_only(ui: TestClient, client: TestClient) -> None:
    page = ui.get("/ui")
    policy = page.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert page.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in client.get("/v1/me").headers


def test_no_inline_script(ui: TestClient) -> None:
    page = ui.get("/ui").text
    assert (
        "<script>" not in page and " onsubmit=" not in page and " onclick=" not in page
    )


def test_static_files(app_client: TestClient) -> None:
    for path in (
        "/ui/static/css/app.css",
        "/ui/static/js/app.js",
        "/ui/static/vendor/htmx/htmx.min.js",
    ):
        assert app_client.get(path).status_code == 200, path


def test_errors_in_the_ui_are_pages(ui: TestClient, client: TestClient) -> None:
    missing = ui.get("/ui/nothing-here")
    assert missing.status_code == 404
    assert "text/html" in missing.headers["content-type"]
    assert client.get("/v1/nothing-here").json()["error"]["code"] == "not_found"


def test_an_incomplete_form_is_a_page(app_client: TestClient) -> None:
    answer = app_client.post("/ui/login", data={})
    assert answer.status_code == 400
    assert "Incomplete form" in answer.text


def test_the_ui_is_not_in_the_contract(client: TestClient) -> None:
    assert not [p for p in client.get("/openapi.json").json()["paths"] if "/ui" in p]
