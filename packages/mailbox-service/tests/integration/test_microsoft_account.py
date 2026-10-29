"""A Microsoft account through the whole service: connected by OAuth,
its folders and messages read, a mail sent and a draft saved over the
API, against a Graph mailbox in memory."""

from __future__ import annotations

from email import message_from_bytes
from typing import Any

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.assembly import build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import App, OAuthClient
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
    TokenSource,
)
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)

from ..conftest import admin_bearer, set_master_key
from ..graph_fake import TOKEN, FakeGraph
from ..oauth_fake import TokenEndpoint, granted, id_token, state_of


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


def test_connect_read_and_send_through_the_api(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_master_key(monkeypatch)
    graph.add_message(subject="Welcome")
    endpoint = TokenEndpoint(
        granted(TOKEN, "rt-1", id_token=id_token(email="me@example.org")),
        # The account's own adapter renews once, from the stored token.
        granted(TOKEN, "rt-2"),
    )

    def factory(
        kind: ProviderType,
        settings: ProviderSettings,
        credentials: CredentialReader,
        /,
        *,
        tokens: TokenSource | None = None,
    ) -> Reads:
        assert kind is ProviderType.MICROSOFT and tokens is not None
        return MicrosoftProvider(
            tokens, ApiClient(transport=httpx.MockTransport(graph))
        )

    config = Settings(storage="memory")
    app = App(microsoft_endpoints(), "client-1", SecretStr("secret"))
    services = build_services(
        config,
        provider_factory=factory,
        oauth_clients={
            ProviderType.MICROSOFT: OAuthClient(
                app, ApiClient(transport=httpx.MockTransport(endpoint))
            )
        },
    )
    services.vault.initialize()
    headers = admin_bearer(services)
    client = TestClient(create_app(config, services), headers=headers)

    # The one who started the sign-in, in the UI, finishes it.
    caller = services.auth.authenticate(
        headers["Authorization"].removeprefix("Bearer ")
    )
    callback = "http://testserver/ui/oauth/microsoft/callback"
    state = state_of(services.oauth.start(caller, ProviderType.MICROSOFT, callback))
    account = anyio.run(
        lambda: services.oauth.finish(caller, ProviderType.MICROSOFT, state, "code")
    )
    base = f"/v1/accounts/{account.id}"
    roles = {f["role"] for f in client.get(f"{base}/folders").json()}
    assert {"inbox", "sent", "drafts", "trash"} <= roles
    listed = client.get(f"{base}/messages", params={"folder": "inbox"}).json()
    assert [m["subject"] for m in listed["items"]] == ["Welcome"]
    sent = client.post(
        f"{base}/send",
        json={"to": [{"email": "bob@example.org"}], "subject": "Hi", "text": "Hello"},
    )
    assert sent.status_code == 200, sent.text
    [raw] = graph.sent
    assert message_from_bytes(raw)["Subject"] == "Hi"
    copy = sent.json()["sent_copy_id"]
    assert graph.messages[copy]["parentFolderId"] == graph.well_known["sentitems"]
    draft = client.post(
        f"{base}/drafts", json={"to": [{"email": "bob@example.org"}], "text": "Later"}
    )
    assert draft.status_code == 201, draft.text
    listed_drafts: Any = client.get(f"{base}/drafts").json()
    assert [d["id"] for d in listed_drafts["items"]] == [draft.json()["id"]]
