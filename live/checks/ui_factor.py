"""The second factor through the UI, the API and the host: a user of the
check's own adds two devices from the keys beside their QR codes,
renames one, signs in with a code of each and with a recovery code,
makes new codes and removes its devices. An administrator removes one
device and then all from the user's page, the host all with
`users reset-second-factor`. Nothing here touches a mailbox."""

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
CODES = r"<li>([0-9A-Z]{5}-[0-9A-Z]{5}-[0-9A-Z]{5})</li>"
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
        """The next code not shown before. The service takes one step
        ahead at most: a later one waits for its time, as a person waits
        for the app's next code."""
        step = max(totp.step_of(datetime.now(UTC)), self._last + 1)
        ahead = step - 1 - totp.step_of(datetime.now(UTC))
        if ahead > 0:
            time.sleep(ahead * totp.STEP_SECONDS - time.time() % totp.STEP_SECONDS + 1)
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
                phone, codes = _add(run, own, "Phone", password)
            if phone is None:
                return
            tablet, codes = _two_devices(run, url, api, user["id"], password, phone)
            if tablet is not None and codes:
                _remove_own(run, url, api, user["id"], password, tablet, codes)
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


def _add(
    run: Run, own: httpx.Client, name: str, password: str, code: str = ""
) -> tuple[App | None, list[str]]:
    """A device added on the page Second factor: its app, and the recovery
    codes the first one brings."""
    page = own.get("/ui/second-factor")
    first = "No device yet" in page.text
    scan = own.post(
        "/ui/second-factor/totp/begin",
        data={
            "csrf_token": csrf_of(page.text),
            "name": name,
            "password": password,
            "code": code,
        },
    )
    key = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', scan.text)
    if not run.check(
        f"adding {name} shows a QR code and the key",
        'src="data:image/svg+xml' in scan.text and key is not None,
    ):
        return None, []
    assert key is not None
    app = App(totp.from_base32(key.group(1).replace(" ", "")))
    if first:
        wrong = own.post(
            "/ui/second-factor/totp/confirm",
            data={"csrf_token": csrf_of(scan.text), "code": "000000"},
        )
        run.check(
            "a wrong first code is refused", "the code is not right" in wrong.text
        )
    done = own.post(
        "/ui/second-factor/totp/confirm",
        data={"csrf_token": csrf_of(scan.text), "code": app.code()},
    )
    codes = re.findall(CODES, done.text)
    if first:
        run.check(
            f"the first device, {name}, turns it on with ten recovery codes once",
            "Second factor on." in done.text
            and len(codes) == 10
            and codes[0] not in own.get("/ui/second-factor").text,
        )
        run.check(
            "and offers them as a text file",
            'href="data:text/plain;charset=utf-8,' in done.text
            and 'download="mailbox-recovery-codes.txt"' in done.text,
        )
    else:
        run.check(
            f"{name} is added, without recovery codes",
            f"Device {name} added." in done.text and not codes,
        )
    return app, codes


def _code_page(browser: httpx.Client, code: str) -> httpx.Response:
    page = browser.get("/ui/login/code")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    return browser.post(
        "/ui/login/code",
        data={"code": code, "nonce": nonce.group(1) if nonce else ""},
    )


def _devices(api: httpx.Client, user_id: str) -> dict[str, str]:
    """The user's devices as the API lists them: name to id."""
    answer = api.get(f"/v1/users/{user_id}/second-factor").json()
    return {d["name"]: d["id"] for d in answer.get("totp", [])}


def _two_devices(
    run: Run, url: str, api: httpx.Client, user_id: str, password: str, phone: App
) -> tuple[App | None, list[str]]:
    """Signed in with the phone, a tablet added with its code and renamed,
    new recovery codes. Then a code of the tablet and a recovery code sign
    in. Returns the tablet and the recovery codes left."""
    with _browser(url) as browser:
        asked = ui_sign_in(browser, NAME, password)
        run.check(
            "the password alone leads to the code page",
            asked.url.path == "/ui/login/code",
        )
        wrong = _code_page(browser, "000000")
        run.check("a wrong code comes back to it", "Wrong code" in wrong.text)
        signed = _code_page(browser, phone.code())
        run.check(
            "the code of Phone signs in",
            signed.url.path == "/ui" and "Signed in as" in signed.text,
        )
        tablet, _ = _add(run, browser, "Tablet", password, phone.code())
        page = browser.get("/ui/second-factor")
        renamed = browser.post(
            "/ui/second-factor/totp/rename",
            data={
                "csrf_token": csrf_of(page.text),
                "device": _devices(api, user_id).get("Tablet", ""),
                "name": "Tablet 2",
            },
        )
        run.check("rename the tablet", "Device renamed." in renamed.text)
        run.check(
            "the API lists both devices",
            set(_devices(api, user_id)) == {"Phone", "Tablet 2"},
        )
        fresh = browser.post(
            "/ui/second-factor/codes",
            data={
                "csrf_token": csrf_of(renamed.text),
                "password": password,
                "code": phone.code(),
            },
        )
        codes = re.findall(CODES, fresh.text)
        run.check("new recovery codes", len(codes) == 10)
    if tablet is None:
        return None, []
    with _browser(url) as browser:
        ui_sign_in(browser, NAME, password)
        signed = _code_page(browser, tablet.code())
        run.check("a code of Tablet 2 signs in", signed.url.path == "/ui")
    with _browser(url) as browser:
        ui_sign_in(browser, NAME, password)
        signed = _code_page(browser, codes[0].lower() if codes else "")
        run.check("a recovery code signs in", signed.url.path == "/ui")
    return tablet, codes[1:]


