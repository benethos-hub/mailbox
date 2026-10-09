"""The second factor in the UI: the code after the password, the page of
the devices, and their removal (docs/AUTHENTICATION.md)."""

from __future__ import annotations

import asyncio
import html
import re
from datetime import UTC, datetime
from urllib.parse import unquote

import httpx
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import ActivityFilter, Grant, User
from benethos_mailbox_service.data.secrets import encode_recovery, totp

from ...conftest import ADMIN, UI_PASSWORD, browser_admin, browser_user
from ...ui_helpers import post, sign_in, try_sign_in

pytestmark = pytest.mark.usefixtures("master_key")

READER = Grant(accounts=["*"], allow=["mail.read"])
CODES = r"<li>([0-9A-Z]{5}-[0-9A-Z]{5}-[0-9A-Z]{5})</li>"


@pytest.fixture(autouse=True)
def keys(master_key: None, services: Services) -> None:
    services.vault.initialize()


def code_after(secret: bytes, steps: int = 1) -> str:
    """A code of a step after the current one: the current one may be
    taken already, by the setup."""
    return totp.code(secret, totp.step_of(datetime.now(UTC)) + steps)


def user_named(services: Services, name: str) -> User:
    user = services.auth.user_named(name)
    assert user is not None
    return user


def with_factor(services: Services, name: str) -> tuple[bytes, list[str]]:
    """The user of this name adds the device Phone: its secret and the
    recovery codes."""
    access = services.auth.access_of(user_named(services, name).id)
    assert access is not None
    kept, secret = asyncio.run(services.totp.begin(access, "Phone", UI_PASSWORD))
    codes, _ = services.totp.confirm(access, kept, secret, code_after(secret, 0))
    return secret, codes


def code_form(client: TestClient, code: str) -> str:
    """The code page sent as a browser sends it: where it leads."""
    page = client.get("/ui/login/code")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    answer = client.post(
        "/ui/login/code",
        data={"code": code, "nonce": nonce.group(1)},
        follow_redirects=False,
    )
    assert answer.status_code == 303
    return str(answer.headers["location"])


def scanned(page: httpx.Response) -> bytes:
    """The secret of the key beside the QR code."""
    key = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', page.text)
    assert key is not None
    return totp.from_base32(key.group(1).replace(" ", ""))


def device_ids(services: Services, name: str) -> dict[str, str]:
    devices = services.factors.of(ADMIN, user_named(services, name).id).totp
    return {d.name: d.id for d in devices}


def credentials(services: Services) -> list[str]:
    found = services.audit.list_activity(
        ADMIN, limit=50, matching=ActivityFilter(activity="auth.signed_in")
    )
    return [record.credential or "" for record in found.items]


# --- signing in -----------------------------------------------------------------


