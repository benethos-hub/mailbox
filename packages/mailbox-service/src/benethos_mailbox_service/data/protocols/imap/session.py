"""One IMAP session: the connection, the login, the selected folder and
IDLE. Its folders and messages are ``folders`` and ``messages``."""

from __future__ import annotations

import imaplib
import re
import time
from collections.abc import Callable
from typing import Any

from imapclient import IMAPClient
from imapclient.exceptions import LoginError

from ....errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    missing,
)
from ..transport import Server, refuse_line_ends, text
from .folders import Folders
from .messages import Messages
from .responses import capabilities, quietly_logout, translated, uidvalidity
from .values import MAX_MESSAGE_BYTES, Selected

ClientFactory = Callable[..., Any]

# How often a waiting IDLE looks whether it should stop. Costs no traffic.
IDLE_STEP = 5.0

# What an untagged response during IDLE says changed.
_CHANGES = {b"EXISTS", b"EXPUNGE", b"FETCH", b"VANISHED"}

# RFC 5530 response codes. The first say the credential is wrong, the
# second that the server cannot take a login now: too many connections,
# a mailbox in use, a store that is down. A refusal without a code counts
# as a rejected credential, as most servers answer a wrong password so.
_REJECTED = ("[AUTHENTICATIONFAILED]", "[AUTHORIZATIONFAILED]", "[EXPIRED]")
_FOR_NOW = ("[UNAVAILABLE]", "[INUSE]", "[LIMIT]", "[SERVERBUG]")
_FOR_NOW_TEXT = re.compile(r"too many|try again later", re.IGNORECASE)


def default_client(server: Server, timeout: float) -> Any:
    address, context = server.endpoint()
    if server.security == "starttls":
        client = IMAPClient(address, server.port, ssl=False, timeout=timeout)
        client.starttls(context)
        return client
    return IMAPClient(
        address, server.port, ssl=True, ssl_context=context, timeout=timeout
    )