def _remove_own(
    run: Run,
    url: str,
    api: httpx.Client,
    user_id: str,
    password: str,
    tablet: App,
    codes: list[str],
) -> None:
    """The phone removed with a code of the tablet, then the tablet, the
    last one, with a recovery code."""
    with _browser(url) as browser:
        ui_sign_in(browser, NAME, password)
        _code_page(browser, codes[0])
        devices = _devices(api, user_id)
        page = browser.get("/ui/second-factor")
        removed = browser.post(
            "/ui/second-factor/totp/remove",
            data={
                "csrf_token": csrf_of(page.text),
                "device": devices.get("Phone", ""),
                "password": password,
                "code": tablet.code(),
            },
        )
        run.check(
            "its owner removes Phone with the password and a code of Tablet 2",
            "Device removed." in removed.text
            and set(_devices(api, user_id)) == {"Tablet 2"},
        )
        last = browser.post(
            "/ui/second-factor/totp/remove",
            data={
                "csrf_token": csrf_of(removed.text),
                "device": devices.get("Tablet 2", ""),
                "password": password,
                "code": codes[1],
            },
        )
        run.check(
            "and the last one with a recovery code: the factor is off",
            "The second factor is off." in last.text,
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
    """Two devices anew: the administrator removes one on the user's page,
    then every one. One device anew: the host removes it."""
    with _browser(url) as own:
        ui_sign_in(own, NAME, password)
        _, codes = _add(run, own, "Phone", password)
        _add(run, own, "Tablet", password, codes[0] if codes else "")
    shown = api.get(f"/v1/users/{user_id}").json()
    run.check("the API says it has one", shown.get("second_factor") is True)
    page = browser.get(f"/ui/users/{user_id}?tab=access")
    run.check(
        "the user's page lists the devices",
        '<td class="name">Phone</td>' in page.text
        and '<td class="name">Tablet</td>' in page.text,
    )
    phone = _devices(api, user_id).get("Phone", "")
    one = browser.post(
        f"/ui/users/{user_id}/second-factor/totp/{phone}/remove",
        data={"csrf_token": csrf_of(page.text)},
    )
    run.check(
        "the administrator removes one device",
        "Device removed." in one.text and set(_devices(api, user_id)) == {"Tablet"},
    )
    every = browser.post(
        f"/ui/users/{user_id}/second-factor/remove",
        data={"csrf_token": csrf_of(one.text)},
    )
    run.check("and then every device", "Second factor removed." in every.text)
    gone = api.delete(f"/v1/users/{user_id}/second-factor")
    run.check("then the API finds none", gone.status_code == 404)

    with _browser(url) as own:
        ui_sign_in(own, NAME, password)
        _add(run, own, "Phone", password)
    host = subprocess.run(
        [program("benethos-mailbox-service"), "users", "reset-second-factor", NAME],
        env=env,
        cwd=run_dir(env),
        capture_output=True,
        text=True,
    )
    shown = api.get(f"/v1/users/{user_id}").json()
    run.check(
        "the host removes it with users reset-second-factor",
        host.returncode == 0 and shown.get("second_factor") is False,
        host.stderr.strip()[-200:] if host.returncode else "",
    )
    audit = api.get("/v1/audit", params={"record": user_id, "limit": 100}).json()
    kinds = {(i["activity"], i["credential"]) for i in audit.get("items", [])}
    wanted = {
        ("users.totp_added", "password"),
        ("users.totp_renamed", "password"),
        ("users.totp_removed", "password"),
        ("users.factor_removed", "host"),
        ("auth.recovery_code_used", "password+recovery"),
        ("users.codes_renewed", "password"),
    }
    run.check(
        "the audit names the devices, the sign-ins and the removals",
        wanted <= kinds,
        ", ".join(sorted(str(k) for k in wanted - kinds)),
    )
    signed = api.get(
        "/v1/audit", params={"activity": "auth.signed_in", "limit": 100}
    ).json()
    details = [i["detail"] for i in signed.get("items", [])]
    run.check(
        "and the sign-ins with the code of each device",
        "signed in to the UI with a code of Phone" in details
        and "signed in to the UI with a code of Tablet 2" in details,
    )
