"""The packages as installed, as real processes. Not a test.

The suite calls the service through a test client and mocks the REST API
for the MCP server. It does not see the service under its real server, nor
what the MCP SDK makes of a result and an error on the way to a client. This
script looks at both, with the interpreter it runs under:

- the service: ``keys generate``, ``keys init`` and ``users create-admin`` as
  an operator runs them, then ``serve`` on a free port with a database in a
  scratch folder. ``/health`` names the installed version, the API refuses a
  request without a token in its envelope, and the one-time password signs
  in through the form and leads to the page that asks for a new one
- the MCP server: spawned over stdio as a client does. It refuses to start
  without its service, and alone in an environment it has none, so a stand-in
  on a free port answers the two questions it asks. It introduces itself,
  lists its tools with their annotations, answers ``list_accounts`` and
  ``server_status`` with the installed version, and answers a service in
  trouble, an unknown tool and an argument of the wrong type each with an
  error result. The real service behind it stays the live check
  ``live/mcp_stdio.py``
- the client and the common package: they import, under the installed version

Exits with 0 when every answer is as expected and with 1 otherwise. No
account and no mail server, and nothing but ``127.0.0.1``. The settings of
this machine stay out, since an empty settings file replaces the search for
one. ``.github/workflows/freshness.yml`` runs it on the newest versions the
ranges allow, and on each published package alone, which ``FRESHNESS_PACKAGE``
names. ``uv run python tests/installed_check.py`` runs it on the checkout.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SERVICE = "benethos-mailbox-service"
MCP = "benethos-mailbox-mcp"
CLIENT = "benethos-mailbox-client"
COMMON = "benethos-mailbox-common"
# How long the service may take to answer, and the whole MCP conversation.
TIMEOUT = 60.0

failures: list[str] = []


def check(condition: bool, what: str) -> None:
    if not condition:
        failures.append(what)


def program(name: str) -> str:
    """The console script beside this interpreter, not one on the path."""
    command = shutil.which(name, path=str(Path(sys.executable).parent))
    if command is None:
        raise FileNotFoundError(f"{name} is not installed beside {sys.executable}")
    return command


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def scratch_folder() -> Iterator[Path]:
    """A folder that is gone at the end. On Windows a console script and a
    virtual environment's python.exe are launchers: ending one leaves the
    real process a moment longer, which holds its files open."""
    folder = Path(tempfile.mkdtemp(prefix="mailbox-installed-check-"))
    try:
        yield folder
    finally:
        for _ in range(20):
            try:
                shutil.rmtree(folder)
                break
            except OSError:
                time.sleep(0.5)


def service_env(scratch: Path, port: int) -> dict[str, str]:
    """A service of this script: its data in ``scratch``, the master key in
    the environment once ``keys generate`` made it, no background sync."""
    settings = scratch / "empty.env"
    settings.write_text("", encoding="utf-8")
    return {
        **os.environ,
        "MAILBOX_SERVICE_ENV_FILE": str(settings),
        "MAILBOX_SERVICE_DATA_DIR": str(scratch / "data"),
        "MAILBOX_SERVICE_STORAGE": "sqlite",
        "MAILBOX_SERVICE_KEY_PROVIDER": "env",
        "MAILBOX_SERVICE_HOST": "127.0.0.1",
        "MAILBOX_SERVICE_PORT": str(port),
        "MAILBOX_SERVICE_SYNC_INTERVAL": "0",
        "MAILBOX_SERVICE_SYNC_IDLE": "false",
    }


def command_output(env: dict[str, str], cwd: Path, *args: str) -> str:
    """What a command of the service prints. Keys and passwords come this
    way, so a failure names the command and the exit code and nothing it
    printed."""
    done = subprocess.run(
        [program(SERVICE), *args], env=env, cwd=cwd, capture_output=True, text=True
    )
    if done.returncode != 0:
        raise RuntimeError(f"{SERVICE} {' '.join(args)}: exit {done.returncode}")
    return done.stdout.strip()


def wait_for_health(client: Any, process: subprocess.Popen[bytes]) -> Any:
    """The answer of ``/health``, once the service gives one."""
    import httpx

    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{SERVICE} serve ended with {process.returncode}")
        try:
            return client.get("/health")
        except httpx.TransportError:
            time.sleep(0.5)
    raise TimeoutError(f"{SERVICE} did not answer within {TIMEOUT:.0f} s")


def sign_in(client: Any, password: str) -> Any:
    """The sign-in form, sent with the nonce of its page."""
    page = client.get("/ui/login")
    check(page.status_code == 200, f"/ui/login answered {page.status_code}")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    check(nonce is not None, "/ui/login holds no nonce")
    return client.post(
        "/ui/login",
        data={
            "name": "admin",
            "password": password,
            "nonce": nonce.group(1) if nonce else "",
        },
    )


def check_service() -> None:
    import httpx

    version = importlib.metadata.version(SERVICE)
    with scratch_folder() as scratch:
        port = free_port()
        env = service_env(scratch, port)
        env["MAILBOX_SERVICE_MASTER_KEY"] = command_output(
            env, scratch, "keys", "generate"
        )
        command_output(env, scratch, "keys", "init")
        one_time = command_output(env, scratch, "users", "create-admin")
        process = subprocess.Popen(
            [program(SERVICE), "serve"],
            env=env,
            cwd=scratch,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=30, follow_redirects=True
            ) as client:
                health = wait_for_health(client, process)
                check(
                    health.status_code == 200
                    and health.json().get("version") == version,
                    f"/health answered {health.status_code}, not version {version}",
                )
                refused = client.get("/v1/me")
                check(
                    refused.status_code == 401 and "error" in refused.json(),
                    f"/v1/me without a token answered {refused.status_code}",
                )
                signed_in = sign_in(client, one_time)
                check(
                    signed_in.url.path == "/ui/password",
                    f"the one-time password led to {signed_in.url.path}",
                )
        finally:
            process.terminate()
            process.wait(timeout=10)


def text_of(result: Any) -> str:
    return "".join(getattr(part, "text", "") for part in result.content)


class StandIn(BaseHTTPRequestHandler):
    """What the MCP server asks its service: the version, and what the token
    may do, a user with no account and no right. ``trouble`` makes the second
    answer an error in the service's envelope."""

    version = ""
    trouble = False

    def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
        status, body = 404, {"error": {"code": "not_found", "message": "no"}}
        if self.path == "/health":
            status, body = 200, {"status": "ok", "version": self.version}
        elif self.path == "/v1/me" and StandIn.trouble:
            message = "the stand-in is in trouble"
            status, body = 503, {"error": {"code": "unavailable", "message": message}}
        elif self.path == "/v1/me":
            me = {"user_id": "usr_1", "name": "check", "accounts": [], "operations": []}
            status, body = 200, me
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        """Keeps each request out of the output of the check."""


