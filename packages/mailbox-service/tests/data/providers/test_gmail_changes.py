"""The ``gmail`` adapter: what changed since a history id, Gmail's errors
on the wire, how an account signs in, and the client in the settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from benethos_mailbox_service.assembly.providers import build_oauth
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import MessageUpdate, ProviderType
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import (
    App,
    OAuthClient,
    authorize_url,
    new_pkce,
)
from benethos_mailbox_service.data.providers import build_provider, sign_in
from benethos_mailbox_service.data.providers.gmail import GmailProvider
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_service.errors import (
    ChangesExpiredError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from ...gmail_fake import TOKEN, FakeGmail
from .test_gmail import Tokens

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def gmail() -> FakeGmail:
    return FakeGmail()


def adapter(
    gmail: FakeGmail, tokens: Tokens | None = None, clock: list[float] | None = None
) -> GmailProvider:
    ticks = clock if clock is not None else [0.0]
    return GmailProvider(
        tokens or Tokens(TOKEN),
        ApiClient(transport=httpx.MockTransport(gmail)),
        clock=lambda: ticks[0],
        now=lambda: NOW,
    )


# --- changes --------------------------------------------------------------------------


async def test_a_first_question_names_every_message(gmail: FakeGmail) -> None:
    inbox = gmail.add_message()
    gmail.add_message(labels=("TRASH",))
    provider = adapter(gmail)
    states = await provider.folder_states()
    assert {"INBOX", "TRASH", "ALL_MAIL", "SENT"} <= set(states)
    assert "UNREAD" not in states
    found = await provider.folder_changes("INBOX", None)
    assert [m.id for m in found.changed] == [inbox] and found.removed == []
    assert found.token == str(gmail.history_id)


async def test_what_arrived_moved_and_went(gmail: FakeGmail) -> None:
    stays = gmail.add_message()
    goes = gmail.add_message()
    provider = adapter(gmail)
    token = (await provider.folder_changes("INBOX", None)).token
    new = gmail.add_message()
    await provider.update_messages([stays], MessageUpdate(folder_ids=["ALL_MAIL"]))
    await provider.delete_messages([goes], permanent=False)
    inbox = await provider.folder_changes("INBOX", token)
    assert [(m.id, m.created) for m in inbox.changed] == [(new, NOW)]
    assert set(inbox.removed) == {stays, goes}
    all_mail = await provider.folder_changes("ALL_MAIL", token)
    assert {m.id: m.created for m in all_mail.changed} == {new: NOW, stays: None}
    assert all_mail.removed == [goes]
    trash = await provider.folder_changes("TRASH", token)
    assert [m.id for m in trash.changed] == [goes] and trash.removed == []
    assert inbox.token == all_mail.token == str(gmail.history_id)


async def test_a_flag_changes_the_message_where_it_is(gmail: FakeGmail) -> None:
    message_id = gmail.add_message()
    provider = adapter(gmail)
    token = (await provider.folder_changes("INBOX", None)).token
    await provider.update_messages([message_id], MessageUpdate(unread=False))
    found = await provider.folder_changes("INBOX", token)
    assert [(m.id, m.created) for m in found.changed] == [(message_id, None)]
    assert (await provider.folder_changes("SENT", token)).changed == []


async def test_a_message_deleted_for_good_is_removed(gmail: FakeGmail) -> None:
    message_id = gmail.add_message()
    provider = adapter(gmail)
    token = (await provider.folder_changes("INBOX", None)).token
    await provider.delete_messages([message_id], permanent=True)
    found = await provider.folder_changes("INBOX", token)
    assert found.changed == [] and found.removed == [message_id]


async def test_a_history_gmail_no_longer_keeps(gmail: FakeGmail) -> None:
    provider = adapter(gmail)
    gmail.oldest = gmail.history_id + 1
    with pytest.raises(ChangesExpiredError):
        await provider.folder_changes("INBOX", str(gmail.history_id))
    with pytest.raises(ChangesExpiredError):
        await provider.folder_changes("INBOX", "not-a-number")


async def test_the_contents_and_the_message_ids(gmail: FakeGmail) -> None:
    message_id = gmail.add_message(message_id="<one@example.com>")
    provider = adapter(gmail)
    assert await provider.folder_contents("INBOX") == [message_id]
    assert await provider.message_headers([message_id, "00000000000000ff"]) == {
        message_id: "<one@example.com>"
    }


# --- the wire -------------------------------------------------------------------------


async def test_a_refused_token_is_renewed_once(gmail: FakeGmail) -> None:
    tokens = Tokens("old-token", TOKEN)
    await adapter(gmail, tokens).list_folders()
    assert tokens.rejected == 1
    gmail.tokens = set()
    with pytest.raises(ProviderAuthError):
        await adapter(gmail, Tokens("old-token", "other")).list_folders()


async def test_a_quota_refusal_is_a_busy_gmail(gmail: FakeGmail) -> None:
    gmail.next_answer = httpx.Response(
        403,
        json={
            "error": {
                "code": 403,
                "message": "User-rate limit exceeded",
                "errors": [{"reason": "userRateLimitExceeded"}],
            }
        },
    )
    with pytest.raises(ProviderUnavailableError):
        await adapter(gmail).list_folders()
    gmail.next_answer = httpx.Response(
        403, json={"error": {"code": 403, "message": "Insufficient Permission"}}
    )
    with pytest.raises(ProviderError, match="Insufficient Permission"):
        await adapter(gmail).list_folders()


async def test_a_pause_gmail_asks_for_is_kept(gmail: FakeGmail) -> None:
    clock = [100.0]
    provider = adapter(gmail, clock=clock)
    gmail.next_answer = httpx.Response(429, headers={"Retry-After": "30"})
    with pytest.raises(ProviderUnavailableError):
        await provider.list_folders()
    asked = len(gmail.requests)
    with pytest.raises(ProviderUnavailableError, match="next attempt in 30s"):
        await provider.list_folders()
    assert len(gmail.requests) == asked
    clock[0] = 131.0
    await provider.list_folders()


async def test_verify_signs_in_afresh(gmail: FakeGmail) -> None:
    tokens = Tokens(TOKEN)
    await adapter(gmail, tokens).verify()
    assert tokens.forgotten == 1
    assert gmail.requests[-1].url.path.endswith("/profile")


# --- signing in -----------------------------------------------------------------------


def test_google_asks_for_a_refresh_token_on_every_sign_in() -> None:
    app = App(sign_in(ProviderType.GMAIL), "client-1", SecretStr("s"))
    url = urlsplit(authorize_url(app, "https://x/cb", "state-1", new_pkce()))
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["scope"] == ["https://mail.google.com/"]
    assert "response_mode" not in query
    microsoft = App(microsoft_endpoints(), "client-1")
    other = parse_qs(urlsplit(authorize_url(microsoft, "x", "s", new_pkce())).query)
    assert other["response_mode"] == ["query"] and "access_type" not in other


async def test_a_google_refresh_names_no_scope() -> None:
    forms: list[dict[str, list[str]]] = []

    def endpoint(request: httpx.Request) -> httpx.Response:
        forms.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"access_token": "at", "expires_in": 3599})

    app = App(sign_in(ProviderType.GMAIL), "client-1", SecretStr("s"))
    client = OAuthClient(app, ApiClient(transport=httpx.MockTransport(endpoint)))
    tokens = await client.refresh(SecretStr("rt"))
    assert tokens.refresh_token is None
    [form] = forms
    assert "scope" not in form and form["client_secret"] == ["s"]


async def test_the_address_comes_from_gmails_profile() -> None:
    def endpoint(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gmail.googleapis.com":
            body = {"emailAddress": "Me@Gmail.com", "historyId": "1"}
            return httpx.Response(200, content=json.dumps(body))
        return httpx.Response(
            200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 60}
        )

    app = App(sign_in(ProviderType.GMAIL), "client-1", SecretStr("s"))
    client = OAuthClient(app, ApiClient(transport=httpx.MockTransport(endpoint)))
    tokens = await client.exchange("code", "https://x/cb", "verifier")
    assert tokens.identity is not None and tokens.identity.email == "me@gmail.com"


# --- the client in the settings -------------------------------------------------------


def test_a_google_client_needs_its_id_and_its_secret(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Google client"):
        Settings(storage="memory", oauth_google_client_id="id")
    with pytest.raises(ValidationError, match="Google client"):
        Settings(storage="memory", oauth_google_client_secret=SecretStr("s"))
    secret = tmp_path / "google_secret"
    secret.write_text("from-file\n", encoding="utf-8")
    settings = Settings(
        storage="memory",
        oauth_google_client_id="id",
        oauth_google_client_secret_file=secret,
    )
    found = settings.oauth_google_secret()
    assert found is not None and found.get_secret_value() == "from-file"


def test_gmail_signs_in_only_with_a_client_of_the_deployment() -> None:
    assert ProviderType.GMAIL not in build_oauth(Settings(storage="memory"))
    settings = Settings(
        storage="memory",
        oauth_google_client_id="client-1",
        oauth_google_client_secret=SecretStr("s"),
    )
    client = build_oauth(settings)[ProviderType.GMAIL]
    assert client.app.client_id == "client-1" and not client.app.loopback_only
    assert client.app.endpoints.provider == "gmail"


def test_a_gmail_account_is_built_with_its_tokens() -> None:
    built = build_provider(ProviderType.GMAIL, {}, _no_credential, tokens=Tokens(TOKEN))
    assert isinstance(built, GmailProvider)


def _no_credential(_name: str) -> SecretStr:
    raise AssertionError("gmail reads no stored credential")