def test_the_code_comes_after_the_password(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    secret, _ = with_factor(services, name)
    landed = try_sign_in(app_client, name, password, next="/ui/mail")
    assert landed.headers["location"] == "/ui/login/code"
    # No session yet: every other page leads to the sign-in.
    assert (
        app_client.get("/ui", follow_redirects=False)
        .headers["location"]
        .startswith("/ui/login")
    )
    page = app_client.get("/ui/login/code").text
    assert 'autocomplete="one-time-code"' in page
    assert code_form(app_client, code_after(secret)) == "/ui/mail"
    assert app_client.get("/ui").status_code == 200
    assert credentials(services) == ["password+totp"]


def test_a_wrong_code_comes_back_and_the_last_try_ends_it(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    with_factor(services, name)
    try_sign_in(app_client, name, password)
    assert code_form(app_client, "000000") == "/ui/login/code?wrong=1"
    assert "Wrong code" in app_client.get("/ui/login/code?wrong=1").text
    for _ in range(3):
        assert code_form(app_client, "000000") == "/ui/login/code?wrong=1"
    assert code_form(app_client, "000000") == "/ui/login?notice=code_tries"
    assert "Too many wrong codes" in app_client.get("/ui/login?notice=code_tries").text
    gone = app_client.get("/ui/login/code", follow_redirects=False)
    assert gone.headers["location"] == "/ui/login?notice=code_expired"


def test_a_recovery_code_signs_in(app_client: TestClient, services: Services) -> None:
    name, password = browser_user(services, READER)
    _, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    assert code_form(app_client, codes[3].lower()) == "/ui"
    assert credentials(services) == ["password+recovery"]


def test_the_code_page_needs_a_pending_sign_in(app_client: TestClient) -> None:
    gone = app_client.get("/ui/login/code", follow_redirects=False)
    assert gone.headers["location"] == "/ui/login?notice=code_expired"
    sent = app_client.post(
        "/ui/login/code", data={"code": "123456", "nonce": "x"}, follow_redirects=False
    )
    assert sent.headers["location"] == "/ui/login?notice=code_expired"


def test_the_code_form_is_tied_to_its_page(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    secret, _ = with_factor(services, name)
    try_sign_in(app_client, name, password)
    sent = app_client.post(
        "/ui/login/code",
        data={"code": code_after(secret), "nonce": "another"},
        follow_redirects=False,
    )
    assert sent.headers["location"] == "/ui/login?notice=code_expired"


def test_back_at_the_sign_in_the_pending_one_is_given_up(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    with_factor(services, name)
    try_sign_in(app_client, name, password)
    app_client.get("/ui/login")
    gone = app_client.get("/ui/login/code", follow_redirects=False)
    assert gone.headers["location"] == "/ui/login?notice=code_expired"


def test_the_code_before_a_forced_password_change(
    app_client: TestClient, services: Services
) -> None:
    name, _ = browser_user(services, READER)
    secret, _ = with_factor(services, name)
    user = user_named(services, name)
    one_time = asyncio.run(services.passwords.one_time_password(ADMIN, user.id))
    landed = try_sign_in(app_client, name, one_time)
    assert landed.headers["location"] == "/ui/login/code"
    assert code_form(app_client, code_after(secret)) == "/ui/password"


# --- the own page ---------------------------------------------------------------


def test_the_first_device_shows_a_qr_code_then_the_recovery_codes_once(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    sign_in(app_client, name, password)
    assert 'href="/ui/second-factor"' in app_client.get("/ui").text
    page = app_client.get("/ui/second-factor").text
    assert "No device yet" in page and 'name="password"' in page
    # The first device needs no code.
    assert 'id="f-code"' not in page

    wrong = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Phone", "password": "not it at all"},
    )
    assert "the password is not right" in wrong.text

    scan = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Phone", "password": password},
    )
    assert 'src="data:image/svg+xml' in scan.text
    assert "Scan the code for Phone" in scan.text
    secret = scanned(scan)

    refused = post(app_client, "/ui/second-factor/totp/confirm", {"code": "000000"})
    assert "the code is not right" in refused.text
    assert 'src="data:image/svg+xml' in refused.text

    done = post(
        app_client, "/ui/second-factor/totp/confirm", {"code": code_after(secret, 0)}
    )
    assert "Second factor on." in done.text
    codes = re.findall(CODES, done.text)
    assert len(codes) == 10
    again = app_client.get("/ui/second-factor").text
    assert codes[0] not in again
    assert '<td class="name">Phone</td>' in again and "10 left" in again
    # The session that set it up carries on.
    assert app_client.get("/ui").status_code == 200


def test_the_recovery_codes_download_as_a_text_file(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    _, old = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, old[0])
    fresh = post(
        app_client, "/ui/second-factor/codes", {"password": password, "code": old[1]}
    )
    link = re.search(
        r'<a class="btn" href="(data:text/plain;charset=utf-8,[^"]+)"'
        r' download="mailbox-recovery-codes.txt">',
        fresh.text,
    )
    assert link is not None
    text = unquote(link.group(1).split(",", 1)[1])
    codes = re.findall(CODES, fresh.text)
    assert all(code in text.splitlines() for code in codes)
    assert text.startswith(f"Recovery codes of {name} for Mailbox at ")
    # Shown once: the next visit offers neither the codes nor the file.
    assert "data:text/plain" not in app_client.get("/ui/second-factor").text


def test_a_further_device_needs_a_code(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    _, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, codes[0])
    page = app_client.get("/ui/second-factor").text
    assert 'id="f-code"' in page
    refused = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Tablet", "password": password, "code": "000000"},
    )
    assert "the code is not right" in refused.text
    taken = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "phone", "password": password, "code": codes[1]},
    )
    assert "a device named phone exists" in taken.text
    scan = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Tablet", "password": password, "code": codes[2]},
    )
    tablet = scanned(scan)
    done = post(
        app_client, "/ui/second-factor/totp/confirm", {"code": code_after(tablet, 0)}
    )
    assert "Device Tablet added." in done.text
    assert not re.findall(CODES, done.text)
    assert set(device_ids(services, name)) == {"Phone", "Tablet"}


def test_a_device_is_renamed(app_client: TestClient, services: Services) -> None:
    name, password = browser_user(services, READER)
    _, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, codes[0])
    phone = device_ids(services, name)["Phone"]
    renamed = post(
        app_client,
        "/ui/second-factor/totp/rename",
        {"device": phone, "name": "Old phone"},
    )
    assert "Device renamed." in renamed.text
    assert '<td class="name">Old phone</td>' in renamed.text


def test_removing_a_device_needs_password_and_code(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    _, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, codes[0])
    phone = device_ids(services, name)["Phone"]
    refused = post(
        app_client,
        "/ui/second-factor/totp/remove",
        {"device": phone, "password": password, "code": "0"},
    )
    assert "the code is not right" in refused.text
    removed = post(
        app_client,
        "/ui/second-factor/totp/remove",
        {"device": phone, "password": password, "code": codes[1]},
    )
    assert "The second factor is off." in removed.text
    assert "No device yet" in removed.text
    # This session carries on, and the password alone signs in again.
    assert app_client.get("/ui").status_code == 200
    sign_in(TestClient(app_client.app), name, password)


