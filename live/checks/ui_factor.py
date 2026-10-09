"""The second factor through the UI, the API and the host: a user of the
check's own sets one up from the QR code's key, signs in with a code and
with a recovery code, makes new codes and removes it. An administrator
removes it from the user's page, the host with `users reset-totp`.
Nothing here touches a mailbox."""

from __future__ import annotations

import re
import secrets
import subprocess
import time
from datetime import UTC, datetime

import httpx

from benethos_mailbox_service.data.secrets import totp

from .admin import Admin, csrf_of, ui_sign_in
from .processes import program, run_dir
from .run import Run

NAME = "ui-live-factor"
CODES = r"<li>([0-9A-Z]{5}-[0-9A-Z]{5})</li>"
# The longest pause taken for the limit on requests without a credential.
LONGEST_WAIT = 65


class _Patient(httpx.HTTPTransport):
    """A browser that waits when told: the many sign-ins of this check meet
    the limit of 30 requests a minute without a credential, a person's do
    not. A refused request did nothing, so it is sent again."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for _ in range(3):
            answer = super().handle_request(request)
            if answer.status_code != 429:
                return answer
            answer.read()
            wait = int(answer.headers.get("retry-after", "5"))
            time.sleep(min(wait, LONGEST_WAIT))
        return answer


def _browser(url: str) -> httpx.Client:
    return httpx.Client(
        base_url=url, timeout=60, follow_redirects=True, transport=_Patient()
    )


class App:
    """The authenticator app: it holds the secret and never shows a code
    twice, as the service takes each step once."""

    def __init__(self, secret: bytes) -> None:
        self._secret = secret
        self._last = -1

    def code(self) -> str:
        step = max(totp.step_of(datetime.now(UTC)), self._last + 1)
        self._last = step
        return totp.code(self._secret, step)


def check_second_factor(
    run: Run, url: str, admin: Admin, browser: httpx.Client, env: dict[str, str]
) -> None:
    with httpx.Client(
        base_url=url, headers={"Authorization": f"Bearer {admin.token}"}, timeout=30
    ) as api:
        user = api.post("/v1/users", json={"name": NAME, "ui_sign_in": True}).json()
        one_time = api.post(f"/v1/users/{user['id']}/password", json={}).json()
        password = secrets.token_urlsafe(18)
        try:
            with _browser(url) as own:
                _choose_password(own, one_time["password"], password)
                app = _set_up(run, own, password)
                if app is None:
                    return
                codes = _sign_in_with_codes(run, url, password, app)
                if codes:
                    _remove_own(run, url, password, codes)
            _removed_by_others(run, url, api, browser, password, user["id"], env)
        finally:
            api.delete(f"/v1/users/{user['id']}")


def _choose_password(own: httpx.Client, one_time: str, password: str) -> None:
    asked = ui_sign_in(own, NAME, one_time)
    own.post(
        "/ui/password",
        data={
            "csrf_token": csrf_of(asked.text),
            "current_password": one_time,
            "new_password": password,
            "repeat_password": password,
        },
    )


def _set_up(run: Run, own: httpx.Client, password: str) -> App | None:
    """The page Second factor, from the password to the recovery codes."""
    page = own.get("/ui/second-factor")
    run.check("the page Second factor offers the setup", "Off now" in page.text)
    scan = own.post(
        "/ui/second-factor/begin",
        data={"csrf_token": csrf_of(page.text), "password": password},
    )
    key = re.search(r'<code class="secret">([^<]+)</code>', scan.text)
    if not run.check(
        "it shows a QR code and the key",
        'src="data:image/svg+xml' in scan.text and key is not None,
    ):
        return None
    assert key is not None
    app = App(totp.from_base32(key.group(1).replace(" ", "")))
    wrong = own.post(
        "/ui/second-factor/confirm",
        data={"csrf_token": csrf_of(scan.text), "code": "000000"},
    )
    run.check("a wrong first code is refused", "the code is not right" in wrong.text)
    done = own.post(
        "/ui/second-factor/confirm",
        data={"csrf_token": csrf_of(scan.text), "code": app.code()},
    )
    codes = re.findall(CODES, done.text)
    run.check(
        "the first code turns it on and shows ten recovery codes once",
        "Second factor on." in done.text
        and len(codes) == 10
        and codes[0] not in own.get("/ui/second-factor").text,
    )
    return app


def _code_page(browser: httpx.Client, code: str) -> httpx.Response:
    page = browser.get("/ui/login/code")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    return browser.post(
        "/ui/login/code",
        data={"code": code, "nonce": nonce.group(1) if nonce else ""},
    )


def _sign_in_with_codes(run: Run, url: str, password: str, app: App) -> list[str]:
    """A code of the app, then a recovery code of a new set. Returns the
    codes of that set left."""
    with _browser(url) as browser:
        asked = ui_sign_in(browser, NAME, password)
        run.check(
            "the password alone leads to the code page",
            asked.url.path == "/ui/login/code",
        )
        wrong = _code_page(browser, "000000")
        run.check("a wrong code comes back to it", "Wrong code" in wrong.text)
        signed = _code_page(browser, app.code())
        run.check(
            "the code of the app signs in",
            signed.url.path == "/ui" and "Signed in as" in signed.text,
        )
        page = browser.get("/ui/second-factor")
        fresh = browser.post(
            "/ui/second-factor/codes",
            data={"csrf_token": csrf_of(page.text), "password": password},
        )
        codes = re.findall(CODES, fresh.text)
        run.check("new recovery codes", len(codes) == 10)
    with _browser(url) as browser:
        ui_sign_in(browser, NAME, password)
        signed = _code_page(browser, codes[0].lower() if codes else "")
        run.check("a recovery code signs in", signed.url.path == "/ui")
    return codes[1:]


def _remove_own(run: Run, url: str, password: str, codes: list[str]) -> None:
    with _browser(url) as browser:
        ui_sign_in(browser, NAME, password)
        _code_page(browser, codes[0])
        page = browser.get("/ui/second-factor")
        removed = browser.post(
            "/ui/second-factor/remove",
            data={
                "csrf_token": csrf_of(page.text),
                "password": password,
                "code": codes[1],
            },
        )
        run.check(
            "its owner removes it with the password and a recovery code",
            "Second factor removed." in removed.text,
        )
    with _browser(url) as browser:
        again = ui_sign_in(browser, NAME, password)
        run.check("then the password alone signs in", again.url.path == "/ui")


def _removed_by_others(
    run: Run,
    url: str,
    api: httpx.Client,
    browser: httpx.Client,
    password: str,
    user_id: str,
    env: dict[str, str],
) -> None:
    """Set up anew twice: removed by the administrator in the UI, then by
    the host."""
    with _browser(url) as own:
        ui_sign_in(own, NAME, password)
        _set_up(run, own, password)
    shown = api.get(f"/v1/users/{user_id}").json()
    run.check("the API says it has one", shown.get("second_factor") is True)
    page = browser.get(f"/ui/users/{user_id}")
    removed = browser.post(
        f"/ui/users/{user_id}/second-factor/remove",
        data={"csrf_token": csrf_of(page.text)},
    )
    run.check(
        "the administrator removes it on the user's page",
        "Second factor removed." in removed.text,
    )
    gone = api.delete(f"/v1/users/{user_id}/second-factor")
    run.check("then the API finds none", gone.status_code == 404)

    with _browser(url) as own:
        ui_sign_in(own, NAME, password)
        _set_up(run, own, password)
    host = subprocess.run(
        [program("benethos-mailbox-service"), "users", "reset-totp", NAME],
        env=env,
        cwd=run_dir(env),
        capture_output=True,
        text=True,
    )
    shown = api.get(f"/v1/users/{user_id}").json()
    run.check(
        "the host removes it with users reset-totp",
        host.returncode == 0 and shown.get("second_factor") is False,
        host.stderr.strip()[-200:] if host.returncode else "",
    )
    audit = api.get("/v1/audit", params={"record": user_id, "limit": 50}).json()
    kinds = [(i["activity"], i["credential"]) for i in audit.get("items", [])]
    run.check(
        "the audit names the setup, the sign-ins and the removals",
        ("users.factor_set_up", "password") in kinds
        and ("users.factor_removed", "host") in kinds
        and ("auth.recovery_code_used", "password+recovery") in kinds
        and ("users.codes_renewed", "password") in kinds,
    )
    signed = api.get("/v1/audit", params={"activity": "auth.signed_in"}).json()
    run.check(
        "and a sign-in with the app's code",
        any(i["credential"] == "password+totp" for i in signed.get("items", [])),
    )
