"""Passkeys in the UI: made on the page Second factor, signing in after
the password, standing in for a code, and removed (docs/AUTHENTICATION.md
4, 5). The browser's part is a passkey in software."""

from __future__ import annotations

import html
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ActivityFilter, Grant

from ...conftest import ADMIN, UI_PASSWORD, browser_user
from ...passkey_fake import Authenticator
from ...ui_helpers import post, sign_in, try_sign_in

pytestmark = pytest.mark.usefixtures("master_key")

READER = Grant(accounts=["*"], allow=["mail.read"])
ORIGIN = "https://mail.example.org"


@pytest.fixture
def at_https(master_key: None, services: Services) -> TestClient:
    """A browser at the service at a name over HTTPS, where browsers make
    passkeys. Signed in to nothing yet."""
    services.vault.initialize()
    return TestClient(
        create_app(Settings(storage="memory", public_url=ORIGIN), services)
    )


def options(page: httpx.Response | str, kind: str = "options") -> str:
    """The options the page hands the browser: to sign with a passkey,
    or with ``create`` to make one."""
    text = page if isinstance(page, str) else page.text
    found = re.search(rf'data-passkey-{kind}="([^"]+)"', text)
    assert found is not None, f"no data-passkey-{kind} on the page"
    return html.unescape(found.group(1))


def make(client: TestClient, device: Authenticator, name: str, **proof: str) -> str:
    """A passkey made the way the page makes it: the page it lands on."""
    begun = post(
        client,
        "/ui/second-factor/passkeys/begin",
        {"name": name, "password": UI_PASSWORD, **proof},
    )
    assert begun.status_code == 200, begun.text
    answer = device.create(options(begun, "create"))
    made = post(client, "/ui/second-factor/passkeys/confirm", {"answer": answer})
    assert made.status_code == 200
    return made.text


def signed_up(at_https: TestClient, services: Services) -> tuple[str, Authenticator]:
    """A reader signed in, with the passkey Laptop: its name."""
    name, password = browser_user(services, READER)
    sign_in(at_https, name, password)
    laptop = Authenticator(origin=ORIGIN)
    page = make(at_https, laptop, "Laptop")
    assert "Second factor on." in page
    assert len(re.findall(r"<li>[0-9A-Z]{5}-[0-9A-Z]{5}-[0-9A-Z]{5}</li>", page)) == 10
    return name, laptop


def code_page(client: TestClient, page: str, **data: str) -> str:
    """The code page shown as ``page``, sent as a browser sends it:
    where it leads."""
    nonce = re.search(r'name="nonce" value="([^"]+)"', page)
    assert nonce is not None
    answer = client.post(
        "/ui/login/code",
        data={"nonce": nonce.group(1), "code": "", **data},
        follow_redirects=False,
    )
    assert answer.status_code == 303
    return str(answer.headers["location"])


def credentials(services: Services) -> list[str]:
    found = services.audit.list_activity(
        ADMIN, limit=50, matching=ActivityFilter(activity="auth.signed_in")
    )
    return [record.credential or "" for record in found.items]


def test_a_passkey_is_made_on_the_page(
    at_https: TestClient, services: Services
) -> None:
    name, _ = signed_up(at_https, services)
    page = at_https.get("/ui/second-factor").text
    assert '<td class="name">Laptop</td>' in page
    assert '<script src="/ui/static/js/passkey.js" defer></script>' in page
    user = services.auth.user_named(name)
    assert user is not None
    assert [p.name for p in services.factors.of(ADMIN, user.id).passkeys] == ["Laptop"]
    # The session that made it carries on.
    assert at_https.get("/ui").status_code == 200


def test_a_passkey_signs_in_after_the_password(
    at_https: TestClient, services: Services
) -> None:
    name, laptop = signed_up(at_https, services)
    browser = TestClient(at_https.app)
    landed = try_sign_in(browser, name, UI_PASSWORD, next="/ui/mail")
    assert landed.headers["location"] == "/ui/login/code"
    page = browser.get("/ui/login/code").text
    # The passkey first, the others listed after "Try another way".
    assert 'data-way="passkey"' in page and 'data-way-pick="passkey"' in page
    assert 'data-way-pick="recovery"' in page and "A recovery code" in page
    assert 'data-way="totp"' not in page
    answer = laptop.get(options(page))
    assert code_page(browser, page, passkey=answer) == "/ui/mail"
    assert browser.get("/ui").status_code == 200
    assert credentials(services)[0] == "password+passkey"


def test_a_passkey_answer_counts_once(at_https: TestClient, services: Services) -> None:
    name, laptop = signed_up(at_https, services)
    browser = TestClient(at_https.app)
    try_sign_in(browser, name, UI_PASSWORD)
    answer = laptop.get(options(browser.get("/ui/login/code")))
    # The page shown again offers a new challenge: the old answer is void.
    again = browser.get("/ui/login/code").text
    assert code_page(browser, again, passkey=answer) == "/ui/login/code?wrong=1"
    page = browser.get("/ui/login/code?wrong=1").text
    assert "Wrong code or passkey" in page
    assert code_page(browser, page, passkey=laptop.get(options(page))) == "/ui"


