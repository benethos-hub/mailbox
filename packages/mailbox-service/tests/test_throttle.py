"""Guessed credentials are slowed down (CONCEPT 7.5): the throttle alone,
and through the API and the UI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.domain.throttle import SignInThrottle
from benethos_mailbox_service.errors import RateLimitedError
from benethos_mailbox_service.main import create_app

from .conftest import API_KEY

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def tick(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def throttle(clock: Clock) -> SignInThrottle:
    return SignInThrottle(
        limit=3,
        window=timedelta(minutes=15),
        lockout=timedelta(minutes=15),
        max_sources=2,
        clock=clock,
    )


def test_below_the_limit_nothing_happens(throttle: SignInThrottle) -> None:
    throttle.failed("a")
    throttle.failed("a")
    throttle.check("a")


def test_the_limit_locks_the_source_out(throttle: SignInThrottle, clock: Clock) -> None:
    for _ in range(3):
        throttle.failed("a")
    with pytest.raises(RateLimitedError) as caught:
        throttle.check("a")
    assert caught.value.retry_after == 15 * 60
    # Another source is not affected.
    throttle.check("b")
    clock.tick(minutes=14)
    with pytest.raises(RateLimitedError) as caught:
        throttle.check("a")
    assert caught.value.retry_after == 60
    clock.tick(minutes=1)
    throttle.check("a")


def test_old_failures_leave_the_window(throttle: SignInThrottle, clock: Clock) -> None:
    throttle.failed("a")
    throttle.failed("a")
    clock.tick(minutes=16)
    throttle.failed("a")
    throttle.check("a")


def test_success_clears_the_source(throttle: SignInThrottle) -> None:
    throttle.failed("a")
    throttle.failed("a")
    throttle.succeeded("a")
    throttle.failed("a")
    throttle.failed("a")
    throttle.check("a")
    throttle.failed("a")
    with pytest.raises(RateLimitedError):
        throttle.check("a")
    throttle.succeeded("a")
    throttle.check("a")


def test_the_number_of_sources_is_capped(throttle: SignInThrottle) -> None:
    for _ in range(2):
        throttle.failed("a")
    throttle.failed("b")
    throttle.failed("c")
    # The failures of the oldest source were forgotten: one more does not
    # lock it.
    throttle.failed("a")
    throttle.check("a")


def test_a_flood_of_sources_frees_no_locked_one(
    throttle: SignInThrottle, clock: Clock
) -> None:
    for _ in range(3):
        throttle.failed("a")
    for source in "bcdef":
        throttle.failed(source)
    with pytest.raises(RateLimitedError):
        throttle.check("a")
    # Lockouts are capped as well: those that ran out go first.
    clock.tick(minutes=16)
    for source in "xy":
        for _ in range(3):
            throttle.failed(source)
    for source in "xy":
        with pytest.raises(RateLimitedError):
            throttle.check(source)
    for _ in range(3):
        throttle.failed("z")
    assert set(throttle._locked) == {"y", "z"}


def test_a_bad_limit_is_refused() -> None:
    with pytest.raises(ValueError):
        SignInThrottle(limit=0)


# --- through the API ------------------------------------------------------------


def test_the_api_locks_a_guessing_client_out(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    for _ in range(10):
        wrong = client.get("/v1/accounts", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
    locked = client.get("/v1/accounts", headers={"Authorization": "Bearer nope"})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "rate_limited"
    assert int(locked.headers["Retry-After"]) > 0
    # While locked, the right key is not even looked at.
    right = client.get("/v1/accounts", headers={"Authorization": f"Bearer {API_KEY}"})
    assert right.status_code == 429


def test_a_missing_token_is_no_guess(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    for _ in range(12):
        assert client.get("/v1/accounts").status_code == 401


def test_a_successful_sign_in_clears_the_count(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    for _ in range(9):
        client.get("/v1/accounts", headers={"Authorization": "Bearer nope"})
    ok = client.get("/v1/accounts", headers={"Authorization": f"Bearer {API_KEY}"})
    assert ok.status_code == 200
    for _ in range(9):
        client.get("/v1/accounts", headers={"Authorization": "Bearer nope"})
    ok = client.get("/v1/accounts", headers={"Authorization": f"Bearer {API_KEY}"})
    assert ok.status_code == 200


# --- through the UI, the same throttle ------------------------------------------


def test_the_ui_says_when_a_client_is_locked_out(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    for _ in range(10):
        page = client.get("/ui/login")
        nonce = page.text.split('name="nonce" value="')[1].split('"')[0]
        client.post("/ui/login", data={"token": "nope", "nonce": nonce})
    page = client.get("/ui/login")
    nonce = page.text.split('name="nonce" value="')[1].split('"')[0]
    answer = client.post("/ui/login", data={"token": API_KEY, "nonce": nonce})
    assert "Too many failed attempts" in answer.text
    assert "Try again in 15 minutes" in answer.text
    assert "mailbox_ui_session" not in client.cookies


def test_a_wrong_token_on_the_api_counts_for_the_ui_too(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    for _ in range(10):
        client.get("/v1/accounts", headers={"Authorization": "Bearer nope"})
    page = client.get("/ui/login")
    nonce = page.text.split('name="nonce" value="')[1].split('"')[0]
    answer = client.post("/ui/login", data={"token": API_KEY, "nonce": nonce})
    assert "Too many failed attempts" in answer.text
    assert "mailbox_ui_session" not in client.cookies
