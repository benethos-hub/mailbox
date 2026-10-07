"""The limits of the web layer: the size of a request body, refused with
413 before it is read whole, and the requests a minute, refused with 429."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.web import limits
from benethos_mailbox_service.web.api import PREFIX as API_PREFIX
from benethos_mailbox_service.web.limits import Buckets, RequestLimits

from ..conftest import METHODS, bearer_for, browser_admin
from ..ui_helpers import csrf_of, sign_in

LIMIT = 4096


@pytest.fixture(autouse=True)
def small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Read when the app builds its middleware, at the first request.
    monkeypatch.setattr(limits, "MAX_BODY", LIMIT)


def test_a_declared_body_above_the_limit_is_refused(
    client: TestClient, account_id: str, services: Services
) -> None:
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"to": [{"email": "you@example.com"}], "text": "x" * LIMIT},
    )
    assert answer.status_code == 413
    assert answer.json()["error"]["code"] == "payload_too_large"
    assert services.adapters.get(account_id).outbox == []  # type: ignore[attr-defined]


def test_a_chunked_body_is_cut_off_at_the_limit(
    client: TestClient, account_id: str
) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"to": [{"email": "you@example.com"}], "text": "'
        for _ in range(8):
            yield b"x" * 1024
        yield b'"}'

    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert answer.status_code == 413
    assert answer.json()["error"]["code"] == "payload_too_large"


def test_a_body_within_the_limit_passes(client: TestClient, account_id: str) -> None:
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"to": [{"email": "you@example.com"}], "text": "Hallo"},
    )
    assert answer.status_code == 200


def test_an_upload_above_the_limit_is_a_page(ui: TestClient, account_id: str) -> None:
    form = ui.get(f"/ui/accounts/{account_id}/compose").text
    answer = ui.post(
        f"/ui/accounts/{account_id}/compose",
        data={"csrf_token": csrf_of(form), "to": "bob@example.org", "do": "send"},
        files=[("attachments", ("big.bin", b"x" * LIMIT, "application/octet-stream"))],
    )
    assert answer.status_code == 413
    assert "larger than" in answer.text
    assert answer.headers["content-type"].startswith("text/html")


# --- requests a minute --------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def limited(
    settings: Settings, services: Services, signed_in: int, anonymous: int
) -> tuple[TestClient, Clock]:
    """A client of an app whose limits run on a clock the test moves."""
    app = create_app(settings, services)
    clock = Clock()
    app.state.request_limits = RequestLimits(signed_in, anonymous, clock)
    return TestClient(app), clock


def refusals(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name.endswith("http.rate_limited")
    ]


def test_a_token_gets_a_burst_of_half_its_minute_then_waits(
    settings: Settings, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    client, clock = limited(settings, services, signed_in=4, anonymous=0)
    token = bearer_for(services)
    assert [client.get("/v1/me", headers=token).status_code for _ in range(2)] == [
        200,
        200,
    ]
    answer = client.get("/v1/me", headers=token)
    assert answer.status_code == 429
    assert answer.headers["Retry-After"] == "15"
    assert answer.json()["error"]["code"] == "rate_limited"
    # Refused again, logged once.
    assert client.get("/v1/me", headers=token).status_code == 429
    assert len(refusals(caplog)) == 1
    assert (
        "sent too many requests, the last to /v1/me from testclient"
        in (refusals(caplog)[0])
    )
    assert "limited to 4 a minute, refused for 15 seconds" in refusals(caplog)[0]
    # Another token has a bucket of its own.
    assert client.get("/v1/me", headers=bearer_for(services)).status_code == 200
    clock.now += 15
    assert client.get("/v1/me", headers=token).status_code == 200


def test_a_limit_that_engages_again_is_logged_again(
    settings: Settings, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    client, clock = limited(settings, services, signed_in=2, anonymous=0)
    token = bearer_for(services)
    for _ in range(2):
        assert client.get("/v1/me", headers=token).status_code == 200
        assert client.get("/v1/me", headers=token).status_code == 429
        assert client.get("/v1/me", headers=token).status_code == 429
        clock.now += 30
    assert len(refusals(caplog)) == 2


def test_a_client_without_a_credential_counts_by_its_address(
    settings: Settings, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = limited(settings, services, signed_in=0, anonymous=2)
    assert client.get("/ui/login").status_code == 200
    page = client.get("/ui/login")
    assert page.status_code == 429
    assert page.headers["Retry-After"] == "30"
    assert page.headers["content-type"].startswith("text/html")
    assert "too many requests" in page.text
    assert client.get("/nothing-here").json()["error"]["code"] == "rate_limited"
    assert refusals(caplog) == [
        "someone sent too many requests, the last to /ui/login from testclient: "
        "limited to 2 a minute, refused for 30 seconds"
    ]
    # A health check and a signed-in caller from the same address pass.
    assert client.get("/health").status_code == 200
    assert client.get("/v1/me", headers=bearer_for(services)).status_code == 200


def test_a_bearer_outside_the_api_counts_by_the_address(
    settings: Settings, services: Services
) -> None:
    client, _ = limited(settings, services, signed_in=0, anonymous=2)
    token = bearer_for(services)
    assert client.get("/openapi.json", headers=token).status_code == 200
    assert client.get("/openapi.json", headers=token).status_code == 429


def test_a_wrong_token_is_left_to_the_sign_in_throttle(
    settings: Settings, services: Services
) -> None:
    client, _ = limited(settings, services, signed_in=2, anonymous=2)
    bearer_for(services)  # a service without users answers 503
    wrong = {"Authorization": "Bearer nope"}
    assert [client.get("/v1/me", headers=wrong).status_code for _ in range(10)] == [
        401
    ] * 10
    assert client.get("/v1/me", headers=wrong).status_code == 429


def test_a_ui_session_counts_as_signed_in(
    settings: Settings, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    client, clock = limited(settings, services, signed_in=4, anonymous=0)
    sign_in(client, *browser_admin(services))
    clock.now += 60
    assert [client.get("/ui").status_code for _ in range(2)] == [200, 200]
    page = client.get("/ui")
    assert page.status_code == 429
    assert page.headers["Retry-After"] == "15"
    [line] = refusals(caplog)
    assert line.startswith("admin (usr_")
    # Its files are not counted.
    assert client.get("/ui/static/css/app.css").status_code == 200


def test_every_operation_of_the_api_checks_the_credential() -> None:
    """The limit leaves a bearer token under /v1 to the route, so every
    route there must check it."""
    schema = create_app().openapi()
    unchecked = [
        f"{method} {path}"
        for path, operations in schema["paths"].items()
        if path.startswith(API_PREFIX)
        for method, operation in operations.items()
        if method in METHODS and {"bearerAuth": []} not in operation.get("security", [])
    ]
    assert unchecked == []


def test_zero_switches_a_limit_off() -> None:
    buckets = Buckets(0)
    assert all(buckets.take("a") is None for _ in range(1000))


def test_the_callers_are_capped() -> None:
    clock = Clock()
    buckets = Buckets(2, clock, max_callers=2)
    assert buckets.take("a") is None
    assert buckets.take("a") is not None
    buckets.take("b")
    buckets.take("c")
    # "a" was forgotten and starts afresh.
    assert buckets.take("a") is None


def test_the_limits_come_from_the_settings() -> None:
    made = RequestLimits.of(
        Settings(rate_limit_per_minute=7, rate_limit_anonymous_per_minute=3)
    )
    assert (made.signed_in.per_minute, made.anonymous.per_minute) == (7, 3)
