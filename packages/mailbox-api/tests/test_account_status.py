from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.models import Folder, ProviderType
from benethos_mailbox_api.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_api.data.providers.memory import MemoryProvider
from benethos_mailbox_api.errors import ProviderAuthError, ProviderUnavailableError
from benethos_mailbox_api.main import build_services, create_app

from .conftest import create_account


class FlakyProvider(MemoryProvider):
    """Fails the way the next test tells it to."""

    def __init__(self) -> None:
        super().__init__()
        self.fail: Exception | None = None

    async def list_folders(self) -> list[Folder]:
        if self.fail is not None:
            raise self.fail
        return await super().list_folders()


def test_status_follows_what_the_provider_reports() -> None:
    flaky = FlakyProvider()

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> FlakyProvider:
        return flaky

    settings = Settings(storage="memory", api_key=SecretStr("k"))
    services = build_services(settings, provider_factory=factory)
    account_id = create_account(
        services.accounts, ProviderType.MEMORY, "a@example.com"
    ).id
    client = TestClient(
        create_app(settings, services), headers={"Authorization": "Bearer k"}
    )

    def status() -> str:
        return str(client.get(f"/v1/accounts/{account_id}").json()["status"])

    flaky.fail = ProviderAuthError("the server rejected the login")
    response = client.get(f"/v1/accounts/{account_id}/folders")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_auth_failed"
    assert status() == "needs_reauth"

    flaky.fail = ProviderUnavailableError("the mail server is not reachable")
    response = client.get(f"/v1/accounts/{account_id}/folders")
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert status() == "unreachable"

    flaky.fail = None
    assert client.get(f"/v1/accounts/{account_id}/folders").status_code == 200
    assert status() == "connected"
