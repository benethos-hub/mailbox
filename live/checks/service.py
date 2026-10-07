"""A service for a check that is gone at the end: as a process on a free
port, or in this process with memory storage."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_client import SyncMailboxClient
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.main import Services, build_services, create_app

from .admin import Admin, admin_token, bootstrap
from .processes import free_port, service_env, start_service, stop


@dataclass(frozen=True)
class Service:
    """A running service and the user that administers it."""

    url: str
    admin_user: Admin

    def admin(self, timeout: float = 60) -> httpx.Client:
        """Plain HTTP with the admin's token, for a check of what the API
        answers itself."""
        return httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {self.admin_user.token}"},
            timeout=timeout,
        )

    def mailbox(self, token: str | None = None) -> SyncMailboxClient:
        """The Python client with ``token``, else with the admin's."""
        return SyncMailboxClient(self.url, token or self.admin_user.token)


@contextmanager
def throwaway_service(prefix: str) -> Iterator[Service]:
    """A service of the script's own on a free port, with a database and a
    master key that are gone at the end."""
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    data_dir = tempfile.mkdtemp(prefix=prefix)
    env = service_env(data_dir, port)
    process = start_service(env, url)
    try:
        yield Service(url, bootstrap(env, url))
    finally:
        stop(process)
        shutil.rmtree(Path(data_dir), ignore_errors=True)


def in_process_service() -> tuple[Services, TestClient]:
    """The service in this process: in memory, under a new master key, and
    a client that calls its API with a token of a user with every right."""
    settings = Settings(
        storage="memory",
        key_provider="env",
        master_key=SecretStr(encode_recovery(cipher.new_key())),
        sync_interval=0,
    )
    services = build_services(settings)
    services.vault.initialize()
    client = TestClient(
        create_app(settings, services),
        headers={"Authorization": f"Bearer {admin_token(services)}"},
    )
    return services, client


def mailbox_of(client: TestClient) -> SyncMailboxClient:
    """The Python client over the app of ``in_process_service``, with its
    token."""
    token = client.headers["Authorization"].removeprefix("Bearer ")
    return SyncMailboxClient(
        str(client.base_url), token, transport=_InProcess(client), allow_http=True
    )


class _InProcess(httpx.BaseTransport):
    """Carries each request of the client into the app through Starlette's
    test client. That one is built on another HTTP library, so the request
    and the answer are copied across."""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        answer = self._client.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.read(),
        )
        return httpx.Response(
            answer.status_code,
            headers=list(answer.headers.multi_items()),
            content=answer.content,
        )
