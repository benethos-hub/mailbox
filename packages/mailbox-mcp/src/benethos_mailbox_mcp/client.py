"""The REST client of the tools: the package benethos-mailbox-client,
its client for async code and the body of a message as the API takes
it. ``models`` names its records, ``errors`` its errors."""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_client import (
    Environment,
    MailboxClient,
    from_environment,
    message_body,
)

# Makes a REST client, for one server or for the start.
Connect = Callable[[], MailboxClient]


def connector(environment: Environment) -> Connect:
    """Clients for the service ``environment`` names, as it was read."""

    def connect() -> MailboxClient:
        return MailboxClient(
            environment.url, environment.token, allow_http=environment.allow_http
        )

    return connect


__all__ = [
    "Connect",
    "Environment",
    "MailboxClient",
    "connector",
    "from_environment",
    "message_body",
]
