"""How the second step of a form looks on the pages: a named group, its
methods, the list of the others (docs/UI.md 6.3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services

from ...conftest import browser_admin
from ...ui_helpers import try_sign_in
from .factor_page_helpers import code_form, with_factor

pytestmark = pytest.mark.usefixtures("master_key")


@pytest.fixture
def factor_on(
    master_key: None, app_client: TestClient, services: Services
) -> list[str]:
    """An administrator with the device Phone, signed in with a recovery
    code: the codes left."""
    services.vault.initialize()
    name, password = browser_admin(services)
    _, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, codes[0])
    return codes[1:]


@pytest.mark.usefixtures("factor_on")
def test_the_step_is_a_named_group(app_client: TestClient) -> None:
    page = app_client.get("/ui/second-factor").text
    assert '<fieldset class="factor-step" data-ways>' in page
    assert "<legend>Confirm it is you</legend>" in page
    assert (
        '<fieldset class="factor-step" data-ways>'
        in app_client.get("/ui/password").text
    )


def test_the_code_page_names_the_step_to_a_screen_reader(
    app_client: TestClient, services: Services
) -> None:
    services.vault.initialize()
    name, password = browser_admin(services)
    with_factor(services, name)
    try_sign_in(app_client, name, password)
    page = app_client.get("/ui/login/code").text
    assert '<legend class="sr">Confirm it is you</legend>' in page
