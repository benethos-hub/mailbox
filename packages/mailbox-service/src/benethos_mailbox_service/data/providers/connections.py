"""How each kind of account is connected (``Connection``): the settings
its adapter takes, in words a form shows, and where a person signs in
instead. The UI draws its forms from these and knows no provider
(docs/UNIFORM.md, U6)."""

from __future__ import annotations

from collections.abc import Mapping

from ..models import Connection, ProviderType, SettingField, Summary
from ..protocols import IMAP_PORTS, JMAP_PATH, JMAP_PORT, POP3_PORTS, SMTP_PORTS

_SECURITY = (("tls", "tls"), ("starttls", "starttls"))


def _ports(ports: Mapping[str, int]) -> str:
    return f"Empty: {ports['tls']} for tls, {ports['starttls']} for starttls."


def _mail_server(protocol: str, ports: Mapping[str, int]) -> tuple[SettingField, ...]:
    """A server that reads mail, beside an SMTP server that sends it."""
    return (
        SettingField("host", f"{protocol} server", required=True),
        SettingField("port", f"{protocol} port", _ports(ports), number=True),
        SettingField(
            "security", f"{protocol} security", choices=_SECURITY, default="tls"
        ),
        SettingField("username", "Login name", "Empty: the address.", login=True),
        SettingField(
            "smtp_host", "SMTP server", "For sending. Empty: this account only reads."
        ),
        SettingField("smtp_port", "SMTP port", _ports(SMTP_PORTS), number=True),
        SettingField(
            "smtp_security",
            "SMTP security",
            choices=(("", "default (tls)"), *_SECURITY),
        ),
        SettingField(
            "smtp_username",
            "SMTP login name",
            "Empty: the login name above.",
            login=True,
        ),
    )


def _sums_up(protocol: str) -> tuple[Summary, ...]:
    return (
        Summary(protocol, "host", "port"),
        Summary("SMTP", "smtp_host", "smtp_port"),
    )


CONNECTIONS: Mapping[ProviderType, Connection] = {
    ProviderType.IMAP: Connection(
        kind=ProviderType.IMAP.value,
        name="IMAP",
        fields=_mail_server("IMAP", IMAP_PORTS),
        by_hand=True,
        summary=_sums_up("IMAP"),
    ),
    ProviderType.POP3: Connection(
        kind=ProviderType.POP3.value,
        name="POP3",
        about="the inbox only, no folders, no read state",
        fields=_mail_server("POP3", POP3_PORTS),
        by_hand=True,
        summary=_sums_up("POP3"),
    ),
    ProviderType.JMAP: Connection(
        kind=ProviderType.JMAP.value,
        name="JMAP",
        fields=(
            SettingField("host", "JMAP server", required=True),
            SettingField(
                "port", "Port", f"Empty: {JMAP_PORT}. Always HTTPS.", number=True
            ),
            SettingField("path", "Session path", f"Empty: {JMAP_PATH}.", login=True),
            SettingField(
                "auth",
                "Sign in with",
                choices=(("password", "a password"), ("token", "an API token")),
                default="password",
            ),
            SettingField(
                "username",
                "Login name",
                "With a password. Empty: the address.",
                login=True,
            ),
        ),
        secret="Password or API token",
        by_hand=True,
        summary=(Summary("JMAP", "host", "port", "path"),),
    ),
    ProviderType.GMAIL: Connection(
        kind=ProviderType.GMAIL.value, name="Gmail", signs_in_at="Google"
    ),
    ProviderType.MICROSOFT: Connection(
        kind=ProviderType.MICROSOFT.value, name="Microsoft", signs_in_at="Microsoft"
    ),
    # For tests and trying the service: it takes a mail server's settings
    # and keeps them.
    ProviderType.MEMORY: Connection(
        kind=ProviderType.MEMORY.value,
        name="Memory",
        fields=_mail_server("Memory", IMAP_PORTS),
        summary=_sums_up("Memory"),
    ),
}


def connection_of(kind: ProviderType) -> Connection:
    return CONNECTIONS[kind]
