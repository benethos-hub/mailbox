"""How each kind of account is connected, as its adapter describes it
(docs/mailbox-service/UNIFORM.md, U6): the UI draws its forms from these."""

from __future__ import annotations

from ...data.models import Connection, ProviderType
from ...data.providers import AUTHSERV_ID, CONNECTIONS


def connection_of(kind: ProviderType | str) -> Connection:
    """The description of one kind of account."""
    return CONNECTIONS[ProviderType(kind)]


def takes_server_name(kind: ProviderType | str) -> bool:
    """Whether a person names the receiving server of this kind of
    account: IMAP, POP3 and JMAP. Gmail and Microsoft name theirs
    themselves."""
    return any(f.name == AUTHSERV_ID for f in connection_of(kind).fields)


def connections() -> list[Connection]:
    """Every kind of account but the memory one, in the order of
    ``ProviderType``."""
    return [c for k, c in CONNECTIONS.items() if k is not ProviderType.MEMORY]
