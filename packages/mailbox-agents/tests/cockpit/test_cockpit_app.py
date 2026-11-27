"""The pages of the cockpit, its sign-in and the headers of its answers."""

from __future__ import annotations

import logging
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_agents.cockpit import security
from benethos_mailbox_agents.cockpit.app import Cockpit
from benethos_mailbox_agents.cockpit.templates import STATIC_DIR, TEMPLATE_DIR

from .cockpit_helpers import NOW, SECRET, signed_in

PAGES = ("/", "/agents/counting", "/agents/counting/messages/acc1/m1")


def _nonce(client: TestClient) -> str:
    found = re.search(r'name="nonce" value="([^"]+)"', client.get("/login").text)
    assert found is not None
    return found[1]


@pytest.mark.parametrize("path", PAGES)
def test_without_a_session_every_page_leads_to_the_sign_in(
    client: TestClient, path: str
) -> None:
    answer = client.get(path)

    assert (answer.status_code, answer.headers["location"]) == (303, "/login")


def test_the_right_secret_signs_in_and_the_pages_show(client: TestClient) -> None:
    signed_in(client)

    overview = client.get("/")
    instance = client.get("/agents/counting")
    message = client.get("/agents/counting/messages/acc1/m1")

    assert overview.status_code == instance.status_code == message.status_code == 200
    assert 'href="/agents/counting"' in overview.text
    assert "classifier" in overview.text
    assert "agent-counted" in instance.text
    assert "Billing\\u202e &lt;billing@example.org&gt;" in instance.text
    assert "Your invoice\\x1b[2J &lt;script&gt;alert(1)&lt;/script&gt;" in message.text
    assert "<script>" not in message.text
    assert client.get("/login").headers["location"] == "/"


def test_a_wrong_secret_is_refused_and_counted(
    client: TestClient, cockpit: Cockpit
) -> None:
    for _ in range(security.LIMIT):
        answer = client.post(
            "/login", data={"secret": "wrong", "nonce": _nonce(client)}
        )
        assert answer.headers["location"] == "/login?notice=wrong"

    held = client.post("/login", data={"secret": SECRET, "nonce": _nonce(client)})

    assert held.status_code == 429
    assert "Try again in 15 minutes" in held.text
    assert int(held.headers["retry-after"]) == 15 * 60
    assert client.get("/").status_code == 303


def test_a_sign_in_without_the_nonce_of_its_form_is_refused(client: TestClient) -> None:
    _nonce(client)

    answer = client.post("/login", data={"secret": SECRET, "nonce": "other"})

    assert answer.headers["location"] == "/login?notice=expired"
    assert client.get("/").status_code == 303


def test_signing_out_needs_the_token_of_the_session(client: TestClient) -> None:
    signed_in(client)
    token = re.search(r'name="token" value="([^"]+)"', client.get("/").text)
    assert token is not None

    assert client.post("/logout", data={"token": "other"}).status_code == 403
    out = client.post("/logout", data={"token": token[1]})

    assert out.headers["location"] == "/login?notice=out"
    assert client.get("/").status_code == 303


@pytest.mark.parametrize("path", ["/login", "/", "/static/css/app.css", "/nowhere"])
def test_the_headers_stand_on_every_answer(client: TestClient, path: str) -> None:
    signed_in(client)

    answer = client.get(path)

    policy = answer.headers["content-security-policy"]
    assert "script-src 'none'" in policy and "frame-ancestors 'none'" in policy
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["referrer-policy"] == "same-origin"
    static = path.startswith("/static/")
    assert answer.headers["cache-control"] == ("no-cache" if static else "no-store")


@pytest.mark.parametrize(
    "path",
    [
        "/agents/nobody",
        "/agents/..%2Fcounting",
        "/agents/counting/messages/acc1/m9",
        "/nowhere",
    ],
)
def test_what_is_not_there_is_a_page_of_html(client: TestClient, path: str) -> None:
    signed_in(client)

    answer = client.get(path)

    assert answer.status_code == 404
    assert answer.headers["content-type"].startswith("text/html")
    assert "nobody" not in answer.text and "m9" not in answer.text


def test_a_state_the_store_does_not_know_is_refused(client: TestClient) -> None:
    signed_in(client)

    answer = client.get("/agents/counting?state=<b>")

    assert answer.status_code == 400
    assert "&lt;b&gt;" not in answer.text and "<b>" not in answer.text


def test_no_page_holds_a_script_a_style_or_the_secret(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    shown = [client.get("/login").text]
    signed_in(client)
    shown += [client.get(path).text for path in PAGES]

    for page in shown:
        assert "<script" not in page and "style=" not in page
        assert SECRET not in page
    assert SECRET not in caplog.text


def test_no_template_marks_text_as_safe_or_loads_from_elsewhere() -> None:
    loaded = re.compile(r'\b(?:src|href|srcset)="(?:https?:)?//', re.I)
    for template in TEMPLATE_DIR.rglob("*.html"):
        text = template.read_text(encoding="utf-8")
        assert not re.search(r"\|\s*safe\b", text), template.name
        assert not loaded.search(text), template.name
        assert "<script" not in text and "style=" not in text, template.name


def test_every_class_a_template_names_is_styled() -> None:
    css = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    styled = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    unstyled = {
        f"{template.name}: {name}"
        for template in TEMPLATE_DIR.rglob("*.html")
        for names in re.findall(r'class="([^"{}]*)"', template.read_text("utf-8"))
        for name in names.split()
        if name not in styled
    }

    assert not unstyled, sorted(unstyled)


def test_the_sessions_end_when_idle_or_too_old() -> None:
    sessions = security.Sessions()
    first = sessions.start(NOW)
    second = sessions.start(NOW)

    assert sessions.get(first.id, NOW + timedelta(hours=7)) is first
    assert sessions.get(second.id, NOW + timedelta(hours=9)) is None
    assert sessions.get(first.id, NOW + timedelta(hours=14)) is first
    assert sessions.get(first.id, NOW + timedelta(hours=25)) is None
    assert sessions.get(None, NOW) is None
