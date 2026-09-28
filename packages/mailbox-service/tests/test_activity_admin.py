"""The activities of administration: users, tokens, roles, accounts and
OAuth (docs/LOGGING.md 5.2 to 5.4). Each line names who, what and to
which record, and never a secret."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_service.domain.access import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderUnavailableError,
    UnauthorizedError,
)
from benethos_mailbox_service.main import Services, build_services

from .conftest import ADMIN, create_account
from .test_account_status import FlakyProvider
from .test_oauth import (
    REDIRECT,
    TokenEndpoint,
    granted,
    id_token,
    services_with,
    state_of,
)
from .ui_helpers import post

READER = Grant(accounts=["*"], allow=["mail.read"])
WHO = "test admin (usr_test_admin)"

pytestmark = pytest.mark.usefixtures("master_key")


def lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The activities, without the lifecycle of the services."""
    return [
        r.getMessage()
        for r in caplog.records
        if ".activity." in r.name and not r.name.endswith(".lifecycle")
    ]


def test_a_user_its_changes_and_its_tokens(
    services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        anna = services.users.create_user(ADMIN, "Anna", [], [READER])
        services.users.update_user(ADMIN, anna.id, name="Anna B", disabled=False)
        token, plain = services.users.create_token(ADMIN, anna.id, "laptop")
        services.users.revoke_token(ADMIN, anna.id, token.id)
        services.users.revoke_token(ADMIN, anna.id, token.id)
    assert lines(caplog) == [
        f"{WHO} created user Anna ({anna.id}): roles none, 1 grant, signs in to "
        "the API",
        f"{WHO} changed user Anna B ({anna.id}): name",
        f"{WHO} issued token laptop ({token.id}) for Anna B ({anna.id}), it does "
        "not expire",
        # Revoked once: the second call changes nothing.
        f"{WHO} revoked token laptop ({token.id}) of Anna B ({anna.id})",
    ]
    assert plain not in caplog.text


def test_roles(services: Services, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        services.users.create_role(ADMIN, "readers", [READER])
        services.users.replace_role(ADMIN, "readers", [READER, READER])
        services.users.delete_role(ADMIN, "readers")
    assert lines(caplog) == [
        f"{WHO} created role readers with 1 grant",
        f"{WHO} replaced role readers: it has 2 grants now",
        f"{WHO} deleted role readers",
    ]


def test_a_token_that_is_revoked_or_of_a_disabled_user(
    services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    anna = services.users.create_user(ADMIN, "Anna", [], [READER])
    token, plain = services.users.create_token(ADMIN, anna.id, "laptop")
    services.users.update_user(ADMIN, anna.id, disabled=True)
    with pytest.raises(UnauthorizedError):
        services.auth.authenticate(plain, source="10.0.0.7")
    services.users.revoke_token(ADMIN, anna.id, token.id)
    with pytest.raises(UnauthorizedError):
        services.auth.authenticate(plain, source="10.0.0.7")
    with pytest.raises(UnauthorizedError):
        services.auth.authenticate("mbx_unknown", source="10.0.0.7")
    refused = [r for r in caplog.records if "presented token" in r.getMessage()]
    said = f"someone presented token laptop ({token.id}) of {anna.id} from 10.0.0.7"
    assert [r.getMessage() for r in refused] == [
        f"{said}: its user is disabled",
        f"{said}: it is revoked",
    ]
    assert all(r.levelno == logging.WARNING for r in refused)
    assert plain not in caplog.text


def test_signing_out(ui: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        post(ui, "/ui/logout")
    assert "signed out of the UI from testclient" in caplog.text


async def test_an_account_from_connect_to_remove(
    services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    services.vault.initialize()
    with caplog.at_level(logging.INFO):
        account = await services.accounts.create(
            ADMIN, ProviderType.MEMORY, "me@example.org"
        )
        await services.accounts.update(
            ADMIN,
            account.id,
            display_name="Me",
            rename=True,
            credentials={"password": SecretStr("a secret password")},
        )
        await services.accounts.verify(ADMIN, account.id)
        await services.accounts.delete(ADMIN, account.id)
    named = f"me@example.org ({account.id})"
    assert lines(caplog) == [
        f"{WHO} connected account {named}: memory",
        f"{WHO} changed account {named}: display name, password",
        f"{WHO} verified account {named}",
        f"{WHO} removed account {named}",
    ]
    assert "a secret password" not in caplog.text


async def test_an_account_that_cannot_connect(
    services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(BadRequestError):
        await services.accounts.create(
            ADMIN, ProviderType.IMAP, "me@example.org", settings={"host": ""}
        )
    [line] = lines(caplog)
    assert line.startswith(f"{WHO} could not connect me@example.org (imap): ")


def test_a_status_is_logged_when_it_changes(caplog: pytest.LogCaptureFixture) -> None:
    flaky = FlakyProvider()

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> FlakyProvider:
        return flaky

    services = build_services(Settings(storage="memory"), provider_factory=factory)
    account_id = create_account(
        services.accounts, ProviderType.MEMORY, "a@example.com"
    ).id
    caplog.clear()

    async def folders() -> None:
        try:
            await services.mailbox.list_folders(ADMIN, account_id)
        except (ProviderAuthError, ProviderUnavailableError):
            pass

    import anyio

    with caplog.at_level(logging.INFO):
        flaky.fail = ProviderUnavailableError("the mail server is not reachable")
        anyio.run(folders)
        anyio.run(folders)
        flaky.fail = ProviderAuthError("the server rejected the login")
        anyio.run(folders)
        flaky.fail = None
        anyio.run(folders)
        anyio.run(folders)
    named = f"a@example.com ({account_id})"
    assert lines(caplog) == [
        f"the service could not reach account {named}: the mail server is not "
        "reachable",
        f"the service found that account {named} needs a new sign-in: the server "
        "rejected the login",
        f"the service reached account {named} again",
    ]


async def test_an_oauth_sign_in(caplog: pytest.LogCaptureFixture) -> None:
    endpoint = TokenEndpoint(
        granted("at-1", "rt-1", id_token=id_token(email="me@example.org")),
        granted("at-2", "rt-2"),
    )
    services = services_with(endpoint)
    with caplog.at_level(logging.DEBUG):
        url = services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT)
        account = await services.oauth.finish(
            ADMIN, ProviderType.MICROSOFT, state_of(url), "the-code"
        )
        await services.accounts.verify(ADMIN, account.id)
    named = f"me@example.org ({account.id})"
    assert lines(caplog) == [
        f"{WHO} started a sign-in with microsoft to connect an account",
        f"{WHO} connected account {named}: microsoft",
        f"{WHO} finished the sign-in with microsoft: {named} connected",
        f"the service refreshed the access token of {named}",
        f"{WHO} verified account {named}",
    ]
    state = state_of(url)
    for secret in (state, "the-code", "rt-1", "at-1", "rt-2", "at-2"):
        assert secret not in caplog.text


async def test_an_oauth_sign_in_that_fails(caplog: pytest.LogCaptureFixture) -> None:
    services = services_with(TokenEndpoint())
    url = services.oauth.start(ADMIN, ProviderType.MICROSOFT, REDIRECT)
    with pytest.raises(BadRequestError):
        await services.oauth.finish(
            Access.admin("usr_other", "other"), ProviderType.MICROSOFT, "x", "c"
        )
    services.oauth.cancel(ADMIN, state_of(url), "the user said no")
    assert lines(caplog) == [
        "other (usr_other) could not finish a sign-in with microsoft: this sign-in "
        "is unknown or expired: start again",
        f"{WHO} could not finish a sign-in with microsoft: the user said no",
    ]
    assert state_of(url) not in caplog.text
