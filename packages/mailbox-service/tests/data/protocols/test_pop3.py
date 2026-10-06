"""One POP3 session: how it connects, and how poplib's failures leave it."""

from __future__ import annotations

import poplib
from typing import Any

import pytest

from benethos_mailbox_service.data.protocols import Server
from benethos_mailbox_service.data.protocols import pop3 as pop3_protocol
from benethos_mailbox_service.data.protocols.pop3 import Pop3Session
from benethos_mailbox_service.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from ...pop3_fake import FakePop3Connection, FakePop3Server

SERVER = Server(host="pop.example.com", port=995, security="tls")


def session(box: FakePop3Server) -> Pop3Session:
    return Pop3Session(SERVER, connection_factory=box)


class Recorded:
    """Stands in for poplib.POP3 and POP3_SSL, remembering how it was made."""

    made: list[tuple[Any, ...]] = []
    stls_failure: Exception | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        Recorded.made.append((type(self).__name__, args, kwargs))
        self.closed = False

    def stls(self, context: Any = None) -> bytes:
        if Recorded.stls_failure is not None:
            raise Recorded.stls_failure
        return b"+OK"

    def close(self) -> None:
        self.closed = True
        Recorded.made.append(("close",))


class RecordedSsl(Recorded):
    pass


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> type[Recorded]:
    Recorded.made = []
    Recorded.stls_failure = None
    monkeypatch.setattr(poplib, "POP3", Recorded)
    monkeypatch.setattr(poplib, "POP3_SSL", RecordedSsl)
    return Recorded


def test_tls_connects_with_a_context_for_the_host(recorded: type[Recorded]) -> None:
    server = Server(
        host="pop.example.com", port=995, security="tls", pick=lambda h, p: "192.0.2.5"
    )
    pop3_protocol._default_connection(server, 7.0)
    [(kind, args, kwargs)] = recorded.made
    assert kind == "RecordedSsl" and args == ("192.0.2.5", 995)
    assert kwargs["timeout"] == 7.0 and kwargs["context"] is not None


def test_starttls_upgrades_and_closes_when_that_fails(recorded: type[Recorded]) -> None:
    server = Server(host="pop.example.com", port=110, security="starttls")
    pop3_protocol._default_connection(server, 5.0)
    assert recorded.made[0][0] == "Recorded"
    recorded.made.clear()
    recorded.stls_failure = poplib.error_proto(b"-ERR no STLS")
    with pytest.raises(poplib.error_proto):
        pop3_protocol._default_connection(server, 5.0)
    assert recorded.made[-1] == ("close",)


def test_a_dropped_connection_during_the_login() -> None:
    box = FakePop3Server()

    def dropping(server: Any, timeout: float) -> FakePop3Connection:
        connection = box(server, timeout)

        def pass_(password: str) -> bytes:
            raise ConnectionResetError("reset")

        connection.pass_ = pass_  # type: ignore[method-assign]
        return connection

    with pytest.raises(ProviderUnavailableError, match="not reachable"):
        Pop3Session(SERVER, connection_factory=dropping).login("me", "secret")


@pytest.mark.parametrize(
    ("refusal", "expected"),
    [
        (b"-ERR [AUTH] wrong", ProviderAuthError),
        (b"-ERR [SYS/PERM] account disabled", ProviderAuthError),
        (b"-ERR invalid password", ProviderAuthError),
        (b"-ERR [LOGIN-DELAY] wait", ProviderUnavailableError),
        (b"-ERR too many connections", ProviderUnavailableError),
    ],
)
def test_refusals_of_the_login(refusal: bytes, expected: type[Exception]) -> None:
    box = FakePop3Server(login_refusal=refusal)
    with pytest.raises(expected):
        session(box).login("me", "secret")


def test_nothing_works_before_the_login() -> None:
    with pytest.raises(ProviderUnavailableError, match="not connected"):
        session(FakePop3Server()).unique_ids()
    # Ending a session that never began does nothing.
    session(FakePop3Server()).commit()
    session(FakePop3Server()).logout()


def test_a_failed_top_where_the_server_offers_top() -> None:
    box = FakePop3Server()
    one = session(box)
    one.login("me", "secret")
    with pytest.raises(ProviderError, match="no such message"):
        one.headers(9)


def test_an_error_answer_is_a_provider_error() -> None:
    one = session(FakePop3Server())
    one.login("me", "secret")
    with pytest.raises(ProviderError, match="answered with an error"):
        one.delete(9)


def test_capabilities_of_a_server_without_capa() -> None:
    box = FakePop3Server(capabilities=[])
    assert session(box).read_capabilities() == frozenset()


def test_a_size_the_server_does_not_say_counts_as_none() -> None:
    class Odd:
        def list(self, which: int) -> bytes:
            return b"+OK"

    assert pop3_protocol._size(Odd(), 1) == 0


def test_ending_quietly_when_the_connection_is_gone() -> None:
    class Gone:
        closed = False

        def rset(self) -> bytes:
            raise OSError("gone")

        def quit(self) -> bytes:
            raise OSError("gone")

        def close(self) -> None:
            raise OSError("gone")

    one = session(FakePop3Server())
    one._connection = Gone()
    one.logout()  # no error
