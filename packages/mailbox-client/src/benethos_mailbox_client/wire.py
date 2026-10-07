"""What both clients share and neither does itself: where the service
is, the request a call makes, and how an answer or a failure is read.
No module here sends anything. ``client`` and ``sync`` do, each in its
own way, with the same requests and the same readings.
"""

from __future__ import annotations

import codecs
import ipaddress
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from urllib.parse import quote, unquote

import httpx

from .errors import (
    ApiError,
    ConfigurationError,
    MailboxError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)
from .models import Attachment

DEFAULT_URL = "http://127.0.0.1:8080"
URL_ENV = "MAILBOX_SERVICE_URL"
TOKEN_ENV = "MAILBOX_SERVICE_TOKEN"
# Allows http to a host other than this machine, e.g. between containers.
ALLOW_HTTP_ENV = "MAILBOX_SERVICE_ALLOW_HTTP"
# Seconds to wait: for the service to take the connection, for an answer,
# and for an attachment, which may be large.
CONNECT_TIMEOUT = 5.0
TIMEOUT = 30.0
ATTACHMENT_TIMEOUT = 120.0

T = TypeVar("T")


@dataclass(frozen=True)
class Call(Generic[T]):
    """One request to the API, and how its answer becomes what the caller
    gets. ``read`` takes the JSON of the answer, None for no content."""

    method: str
    path: str
    read: Callable[[Any], T]
    params: dict[str, Any] = field(default_factory=dict)
    json: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = TIMEOUT

    @property
    def timeouts(self) -> httpx.Timeout:
        return timeouts(self.timeout)


def timeouts(seconds: float = TIMEOUT) -> httpx.Timeout:
    """How long to wait for the connection, and then for the answer."""
    return httpx.Timeout(seconds, connect=CONNECT_TIMEOUT)


