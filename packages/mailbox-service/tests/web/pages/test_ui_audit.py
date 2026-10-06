"""The audit of administration in the configuration UI: its page under
Service and the card on a user's page, for ``audit`` in ``service``."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.main import Services

from ...conftest import ADMIN, browser_admin, browser_user
from ...ui_helpers import sign_in

READER = Grant(accounts=["*"], allow=["mail.read"])


def test_the_page_lists_who_did_what(
    app_client: TestClient, services: Services
) -> None:
    sign_in(app_client, *browser_admin(services))
    anna = services.users.create_user(ADMIN, "Anna <b>", [], [READER])
    assert 'href="/ui/audit"' in app_client.get("/ui").text
    page = app_client.get("/ui/audit").text
    assert 'href="/ui/audit" class="active"' in page
    assert "Kept 90 days" in page
    # Its own sign-in, through the UI.
    assert "auth.signed_in" in page
    assert "the UI" in page
    # A name is text, never markup.
    assert "Anna &lt;b&gt;" in page
    assert "Anna <b>" not in page
    assert f'href="/ui/audit?record={anna.id}"' in page
    assert 'class="tag ok">done' in page


def test_the_filter_bar_narrows_the_list(
    app_client: TestClient, services: Services
) -> None:
    sign_in(app_client, *browser_admin(services))
    anna = services.users.create_user(ADMIN, "Anna", [], [READER])
    services.users.create_role(ADMIN, "readers", [READER])

    def rows(**params: str) -> set[str]:
        page = app_client.get("/ui/audit", params=params).text
        return set(re.findall(r'<span class="mono">(\w+\.\w+)</span>', page))

    assert rows(activity="users.role_created") == {"users.role_created"}
    assert rows(activity="users") == {"users.created", "users.role_created"}
    assert rows(record=anna.id) == {"users.created"}
    # The admin of the test made both, the browser's user signed in.
    assert rows(user=ADMIN.user_id) == {"users.created", "users.role_created"}
    nothing = app_client.get("/ui/audit", params={"record": "usr_nobody"}).text
    assert "Nothing that matches." in nothing
    wrong = app_client.get("/ui/audit", params={"after": "not a day"})
    assert wrong.status_code == 200
    assert "Filter:" in wrong.text


def test_the_page_is_for_audit_in_service(
    app_client: TestClient, services: Services
) -> None:
    sign_in(
        app_client,
        *browser_user(
            services, Grant(accounts=["*"], allow=["audit"]), service=["users.manage"]
        ),
    )
    assert 'href="/ui/audit"' not in app_client.get("/ui").text
    assert app_client.get("/ui/audit").status_code == 403


def test_an_auditor_sees_the_page(app_client: TestClient, services: Services) -> None:
    sign_in(app_client, *browser_user(services, service=["audit"]))
    assert 'href="/ui/audit"' in app_client.get("/ui").text
    assert app_client.get("/ui/audit").status_code == 200


def test_the_card_on_a_users_page(app_client: TestClient, services: Services) -> None:
    sign_in(app_client, *browser_admin(services))
    anna = services.users.create_user(ADMIN, "Anna", [], [READER], service=["admin"])
    services.users.create_role(services.auth.access_of(anna.id), "readers", [READER])
    page = app_client.get(f"/ui/users/{anna.id}").text
    assert "Recent activity" in page
    assert "users.role_created" in page
    # What was done to Anna is not what Anna did.
    assert "users.created" not in page
    assert f'href="/ui/audit?user={anna.id}"' in page
    assert f'href="/ui/audit?record={anna.id}"' in page


def test_no_card_without_the_right(app_client: TestClient, services: Services) -> None:
    sign_in(app_client, *browser_user(services, service=["users.read"]))
    anna = services.users.create_user(ADMIN, "Anna", [], [])
    page = app_client.get(f"/ui/users/{anna.id}")
    assert page.status_code == 200
    assert "Recent activity" not in page.text


def test_the_editor_offers_audit_in_both_lists(
    app_client: TestClient, services: Services
) -> None:
    sign_in(app_client, *browser_admin(services))
    page = app_client.get("/ui/users/new").text
    assert 'name="service" value="audit"' in page
    assert 'name="g0_allow" value="audit"' in page
    assert 'title="list_activity"' in page
    assert 'title="list_sends, list_all_sends"' in page