@contextmanager
def stand_in(version: str) -> Iterator[str]:
    """The address of a stand-in of the service, which names ``version``."""
    StandIn.version, StandIn.trouble = version, False
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def converse(scratch: Path, url: str) -> None:
    """One session with the MCP server, as a client holds it. It asks what
    the token may do only at its start, so nothing moves the tools under the
    conversation."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import get_default_environment, stdio_client

    version = importlib.metadata.version(MCP)
    settings = scratch / "empty.env"
    settings.write_text("", encoding="utf-8")
    parameters = StdioServerParameters(
        command=program(MCP),
        cwd=str(scratch),
        env=get_default_environment()
        | {
            "PYTHONIOENCODING": "utf-8",
            "MAILBOX_MCP_ENV_FILE": str(settings),
            "MAILBOX_MCP_LOG_LEVEL": "ERROR",
            "MAILBOX_MCP_RIGHTS_SECONDS": "0",
            "MAILBOX_SERVICE_URL": url,
            "MAILBOX_SERVICE_TOKEN": "stand-in",
        },
    )
    async with (
        stdio_client(parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        check(
            init.server_info.name == MCP,
            f"the server introduced itself as {init.server_info.name!r}",
        )

        listed = (await session.list_tools()).tools
        names = {tool.name for tool in listed}
        check(
            {"server_status", "list_accounts"} <= names,
            f"the tool list holds {sorted(names)}",
        )
        bare = [
            tool.name
            for tool in listed
            if tool.annotations is None or tool.annotations.read_only_hint is None
        ]
        check(not bare, f"tools without annotations: {bare}")

        status = await session.call_tool("server_status", {})
        text = text_of(status)
        check(
            status.is_error is not True
            and text.startswith(f"name: {MCP}\nversion: {version}\n"),
            f"the status answered is_error={status.is_error} {text[:80]!r}",
        )

        accounts = await session.call_tool("list_accounts", {})
        check(
            accounts.is_error is not True and accounts.structured_content is not None,
            f"list_accounts answered is_error={accounts.is_error}",
        )

        StandIn.trouble = True
        troubled = await session.call_tool("list_accounts", {})
        text = text_of(troubled)
        check(
            troubled.is_error is True and "the stand-in is in trouble" in text,
            f"a service in trouble answered is_error={troubled.is_error} {text!r}",
        )

        unknown = await session.call_tool("no_such_tool", {})
        check(
            unknown.is_error is True and "no_such_tool" in text_of(unknown),
            f"an unknown tool answered is_error={unknown.is_error}",
        )

        wrong = await session.call_tool("server_status", {"details": ["x"]})
        check(
            wrong.is_error is True and "details" in text_of(wrong),
            f"a wrong type answered is_error={wrong.is_error}",
        )
    print(
        f"{MCP} {version} over stdio, mcp {importlib.metadata.version('mcp')}, "
        f"{len(listed)} tools listed"
    )


def check_mcp() -> None:
    import anyio

    async def within_time(scratch: Path, url: str) -> None:
        with anyio.fail_after(TIMEOUT):
            await converse(scratch, url)

    with scratch_folder() as scratch, stand_in(importlib.metadata.version(MCP)) as url:
        anyio.run(within_time, scratch, url)


def check_import(distribution: str) -> None:
    module = importlib.import_module(distribution.replace("-", "_"))
    version = importlib.metadata.version(distribution)
    check(
        module.__version__ == version,
        f"{distribution} says {module.__version__}, installed is {version}",
    )


def check_client() -> None:
    check_import(CLIENT)


def check_common() -> None:
    check_import(COMMON)


CHECKS: dict[str, Callable[[], None]] = {
    SERVICE: check_service,
    CLIENT: check_client,
    MCP: check_mcp,
    COMMON: check_common,
}


def leaves(exc: BaseException) -> list[BaseException]:
    """The exceptions inside a group, since the MCP client runs a task
    group."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for sub in exc.exceptions for leaf in leaves(sub)]
    return [exc]


def main() -> int:
    """The package ``FRESHNESS_PACKAGE`` names, else all four. Every failure
    is a finding, and exit code 3 would read as a rate limit, so it is 1."""
    package = os.environ.get("FRESHNESS_PACKAGE")
    if package and package not in CHECKS:
        print(f"FAIL: no check for the package {package}", file=sys.stderr)
        return 1
    for name in [package] if package else CHECKS:
        try:
            CHECKS[name]()
        except Exception as exc:  # noqa: BLE001 - every failure is a finding
            traceback.print_exception(exc, file=sys.stderr)
            failures.extend(
                f"{name}: {type(leaf).__name__}: {leaf}" for leaf in leaves(exc)
            )
        print(f"checked {name} {importlib.metadata.version(name)}")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
