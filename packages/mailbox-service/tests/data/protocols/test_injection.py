"""What a caller writes cannot become a command of a mail protocol.

Each protocol was read against its specification for what ends a value
or a command. IMAP, POP3 and SMTP are protocols of lines: CR, LF and NUL
end a command, and a quote or a backslash only matters inside an IMAP
quoted string, which the library escapes. Graph's ``$search`` is KQL
inside quotes. JMAP sends JSON, which carries every character as data.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from benethos_mailbox_service.data.models import MessageFilter
from benethos_mailbox_service.data.protocols import Server
from benethos_mailbox_service.data.protocols.imap import ImapSession
from benethos_mailbox_service.data.protocols.pop3 import Pop3Session
from benethos_mailbox_service.data.protocols.smtp import SmtpLogin, SmtpSession
from benethos_mailbox_service.data.protocols.transport import refuse_line_ends
from benethos_mailbox_service.data.providers.jmap import mappers as jmap
from benethos_mailbox_service.data.providers.microsoft import mappers as graph
from benethos_mailbox_service.errors import BadRequestError, MailboxServiceError

from ...imap_fake import FakeMailBox
from ...smtp_fake import FakeSmtpServer

# What ends a line or a command, and what does not.
ENDS = ["\r\n", "\n", "\r", "\x00"]
HARMLESS = ['"', "'", "\\", "\u2028", "\x85"]
SERVER = Server("mail.example.com", 993, "tls")


class Unreachable:
    """A connection factory that notes each call and connects nowhere."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, server: Any, timeout: float) -> Any:
        self.calls += 1
        raise OSError("not connected in this test")


@pytest.mark.parametrize("end", ENDS)
def test_a_line_end_is_refused(end: str) -> None:
    with pytest.raises(BadRequestError, match="the password must not hold"):
        refuse_line_ends("me", f"secret{end}A1 DELETE INBOX", what="the password")


@pytest.mark.parametrize("value", HARMLESS)
def test_what_ends_no_line_passes(value: str) -> None:
    refuse_line_ends(f"a{value}b", what="it")


@pytest.mark.parametrize("end", ENDS)
def test_an_imap_login_with_a_line_end_never_connects(end: str) -> None:
    factory = Unreachable()
    session = ImapSession(SERVER, client_factory=factory)
    with pytest.raises(BadRequestError):
        session.login("me", f"x{end}A1 LOGOUT")
    with pytest.raises(BadRequestError):
        session.login_oauth(f"me{end}", "token")
    assert factory.calls == 0


@pytest.mark.parametrize("value", HARMLESS)
def test_an_imap_login_with_a_quote_goes_to_the_server(value: str) -> None:
    factory = Unreachable()
    with pytest.raises(MailboxServiceError):
        ImapSession(SERVER, client_factory=factory).login("me", f"x{value}y")
    assert factory.calls == 1


def _folder_commands(session: ImapSession, name: str) -> list[Callable[[], Any]]:
    """Every command of a session that takes a folder name, with ``name``."""
    return [
        lambda: session.select(name),
        lambda: session.select_writable(name),
        lambda: session.folders.folder_state(name),
        lambda: session.folders.create_folder(name),
        lambda: session.folders.rename_folder(name, "New"),
        lambda: session.folders.rename_folder("INBOX", name),
        lambda: session.folders.delete_folder(name),
        lambda: session.messages.move([1], name),
        lambda: session.messages.append(name, b"Subject: x\r\n\r\nx", []),
    ]


@pytest.mark.parametrize("end", ENDS)
def test_an_imap_folder_name_with_a_line_end_never_reaches_the_server(
    end: str, server: FakeMailBox
) -> None:
    session = ImapSession(SERVER, client_factory=server)
    session.login("me", "secret")
    asked = len(server.calls)
    for command in _folder_commands(session, f'INBOX"{end}Z99 DELETE "Important'):
        with pytest.raises(BadRequestError, match="the folder name must not hold"):
            command()
    assert server.calls[asked:] == []


@pytest.mark.parametrize("name", ["Ordner mit Ä", "a/b.c", "100% *wichtig*"])
def test_an_imap_folder_name_without_one_goes_to_the_server(
    name: str, server: FakeMailBox
) -> None:
    session = ImapSession(SERVER, client_factory=server)
    session.login("me", "secret")
    session.folders.create_folder(name)
    session.select(name)
    assert ("create", name) in server.calls
    assert ("select", name, True) in server.calls


@pytest.mark.parametrize("end", ENDS)
def test_a_pop3_login_with_a_line_end_never_connects(end: str) -> None:
    factory = Unreachable()
    session = Pop3Session(SERVER, connection_factory=factory)
    with pytest.raises(BadRequestError):
        session.login(f"me{end}DELE 1", "secret")
    with pytest.raises(BadRequestError):
        session.login("me", f"secret{end}DELE 1")
    assert factory.calls == 0


@pytest.mark.parametrize("bad", [*ENDS, " ", "\t", "\u2028", "\x85"])
def test_an_smtp_address_with_a_break_never_connects(bad: str) -> None:
    fake = FakeSmtpServer()
    session = SmtpSession(SERVER, connection_factory=fake)
    login = SmtpLogin("me@example.com", "secret")
    with pytest.raises(BadRequestError, match="no address"):
        session.send(login, "me@example.com", [f"you{bad}@example.org"], b"x")
    with pytest.raises(BadRequestError, match="no address"):
        session.send(login, f"me@example.com{bad}RCPT TO:<x@y>", ["a@b.c"], b"x")
    assert fake.calls == []


@pytest.mark.parametrize("bad", [*ENDS, "\x01"])
def test_an_xoauth2_login_with_a_control_character_never_logs_in(bad: str) -> None:
    fake = FakeSmtpServer()
    login = SmtpLogin(f"me@example.com{bad}auth=x", "token", auth="xoauth2")
    with pytest.raises(BadRequestError):
        SmtpSession(SERVER, connection_factory=fake).verify(login)


@pytest.mark.parametrize("value", [*HARMLESS, "\r\n", "a' OR from:'x"])
def test_a_graph_search_value_stays_inside_its_phrase(value: str) -> None:
    for field in ("text", "sender", "to", "subject"):
        params, _ = graph.query(MessageFilter.model_construct(**{field: value}))
        search = params["$search"]
        # The outer double quotes, one phrase in single quotes, nothing more.
        assert search.startswith('"') and search.endswith('"')
        assert '"' not in search[1:-1]
        assert search.count("'") == 2
        assert "\\" not in search


@pytest.mark.parametrize("value", [*HARMLESS, *ENDS])
def test_a_jmap_filter_carries_any_value_as_data(value: str) -> None:
    text = f"a{value}b"
    sent = json.loads(
        json.dumps(jmap.query_filter("m1", MessageFilter.model_construct(text=text)))
    )
    assert sent["conditions"] == [{"inMailbox": "m1"}, {"text": text}]