class ImapSession:
    def __init__(
        self,
        server: Server,
        timeout: float = 30.0,
        client_factory: ClientFactory = default_client,
        client_id: tuple[str, str] | None = None,
        max_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self._server = server
        self._timeout = timeout
        self._factory = client_factory
        self._client_id = client_id
        self._client: Any = None
        self.folders = Folders(self)
        self.messages = Messages(self, max_bytes)

    @property
    def connected(self) -> bool:
        return self._client is not None

    def client(self) -> Any:
        """The library's client of the logged-in connection."""
        if self._client is None:
            raise ProviderError("not connected")
        return self._client

    # --- the connection -------------------------------------------------------------

    def login(self, username: str, password: str) -> None:
        refuse_line_ends(username, password, what="the user name or password")
        if (username + password).isascii():
            self._log_in(lambda c: c.login(username, password), "login")
        else:
            # LOGIN carries ASCII alone. SASL PLAIN carries UTF-8 (RFC 4616).
            self._log_in(lambda c: _plain_login(c, username, password), "login")

    def login_oauth(self, username: str, access_token: str) -> None:
        refuse_line_ends(username, access_token, what="the user name or token")
        self._log_in(lambda c: c.oauth2_login(username, access_token), "token")

    def _log_in(self, authenticate: Callable[[Any], Any], what: str) -> None:
        with translated():
            client = self._connect()
            try:
                authenticate(client)
            except LoginError as exc:
                quietly_logout(client)
                raise _login_refused(exc, what) from None
            except BaseException:
                quietly_logout(client)
                raise
            self._client = client

    def _connect(self) -> Any:
        client = self._factory(self._server, self._timeout)
        if self._client_id is not None:
            _send_id(client, *self._client_id)
        return client

    def read_capabilities(self) -> frozenset[str]:
        """Connect without logging in and return what the server announces
        after TLS or STARTTLS. Sends no credential."""
        with translated():
            client = self._factory(self._server, self._timeout)
            try:
                return capabilities(client)
            finally:
                quietly_logout(client)

    def server_capabilities(self) -> frozenset[str]:
        """What the server announces now, after the login."""
        with translated():
            return capabilities(self.client())

    def logout(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            quietly_logout(client)

    def noop(self) -> None:
        """Lets the server catch up the selected folder. Until then STATUS
        on that folder may answer the state from when it was selected
        (RFC 3501), and a change another client made goes unseen."""
        with translated():
            self.client().noop()

    # --- the selected folder --------------------------------------------------------

    def select(self, folder: str) -> int:
        """Select a folder read-only, return its UIDVALIDITY."""
        with translated():
            answer = self._select_folder(folder, readonly=True)
        return uidvalidity(answer)

    def select_writable(self, folder: str) -> Selected:
        """Select a folder read-write."""
        with translated():
            answer = self._select_folder(folder, readonly=False)
        if b"READ-ONLY" in answer:
            raise ProviderError(f"the folder {folder} is read-only on the server")
        permanent = answer.get(b"PERMANENTFLAGS", ())
        return Selected(uidvalidity(answer), frozenset(text(f) for f in permanent))

    def _select_folder(self, folder: str, readonly: bool) -> dict[bytes, Any]:
        """SELECT or EXAMINE. A folder that is gone, e.g. renamed by another
        client, is ``NotFoundError`` rather than a server error."""
        client = self.client()
        try:
            answer: dict[bytes, Any] = client.select_folder(folder, readonly=readonly)
        except imaplib.IMAP4.error:
            if not client.folder_exists(folder):
                raise missing("folder", folder) from None
            raise
        return answer

    def idle(
        self,
        timeout: float,
        stopped: Callable[[], bool],
        step: float = IDLE_STEP,
        clock: Callable[[], float] = time.monotonic,
    ) -> bool:
        """IDLE in the selected folder until the server reports a change,
        ``timeout`` passes or ``stopped`` says so. Looks at ``stopped`` every
        ``step`` seconds, which costs no traffic. True on a change."""
        with translated():
            client = self.client()
            client.idle()
            try:
                return _idle_until(client, clock() + timeout, stopped, step, clock)
            finally:
                if self._client is not None:
                    try:
                        client.idle_done()
                    except (imaplib.IMAP4.error, OSError):
                        # The connection is spoiled. Start afresh next time.
                        self.logout()


def _idle_until(
    client: Any,
    deadline: float,
    stopped: Callable[[], bool],
    step: float,
    clock: Callable[[], float],
) -> bool:
    while not stopped():
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        responses = client.idle_check(timeout=min(step, remaining))
        if any(r and r[0] == b"BYE" for r in responses):
            raise ProviderUnavailableError("the mail server ended the connection")
        if any(_CHANGES.intersection(r[:2]) for r in responses):
            return True
    return False


def _send_id(client: Any, name: str, version: str) -> None:
    """RFC 2971 ID, where the server offers it. Some servers require it."""
    if b"ID" not in client.capabilities():
        return
    try:
        client.id_({"name": name, "version": version})
    except (imaplib.IMAP4.error, OSError):
        pass


def _login_refused(exc: LoginError, what: str) -> Exception:
    """imapclient wraps whatever the login raised. A dropped connection is
    not a rejected credential, nor is a refusal for now."""
    cause = exc.__context__
    if isinstance(cause, imaplib.IMAP4.abort | OSError):
        return ProviderUnavailableError(
            f"the mail server dropped the connection during the {what}"
        )
    if _for_now(str(exc)):
        return ProviderUnavailableError(f"the mail server refused the {what} for now")
    return ProviderAuthError(f"the server rejected the {what}")


def _for_now(refusal: str) -> bool:
    """Whether the server's refusal of a login is temporary."""
    upper = refusal.upper()
    if any(code in upper for code in _REJECTED):
        return False
    return any(code in upper for code in _FOR_NOW) or bool(
        _FOR_NOW_TEXT.search(refusal)
    )


def _plain_login(client: Any, username: str, password: str) -> None:
    if b"AUTH=PLAIN" not in client.capabilities():
        raise BadRequestError(
            "the user name or password goes beyond ASCII, and the mail server "
            "offers no AUTH=PLAIN, which could carry it"
        )
    client.plain_login(username, password)
