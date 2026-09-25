"""The hosts of an account pass the same check as autodiscovery, before the
first connection: the service is not pointed into its own network
(CONCEPT 5.8, rule 6)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.main import build_services, create_app

from .conftest import API_KEY

PUBLIC = "93.184.215.14"
TABLE: dict[str, list[str]] = {
    "imap.example.org": [PUBLIC],
    "smtp.example.org": [PUBLIC],
    "mail.internal": ["10.0.0.5"],
    "localhost": ["127.0.0.1"],
    "10.0.0.5": ["10.0.0.5"],
    "nowhere.example": [],
}


class World:
    """A client whose DNS is the table above, and a count of the lookups."""

    def __init__(self, internal_hosts: list[str] | None = None) -> None:
        self.lookups: list[str] = []
        settings = Settings(
            api_key=SecretStr(API_KEY),
            storage="memory",
            discovery_internal_hosts=internal_hosts or [],
        )
        services = build_services(settings, resolve=self._resolve)
        self.client = TestClient(
            create_app(settings, services),
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    async def _resolve(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        return TABLE.get(host, [])

    def create(self, **settings: object) -> object:
        # The memory adapter ignores its settings, so no connection is made
        # and only the check decides.
        return self.client.post(
            "/v1/accounts",
            json={
                "provider": "memory",
                "email": "me@example.org",
                "settings": settings,
            },
        )


@pytest.fixture
def world() -> Iterator[World]:
    yield World()


def test_public_hosts_pass(world: World) -> None:
    response = world.create(host="imap.example.org", smtp_host="smtp.example.org")
    assert response.status_code == 201, response.text
    assert sorted(world.lookups) == ["imap.example.org", "smtp.example.org"]


@pytest.mark.parametrize("host", ["mail.internal", "localhost", "10.0.0.5"])
def test_a_private_host_is_refused(world: World, host: str) -> None:
    response = world.create(host=host)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "bad_request"
    assert "non-public" in error["message"]
    assert world.client.get("/v1/accounts").json() == []


def test_the_smtp_host_is_checked_too(world: World) -> None:
    response = world.create(host="imap.example.org", smtp_host="mail.internal")
    assert response.status_code == 400
    assert "mail.internal" in response.json()["error"]["message"]


def test_a_host_that_does_not_resolve_is_refused(world: World) -> None:
    response = world.create(host="nowhere.example")
    assert response.status_code == 400
    assert response.json()["error"]["message"] == (
        "host: nowhere.example does not resolve"
    )


def test_an_operator_may_allow_an_internal_host() -> None:
    world = World(internal_hosts=["mail.internal"])
    assert world.create(host="mail.internal").status_code == 201
    # The allow-list names hosts, not addresses.
    assert world.create(host="10.0.0.5").status_code == 400


def test_a_change_of_settings_is_checked(world: World) -> None:
    account = world.create(host="imap.example.org").json()
    url = f"/v1/accounts/{account['id']}"

    refused = world.client.patch(url, json={"settings": {"smtp_host": "localhost"}})
    assert refused.status_code == 400
    assert world.client.get(url).json()["settings"] == {"host": "imap.example.org"}

    moved = world.client.patch(url, json={"settings": {"host": "smtp.example.org"}})
    assert moved.status_code == 200, moved.text
    assert moved.json()["settings"] == {"host": "smtp.example.org"}


def test_other_changes_look_nothing_up(world: World) -> None:
    account = world.create(host="imap.example.org").json()
    world.lookups.clear()
    renamed = world.client.patch(
        f"/v1/accounts/{account['id']}", json={"display_name": "Work"}
    )
    assert renamed.status_code == 200, renamed.text
    assert world.lookups == []
