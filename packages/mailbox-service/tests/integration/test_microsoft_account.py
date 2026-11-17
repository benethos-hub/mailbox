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

from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.protocols.oauth import App, OAuthClient
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
    TokenSource,
    rules,
)
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider
from benethos_mailbox_service.data.providers.microsoft import (
    endpoints as microsoft_endpoints,
)
from benethos_mailbox_service.domain import paging

from ..conftest import admin_bearer, bearer_for, set_master_key
from ..graph_fake import TOKEN, FakeGraph
from ..oauth_fake import TokenEndpoint, granted, id_token, state_of


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


def _connected(graph: FakeGraph) -> tuple[Services, TestClient, str]:
    """A service with the Graph fake, the admin's client of its API, and
    the Microsoft account the admin connected."""
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
    return services, client, account.id


def test_connect_read_and_send_through_the_api(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_master_key(monkeypatch)
    graph.add_message(subject="Welcome")
    _, client, account_id = _connected(graph)
    base = f"/v1/accounts/{account_id}"
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


def test_a_token_of_drafts_reads_no_inbox_through_a_cursor(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor of the drafts with the path of the inbox, made up by a
    token that may reach drafts alone (review 2026-11-17, finding 1)."""
    set_master_key(monkeypatch)
    graph.add_message(subject="Payroll")
    services, client, account_id = _connected(graph)
    client.headers.update(
        bearer_for(services, Grant(accounts=[account_id], allow=["drafts"]))
    )
    base = f"/v1/accounts/{account_id}"
    assert client.get(f"{base}/messages", params={"folder": "inbox"}).status_code == 403
    path = f"/me/mailFolders/{graph.well_known['inbox']}/messages?$top=50"
    scope = rules.cursor_scope(graph.well_known["drafts"], None)
    forged = rules.bound_cursor("m_", scope, path)
    answer = client.get(f"{base}/drafts", params={"cursor": forged})
    assert answer.status_code == 400
    assert "Payroll" not in answer.text


def test_a_thread_row_shows_nothing_beyond_the_folders_of_a_grant(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grant on the inbox alone, and a cursor of the inbox's threads with
    the path of the archive: a thread with a mail in the inbox would show
    the subject of its mail in the archive (review 2026-11-17, finding 2)."""
    set_master_key(monkeypatch)
    archive = graph.new_folder("Archive", graph.root)
    graph.add_message(subject="Plan")
    graph.add_message(folder=archive, subject="Secret plan")
    services, client, account_id = _connected(graph)
    client.headers.update(
        bearer_for(
            services,
            Grant(accounts=[account_id], allow=["mail.read"], folders=["inbox"]),
        )
    )
    inbox = graph.well_known["inbox"]
    path = f"/me/mailFolders/{archive}/messages?$top=50"
    provider = rules.bound_cursor("m_", rules.cursor_scope(inbox, None), path)
    forged = paging.encode_cursor("t_", [provider, []])
    answer = client.get(
        f"/v1/accounts/{account_id}/threads",
        params={"folder": "inbox", "cursor": forged},
    )
    assert "Secret" not in answer.text