def test_a_passkey_of_another_origin_does_not_sign_in(
    at_https: TestClient, services: Services
) -> None:
    name, laptop = signed_up(at_https, services)
    browser = TestClient(at_https.app)
    try_sign_in(browser, name, UI_PASSWORD)
    laptop.origin = "https://evil.example"
    page = browser.get("/ui/login/code").text
    answer = laptop.get(options(page))
    assert code_page(browser, page, passkey=answer) == "/ui/login/code?wrong=1"


def test_a_passkey_stands_in_for_a_code(
    at_https: TestClient, services: Services
) -> None:
    _, laptop = signed_up(at_https, services)
    page = at_https.get("/ui/second-factor")
    renewed = post(
        at_https,
        "/ui/second-factor/codes",
        {"password": UI_PASSWORD, "passkey": laptop.get(options(page))},
    )
    assert "New recovery codes." in renewed.text
    # A second passkey, confirmed with the first.
    page = at_https.get("/ui/second-factor")
    made = make(
        at_https,
        Authenticator(origin=ORIGIN),
        "Key",
        passkey=laptop.get(options(page)),
    )
    assert "Passkey Key added." in made
    assert '<td class="name">Key</td>' in made


def test_a_passkey_is_renamed_and_removed(
    at_https: TestClient, services: Services
) -> None:
    name, laptop = signed_up(at_https, services)
    user = services.auth.user_named(name)
    assert user is not None
    [passkey] = services.factors.of(ADMIN, user.id).passkeys
    renamed = post(
        at_https,
        "/ui/second-factor/passkeys/rename",
        {"device": passkey.id, "name": "Work laptop"},
    )
    assert "Passkey renamed." in renamed.text
    page = at_https.get("/ui/second-factor")
    removed = post(
        at_https,
        "/ui/second-factor/passkeys/remove",
        {
            "device": passkey.id,
            "password": UI_PASSWORD,
            "passkey": laptop.get(options(page)),
        },
    )
    assert "Passkey removed. The second factor is off." in removed.text
    assert not services.factors.has(user.id)


def test_an_administrator_removes_a_passkey(
    ui: TestClient, at_https: TestClient, services: Services
) -> None:
    anna = at_https
    name, _ = signed_up(anna, services)
    user = services.auth.user_named(name)
    assert user is not None
    page = ui.get(f"/ui/users/{user.id}?tab=access").text
    assert "<td>Passkey</td>" in page
    [passkey] = services.factors.of(ADMIN, user.id).passkeys
    removed = post(
        ui, f"/ui/users/{user.id}/second-factor/passkeys/{passkey.id}/remove"
    )
    assert "Passkey removed." in removed.text
    assert not services.factors.has(user.id)
    assert anna.get("/ui", follow_redirects=False).status_code == 303


def test_a_setup_without_an_answer_stores_nothing(
    at_https: TestClient, services: Services
) -> None:
    name, password = browser_user(services, READER)
    sign_in(at_https, name, password)
    post(
        at_https,
        "/ui/second-factor/passkeys/begin",
        {"name": "Laptop", "password": UI_PASSWORD},
    )
    page = post(at_https, "/ui/second-factor/passkeys/confirm", {"answer": ""})
    assert "No passkey was made." in page.text
    elsewhere = Authenticator(origin="https://evil.example")
    begun = post(
        at_https,
        "/ui/second-factor/passkeys/begin",
        {"name": "Laptop", "password": UI_PASSWORD},
    )
    answer = elsewhere.create(options(begun, "create"))
    refused = post(at_https, "/ui/second-factor/passkeys/confirm", {"answer": answer})
    assert "not created" in refused.text
    user = services.auth.user_named(name)
    assert user is not None
    assert not services.factors.has(user.id)


def test_a_cancelled_setup_is_gone(at_https: TestClient, services: Services) -> None:
    name, password = browser_user(services, READER)
    sign_in(at_https, name, password)
    post(
        at_https,
        "/ui/second-factor/passkeys/begin",
        {"name": "Laptop", "password": UI_PASSWORD},
    )
    page = post(at_https, "/ui/second-factor/passkeys/cancel")
    assert "data-passkey-create" not in page.text
    late = post(at_https, "/ui/second-factor/passkeys/confirm", {"answer": "{}"})
    assert "The setup ran out." in late.text


def test_without_https_the_page_offers_no_passkey(services: Services) -> None:
    """At an address over HTTP a browser makes none: the page says so."""
    services.vault.initialize()
    plain = TestClient(create_app(Settings(storage="memory"), services))
    name, password = browser_user(services, READER)
    sign_in(plain, name, password)
    page = plain.get("/ui/second-factor").text
    assert "Passkeys work at a name over HTTPS" in page
    assert "add-passkey" not in page
    refused = post(
        plain,
        "/ui/second-factor/passkeys/begin",
        {"name": "Laptop", "password": UI_PASSWORD},
    )
    assert "Passkeys work at a name over HTTPS, or at localhost" in refused.text