def test_the_qr_code_carries_no_text(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    sign_in(app_client, name, password)
    scan = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Phone", "password": password},
    )
    found = re.search(r'src="(data:image/svg\+xml[^"]+)"', scan.text)
    assert found is not None
    # The image is the code, not the URI: neither name nor secret in it.
    assert name not in html.unescape(found.group(1))


def test_adding_a_device_signs_out_the_other_sessions(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    sign_in(app_client, name, password)
    laptop = TestClient(app_client.app)
    sign_in(laptop, name, password)
    scan = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Phone", "password": password},
    )
    post(
        app_client,
        "/ui/second-factor/totp/confirm",
        {"code": code_after(scanned(scan), 0)},
    )
    assert app_client.get("/ui").status_code == 200
    assert laptop.get("/ui", follow_redirects=False).status_code == 303


def test_a_setup_can_be_cancelled(app_client: TestClient, services: Services) -> None:
    name, password = browser_user(services, READER)
    sign_in(app_client, name, password)
    post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Phone", "password": password},
    )
    page = post(app_client, "/ui/second-factor/totp/cancel")
    assert "data:image/svg+xml" not in page.text and "No device yet" in page.text
    late = post(app_client, "/ui/second-factor/totp/confirm", {"code": "123456"})
    assert "The setup ran out" in late.text


def test_new_recovery_codes_on_the_own_page(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    _, old = with_factor(services, name)
    # Adding a device ended the sessions before: sign in with a code.
    try_sign_in(app_client, name, password)
    code_form(app_client, old[0])
    assert "9 left" in app_client.get("/ui/second-factor").text
    refused = post(
        app_client, "/ui/second-factor/codes", {"password": password, "code": "0"}
    )
    assert "the code is not right" in refused.text
    fresh = post(
        app_client, "/ui/second-factor/codes", {"password": password, "code": old[1]}
    )
    assert "New recovery codes." in fresh.text
    codes = re.findall(CODES, fresh.text)
    assert len(codes) == 10 and not set(codes) & set(old)
    services.repositories.recovery_codes.delete(user_named(services, name).id)
    assert "No recovery codes are left" in app_client.get("/ui/second-factor").text


def test_the_recovery_key_needs_a_code_with_a_second_factor(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_admin(services)
    secret, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, codes[0])
    assert 'name="code"' in app_client.get("/ui/recovery-key").text
    for code in ("", "000000"):
        refused = post(
            app_client, "/ui/recovery-key", {"password": password, "code": code}
        )
        assert "the code is not right" in refused.text
        assert '<code class="secret"' not in refused.text
    shown = post(
        app_client,
        "/ui/recovery-key",
        {"password": password, "code": code_after(secret)},
    )
    key = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', shown.text)
    assert key is not None
    assert key.group(1) == encode_recovery(services.vault.master_key())


# --- another user's page --------------------------------------------------------


def test_an_administrator_removes_a_device_then_every_one(
    ui: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    secret, codes = with_factor(services, name)
    user = user_named(services, name)
    access = services.auth.access_of(user.id)
    assert access is not None
    kept, tablet = asyncio.run(
        services.totp.begin(access, "Tablet", UI_PASSWORD, codes[0])
    )
    services.totp.confirm(access, kept, tablet, code_after(tablet, 0))
    anna = TestClient(ui.app)
    try_sign_in(anna, name, password)
    code_form(anna, code_after(secret))
    page = ui.get(f"/ui/users/{user.id}").text
    assert "a code of an authenticator app after the password" in page
    assert '<td class="name">Phone</td>' in page and "9 recovery codes left" in page
    phone = device_ids(services, name)["Phone"]
    removed = post(ui, f"/ui/users/{user.id}/second-factor/totp/{phone}/remove")
    assert "Device removed." in removed.text
    assert set(device_ids(services, name)) == {"Tablet"}
    assert anna.get("/ui", follow_redirects=False).status_code == 303
    every = post(ui, f"/ui/users/{user.id}/second-factor/remove")
    assert "Second factor removed." in every.text
    assert not services.factors.has(user.id)


def test_a_reader_sees_the_devices_but_removes_none(
    app_client: TestClient, services: Services
) -> None:
    name, _ = browser_user(services, READER)
    with_factor(services, name)
    user = user_named(services, name)
    # It holds the rights of the user it reads, which the page wants.
    sign_in(app_client, *browser_user(services, READER, service=["users.read"]))
    page = app_client.get(f"/ui/users/{user.id}").text
    assert '<td class="name">Phone</td>' in page
    assert "second-factor/remove" not in page and "/totp/" not in page
    refused = post(app_client, f"/ui/users/{user.id}/second-factor/remove")
    assert "missing right: remove_second_factor" in refused.text
    assert services.factors.has(user.id)


def test_the_own_user_page_links_to_the_factor(
    ui: TestClient, services: Services
) -> None:
    # The fixture ``ui`` signed in as the user browser_admin makes.
    me = user_named(services, "admin")
    page = ui.get(f"/ui/users/{me.id}").text
    assert "Set up a second factor" in page
    assert "second-factor/remove" not in page
