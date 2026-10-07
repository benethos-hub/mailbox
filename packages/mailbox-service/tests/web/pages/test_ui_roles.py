"""The role pages of the configuration UI, and the roles to start from."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.web.pages.grants import (
    ROLE_TEMPLATES,
)

from ...conftest import ADMIN, browser_user
from ...ui_helpers import post, sign_in

# --- roles ----------------------------------------------------------------------------


def test_create_change_and_delete_a_role(ui: TestClient, services: Services) -> None:
    created = post(
        ui,
        "/ui/roles",
        {"id": "reader", "grants": "1", "g0_accounts": "*", "g0_allow": "mail.read"},
    )
    assert "Role reader created." in created.text
    assert services.roles.get_role(ADMIN, "reader").grants == [
        Grant(accounts=["*"], allow=["mail.read"])
    ]
    post(
        ui,
        "/ui/roles/reader",
        {"grants": "1", "g0_accounts": "*", "g0_allow": ["mail.read", "audit"]},
    )
    assert services.roles.get_role(ADMIN, "reader").grants[0].allow == [
        "mail.read",
        "audit",
    ]
    holder = services.users.create_user(ADMIN, "holder", ["reader"], [])
    page = ui.get("/ui/roles/reader").text
    assert "holder" in page
    refused = post(ui, "/ui/roles/reader/delete")

    assert "is used by" in refused.text
    services.users.delete_user(ADMIN, holder.id)
    deleted = post(ui, "/ui/roles/reader/delete")
    assert "Role reader deleted." in deleted.text


def test_a_user_keeps_roles_the_editor_cannot_list(
    app_client: TestClient, services: Services
) -> None:
    services.roles.create_role(ADMIN, "hidden", [])
    target = services.users.create_user(ADMIN, "target", ["hidden"], [])
    sign_in(
        app_client,
        *browser_user(
            services,
            service=["list_users", "get_user", "update_user"],
        ),
    )
    page = app_client.get(f"/ui/users/{target.id}").text
    assert 'name="roles" value="hidden" checked' in page
    post(
        app_client,
        f"/ui/users/{target.id}",
        {"name": "target", "roles": "hidden", "grants": "0"},
    )
    assert services.users.get_user(ADMIN, target.id).roles == ["hidden"]


def test_a_role_name_is_quoted_in_links(ui: TestClient, services: Services) -> None:
    services.roles.create_role(ADMIN, "team a&b", [])
    listed = ui.get("/ui/roles").text
    assert 'href="/ui/roles/team%20a%26b"' in listed
    assert "Role team a&amp;b" in ui.get("/ui/roles/team%20a%26b").text


def test_the_sidebar_links_the_access_pages(ui: TestClient) -> None:
    home = ui.get("/ui").text
    assert 'href="/ui/users"' in home and 'href="/ui/roles"' in home


def test_a_new_role_has_its_editor(
    ui: TestClient, app_client: TestClient, services: Services, account_id: str
) -> None:
    page = ui.get("/ui/roles/new")
    assert page.status_code == 200 and "Cancel" in page.text
    assert 'href="/ui/roles/new"' in ui.get("/ui/roles").text
    created = post(ui, "/ui/roles", {"id": "helpers", "grants": "0"})
    assert "Role helpers created." in created.text
    refused = post(ui, "/ui/roles", {"id": "", "grants": "0"})
    assert refused.status_code == 400 and "Cancel" in refused.text

    reader = TestClient(app_client.app)
    sign_in(
        reader,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    assert reader.get("/ui/roles/new").status_code == 403


# --- roles to start from (PERMISSIONS.md 8.7) ------------------------------------


def test_the_new_role_page_offers_four_templates(ui: TestClient) -> None:
    page = ui.get("/ui/roles/new").text
    for template in ("reader", "agent", "sender", "operator"):
        assert f'href="/ui/roles/new?template={template}"' in page
    assert [t.title for t in ROLE_TEMPLATES.values()] == [
        "Reader",
        "Agent",
        "Sender",
        "Operator",
    ]


@pytest.mark.parametrize("template", list(ROLE_TEMPLATES))
def test_every_template_names_rights_of_the_right_kind(template: str) -> None:
    chosen = ROLE_TEMPLATES[template]
    permissions.check_service(chosen.service)
    for grant in chosen.grants:
        permissions.check_grant(grant.allow)


def test_a_template_fills_the_form(ui: TestClient, account_id: str) -> None:
    agent = ui.get("/ui/roles/new?template=agent").text
    assert 'name="id" value="agent"' in agent
    for group in ("mail.read", "mail.write", "drafts"):
        assert f'name="g0_allow" value="{group}" checked' in agent
    assert 'name="g0_allow" value="send" checked' not in agent
    assert f'name="g0_accounts" value="{account_id}" checked' not in agent
    operator = ui.get("/ui/roles/new?template=operator").text
    assert 'name="service" value="accounts.connect" checked' in operator
    assert 'name="service" value="webhooks.manage" checked' in operator
    assert 'name="g0_accounts" value="*" checked' in operator
    assert 'name="g0_allow" value="accounts.manage" checked' in operator
    unknown = ui.get("/ui/roles/new?template=nothing").text
    assert 'name="id" value=""' in unknown


def test_the_sender_template_wants_recipients(
    ui: TestClient, services: Services, account_id: str
) -> None:
    form = {
        "template": "sender",
        "id": "sender",
        "grants": "1",
        "g0_accounts": account_id,
        "g0_allow": "send",
        "g0_max": "10",
    }
    refused = post(ui, "/ui/roles", form)
    assert refused.status_code == 400
    assert "name the recipients it may send to" in refused.text
    assert 'name="template" value="sender"' in refused.text
    made = post(ui, "/ui/roles", {**form, "g0_recipients": "*@example.org"})
    assert "Role sender created." in made.text
    [grant] = services.roles.get_role(ADMIN, "sender").grants
    assert grant.recipients == ["*@example.org"] and grant.max_sends_per_day == 10