def service_url() -> str:
    """The service's address: ``MAILBOX_SERVICE_URL``, else the default."""
    return (os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")


@dataclass(frozen=True)
class Environment:
    """What the environment says about the service, read at one moment:
    its address, the token, and whether http may go to another machine.
    Unchecked: a client checks it when it is made."""

    url: str
    token: str
    allow_http: bool


def from_environment() -> Environment:
    """``MAILBOX_SERVICE_URL``, ``MAILBOX_SERVICE_TOKEN`` and
    ``MAILBOX_SERVICE_ALLOW_HTTP`` as they are now. A client made without
    them reads them here. A program that makes clients for a long time,
    such as the MCP server, reads them once."""
    allowed = os.environ.get(ALLOW_HTTP_ENV, "").strip().lower()
    return Environment(
        url=service_url(),
        token=os.environ.get(TOKEN_ENV, ""),
        allow_http=allowed in ("1", "true", "yes"),
    )


@dataclass(frozen=True)
class Connection:
    """Where the service is and the token that opens it, checked."""

    base_url: str
    headers: dict[str, str]


def connection(
    base_url: str | None, token: str | None, allow_http: bool | None
) -> Connection:
    """Raises without a token, and when the URL would carry the token
    unencrypted to another machine, unless ``allow_http`` (else
    ``MAILBOX_SERVICE_ALLOW_HTTP``) says so."""
    found = from_environment()
    url = (base_url or found.url).rstrip("/")
    if allow_http is None:
        allow_http = found.allow_http
    _check_url(url, allow_http)
    token = token if token is not None else found.token
    if not token:
        raise ConfigurationError(
            f"{TOKEN_ENV} is not set. Make a token on your user's page in "
            "the service's UI and set it."
        )
    return Connection(url, {"Authorization": f"Bearer {token}"})


def given(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Without the entries that are None: those stay out of a request."""
    return {k: v for k, v in (values or {}).items() if v is not None}


def path(*parts: str) -> str:
    """A path below ``/v1``, each part quoted: an id may come from anyone."""
    return "/v1/" + "/".join(quote(part, safe="") for part in parts)


def answer(response: httpx.Response) -> Any:
    """The JSON of a read answer, None for no content. Raises ``ApiError``
    for an error and for an answer that is not JSON."""
    if response.is_error:
        raise api_error(response)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError:
        raise ApiError(
            response.status_code, "unexpected_response", "the answer is not JSON"
        ) from None


def read(call: Call[T], response: httpx.Response) -> T:
    """What the caller gets of ``response``. An answer of another shape
    than the API describes, such as one without a field the call reads, is
    an ``ApiError`` too, not an error deep inside the reading."""
    found = answer(response)
    try:
        return call.read(found)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ApiError(
            response.status_code,
            "unexpected_response",
            "the answer is not what the API describes",
        ) from None


def api_error(response: httpx.Response) -> ApiError:
    """The error envelope as an ApiError. A validation failure (422) has no
    envelope but a list of what was wrong where, which is what a caller
    needs to correct the call."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        if "code" in error and "message" in error:
            code, message = str(error["code"]), str(error["message"])
            return ApiError(response.status_code, code, message)
    if isinstance(body, dict) and isinstance(body.get("detail"), list):
        reasons = [
            f"{'.'.join(str(p) for p in item.get('loc', ()) if p != 'body')}: "
            f"{item.get('msg', '')}"
            for item in body["detail"]
            if isinstance(item, dict)
        ]
        if reasons:
            reason = "; ".join(reasons)
            return ApiError(response.status_code, "validation_error", reason)
    return ApiError(response.status_code, "unexpected_response", response.reason_phrase)


def failure(exc: httpx.TransportError, base_url: str, seconds: float) -> MailboxError:
    """What went wrong on the way: a service that answers too slowly is
    running, one that cannot be reached is not."""
    if isinstance(exc, httpx.TimeoutException) and not isinstance(
        exc, httpx.ConnectTimeout
    ):
        return ServiceTimeoutError(
            f"mailbox-service did not answer within {seconds:g} s. "
            "Try a narrower request."
        )
    return ServiceUnavailableError(
        f"mailbox-service is not reachable at {base_url}. "
        "Start it with `benethos-mailbox-service serve`."
    )


class Collected:
    """The bytes of an answer read in chunks, up to a limit. ``add``
    answers False once the limit is passed: reading stops there."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.chunks: list[bytes] = []
        self.read = 0
        self.complete = True

    def add(self, chunk: bytes) -> bool:
        self.chunks.append(chunk)
        self.read += len(chunk)
        if self.read > self.max_bytes:
            self.complete = False
        return self.complete


def attachment(headers: httpx.Headers, collected: Collected) -> Attachment:
    """The attachment the headers describe, with the bytes read of it."""
    media, _, options = headers.get(
        "content-type", "application/octet-stream"
    ).partition(";")
    charset = re.search(r"charset=\"?([\w.:-]+)", options)
    name = re.search(
        r"filename\*=UTF-8''([^;]+)", headers.get("content-disposition", "")
    )
    return Attachment(
        data=b"".join(collected.chunks)[: collected.max_bytes],
        content_type=_media_type(media),
        charset=_known_charset(charset.group(1)) if charset else None,
        filename=unquote(name.group(1)) if name else None,
        complete=collected.complete,
    )


# A media type, type/subtype in the characters RFC 6838 allows. The sender
# of a mail chose it, and a caller may show it.
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


def _media_type(value: str) -> str:
    """``value`` when it is a media type and nothing else, else the type of
    unknown bytes."""
    media = value.strip().lower()
    if len(media) <= 127 and _MEDIA_TYPE.fullmatch(media):
        return media
    return "application/octet-stream"


def _check_url(url: str, allow_http: bool) -> None:
    """https anywhere, http to this machine, or anywhere when allowed."""
    try:
        parts = httpx.URL(url)
    except httpx.InvalidURL:
        raise ConfigurationError(f"{URL_ENV} is not a URL: {url}") from None
    if parts.scheme == "https" and parts.host:
        return
    if parts.scheme != "http" or not parts.host:
        raise ConfigurationError(f"{URL_ENV} must be an http or https URL: {url}")
    if allow_http or _loopback(parts.host):
        return
    raise ConfigurationError(
        f"{URL_ENV} is http to {parts.host}, so the token would travel "
        f"unencrypted. Use https, or set {ALLOW_HTTP_ENV}=1 for a network you "
        "trust, such as between containers."
    )


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _known_charset(name: str) -> str | None:
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name
