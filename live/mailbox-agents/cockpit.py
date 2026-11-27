"""The live check of the cockpit, against the test account of
containers/live/mailbox-agents/. It writes nothing to that account.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/cockpit.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

It runs ``backfill`` of the agent counting into a state file in a folder
of its own, so the worker writes its profile, then starts the command
``cockpit`` as a process on a free port, with a secret from a file of the
same folder. It signs in and reads the overview, the page of the instance
and the page of one message: the instance stands there with its stage,
and a message shows the subject the mailbox service names for it. A wrong
secret is refused. A second cockpit without the token of the service
shows the ids alone. Each check says ok or FAILED, and the exit code is 1
if one failed. Never point it at an account that is not a test account.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from agents_common import (  # beside this script
    DAYS,
    ENV,
    connect_mailbox,
    live_settings,
    run_checks,
)

from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.settings import PREFIX, Settings
from benethos_mailbox_agents.store import Store

SECRET = "live-cockpit-secret-value"  # pragma: allowlist secret
# How long the cockpit may take to open its port.
START_SECONDS = 30
# How long a page may take: it asks the service for each of 50 messages.
PAGE = 120


@dataclass
class Live:
    settings: Settings
    env_file: Path
    folder: Path
    ref: MessageRef | None = None


def _environment(live: Live, **values: str) -> dict[str, str]:
    """The environment of a process of the agents: no setting of this
    shell, the folder of the check, and ``values``."""
    found = {k: v for k, v in os.environ.items() if not k.upper().startswith(PREFIX)}
    found[f"{PREFIX}DATA_DIR"] = str(live.folder / "data")
    found.update({f"{PREFIX}{name.upper()}": value for name, value in values.items()})
    return found


def _command(live: Live, *args: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "benethos_mailbox_agents",
        "--env-file",
        str(live.env_file),
        *args,
    ]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@contextmanager
def _cockpit(live: Live, **values: str) -> Iterator[str]:
    """The command cockpit as a process, until the block ends. Answers
    its address."""
    port = _free_port()
    secret = live.folder / "cockpit_secret"
    secret.write_text(SECRET, encoding="utf-8")
    process = subprocess.Popen(
        _command(live, "cockpit"),
        env=_environment(
            live, cockpit_port=str(port), cockpit_secret_file=str(secret), **values
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(START_SECONDS * 10):
            try:
                httpx.get(f"{url}/login", timeout=1)
                break
            except httpx.TransportError:
                if process.poll() is not None:
                    said = process.stderr.read() if process.stderr else ""
                    raise AssertionError(f"the cockpit ended: {said}") from None
                time.sleep(0.1)
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def _signed_in(client: httpx.Client, secret: str = SECRET) -> httpx.Response:
    page = client.get("/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    if nonce is None:
        raise AssertionError("the sign-in page holds no nonce")
    return client.post("/login", data={"secret": secret, "nonce": nonce[1]})


async def profile(live: Live) -> str:
    done = subprocess.run(
        _command(live, "backfill", "--agent", "counting", "--days", str(DAYS)),
        env=_environment(live),
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise AssertionError(f"backfill ended with {done.returncode}: {done.stderr}")
    with Store.open(live.folder / "data" / "counting.db", read_only=True) as store:
        found = store.profile()
        rows = store.messages(None, 1)
    if found is None:
        raise AssertionError("the state file holds no profile")
    if not rows:
        raise AssertionError("counting took up no message")
    live.ref = rows[0].ref
    return f"stage {found.stage}, {found.poll_seconds:g} s between polls"


async def pages(live: Live) -> str:
    if live.ref is None:
        raise AssertionError("no message to look at")
    async with connect_mailbox(live.settings) as mailbox:
        subject = (await mailbox.message(live.ref)).subject or ""
    with _cockpit(live) as url, httpx.Client(base_url=url, timeout=PAGE) as client:
        if _signed_in(client).headers.get("location") != "/":
            raise AssertionError("the right secret did not sign in")
        overview = client.get("/").text
        started = time.monotonic()
        instance = client.get("/agents/counting").text
        took = time.monotonic() - started
    if "counting" not in overview or ">shadow<" not in overview:
        raise AssertionError("the overview does not show counting in shadow")
    if html.escape(subject, quote=False) not in instance:
        raise AssertionError("the page of the instance does not show the subject")
    return (
        "the overview shows counting in shadow, its page a subject of the "
        f"account, in {took:.1f} s"
    )


async def wrong(live: Live) -> str:
    with _cockpit(live) as url, httpx.Client(base_url=url) as client:
        answer = _signed_in(client, "not-the-secret")
        held = client.get("/")
    if answer.headers.get("location") != "/login?notice=wrong":
        raise AssertionError("a wrong secret was not refused")
    if held.status_code != 303:
        raise AssertionError("a page answered without a session")
    return "refused, and no page without a session"


async def ids_alone(live: Live) -> str:
    if live.ref is None:
        raise AssertionError("no message to look at")
    with (
        _cockpit(live, service_token="", service_token_file="") as url,
        httpx.Client(base_url=url) as client,
    ):
        _signed_in(client)
        instance = client.get("/agents/counting").text
    if "Subject and sender are shown with a token" not in instance:
        raise AssertionError("the page does not say it shows the ids alone")
    if html.escape(live.ref.message_id, quote=False) not in instance:
        raise AssertionError("the page does not show the id of the message")
    return "the ids alone, and the page says so"


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("the profile written by backfill", profile),
    ("the pages with the token of the service", pages),
    ("a wrong secret", wrong),
    ("without the token of the service", ids_alone),
]


async def run(settings: Settings, env_file: Path) -> int:
    with tempfile.TemporaryDirectory() as folder:
        live = Live(settings, env_file.resolve(), Path(folder))
        failed = await run_checks(live, CHECKS)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The live check of the cockpit.")
    parser.add_argument("--env-file", type=Path, default=ENV)
    args = parser.parse_args()
    found = live_settings(args.env_file, "cockpit")
    sys.exit(asyncio.run(run(found, args.env_file)))
