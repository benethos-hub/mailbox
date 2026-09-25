"""The autoconfig format (``config-v1.1.xml``). The only module that imports
``defusedxml``.

Used by the ISP autoconfig files and by ISPDB, which serve the same format.
A hostile file can neither expand entities nor read local files. Only what
this service can use is kept: IMAP with TLS or STARTTLS, SMTP likewise, a
password or OAuth. Plain-text servers are dropped (CONCEPT 5.8, rule 5).
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from ...errors import ProviderError
from ..http import SafeFetcher
from ..models import (
    Candidate,
    CredentialKind,
    DiscoverySourceName,
    Hint,
    MailServer,
    ProviderType,
    Security,
    ServerProtocol,
)
from .base import Finding

_SECURITY = {"SSL": Security.TLS, "TLS": Security.TLS, "STARTTLS": Security.STARTTLS}
_PASSWORD = {"password-cleartext", "password-encrypted", "plain", "secure"}
_OAUTH = "oauth2"
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_USERNAME_TEMPLATE = re.compile(r"^[^\s<>]{1,256}$")


async def fetch(
    fetcher: SafeFetcher, url: str, domain: str, source: DiscoverySourceName
) -> Finding | None:
    """The finding an autoconfig file at ``url`` gives, marked as coming
    from ``source``; None when nothing is there."""
    fetched = await fetcher.get(url)
    if fetched is None:
        return None
    candidates = parse(fetched.body, domain, source)
    return Finding(candidates=tuple(candidates), answered_by=fetched.host)


def parse(xml: bytes, domain: str, source: DiscoverySourceName) -> list[Candidate]:
    """One candidate per usable IMAP server, in the file's order."""
    try:
        root = fromstring(xml)
    except (ParseError, DefusedXmlException, ValueError) as exc:
        raise ProviderError(f"the autoconfig file is not valid: {exc}") from None
    provider = root.find("emailProvider")
    if root.tag != "clientConfig" or provider is None:
        raise ProviderError("the autoconfig file has no emailProvider")

    name = _text(provider, "displayName")
    hints = [hint for doc in provider.iter("documentation") if (hint := _hint(doc))]
    smtp = [
        server
        for element in provider.iter("outgoingServer")
        if element.get("type") == "smtp"
        and (server := _server(element, ServerProtocol.SMTP, domain))
    ]
    candidates = []
    for element in provider.iter("incomingServer"):
        if element.get("type") != "imap":
            continue
        imap = _server(element, ServerProtocol.IMAP, domain)
        credential = _credential(element)
        if imap is None or credential is None:
            continue
        candidates.append(
            Candidate(
                provider=ProviderType.IMAP,
                name=name,
                credential=credential,
                servers=[imap, *smtp[:1]],
                hints=hints,
                source=source,
            )
        )
    return candidates


def _text(element: Element, tag: str) -> str | None:
    found = element.find(tag)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _server(
    element: Element, protocol: ServerProtocol, domain: str
) -> MailServer | None:
    host = _host(_text(element, "hostname"), domain)
    security = _SECURITY.get((_text(element, "socketType") or "").upper())
    port = _port(_text(element, "port"))
    if host is None or security is None or port is None:
        return None
    username = _text(element, "username")
    if username is not None and not _USERNAME_TEMPLATE.match(username):
        username = None
    return MailServer(
        protocol=protocol, host=host, port=port, security=security, username=username
    )


def _host(value: str | None, domain: str) -> str | None:
    if not value:
        return None
    value = value.replace("%EMAILDOMAIN%", domain).lower().rstrip(".")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return value if _HOST.match(value) else None


def _port(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    port = int(value)
    return port if 0 < port < 65536 else None


def _credential(element: Element) -> CredentialKind | None:
    methods = {(e.text or "").strip().lower() for e in element.iter("authentication")}
    if methods & _PASSWORD:
        return CredentialKind.PASSWORD
    if _OAUTH in methods:
        return CredentialKind.OAUTH
    return None


def _hint(element: Element) -> Hint | None:
    url = element.get("url")
    if url is not None and not url.startswith("https://"):
        url = None
    descriptions = element.findall("descr")
    english = [d for d in descriptions if d.get("lang") in (None, "en")]
    chosen = english or descriptions
    text = (chosen[0].text or "").strip() if chosen else ""
    if not text and url is None:
        return None
    return Hint(text=text or "Setup instructions of the provider", url=url)
