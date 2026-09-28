"""A secret the service holds never shows in its log or an error text."""

from __future__ import annotations

import json
import logging
import logging.config
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service import logs
from benethos_mailbox_service.common import redact
from benethos_mailbox_service.data.http import ApiClient
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.providers import sign_in
from benethos_mailbox_service.data.providers.protocols.oauth import App, OAuthClient
from benethos_mailbox_service.errors import ProviderError
from benethos_mailbox_service.main import Services
from benethos_mailbox_service.web.api.errors import api_error
from benethos_mailbox_service.web.pages.forms import Failed, failing

PASSWORD = "hunter2-but-longer"


def test_the_log_masks_message_arguments_and_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.config.dictConfig(logs.log_config("info", colours=False))
    redact.note(PASSWORD)
    log = logging.getLogger(f"{logs.PACKAGE}.data.providers")
    log.warning("login with %s refused", PASSWORD)
    try:
        raise RuntimeError(f"the server echoed {PASSWORD}")
    except RuntimeError:
        log.exception("a library failed")
    err = capsys.readouterr().err
    assert PASSWORD not in err
    assert "login with *** refused" in err
    assert "RuntimeError: the server echoed ***" in err


async def test_the_vault_notes_what_it_decrypts(
    master_key: None, services: Services
) -> None:
    services.vault.initialize()
    services.vault.store("acc_1", "password", SecretStr(PASSWORD))
    redact.forget_all()
    assert services.vault.read("acc_1", "password").get_secret_value() == PASSWORD
    assert redact.redact(PASSWORD) == "***"


async def test_tokens_from_a_provider_are_noted() -> None:
    def endpoint(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-token-from-the-provider",
                "refresh_token": "refresh-token-from-the-provider",
                "expires_in": 3600,
            },
        )

    app = App(sign_in(ProviderType.MICROSOFT, "common"), "client", None)
    client = OAuthClient(
        app,
        ApiClient(transport=httpx.MockTransport(endpoint)),
        lambda: datetime(2026, 9, 28, tzinfo=UTC),
    )
    await client.refresh(SecretStr("an-old-refresh-token"))
    said = "access-token-from-the-provider refresh-token-from-the-provider"
    assert redact.redact(said) == "*** ***"


def test_an_error_text_is_masked_in_the_api_and_the_ui() -> None:
    redact.note(PASSWORD)
    error = ProviderError(f"the server said: bad password {PASSWORD}")
    body = json.loads(api_error(error).body)
    assert body["error"]["message"] == "the server said: bad password ***"
    with pytest.raises(Failed) as refused, failing("/ui/accounts"):
        raise error
    assert refused.value.error == "the server said: bad password ***"
