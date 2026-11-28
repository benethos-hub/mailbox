"""The live check of the agents on PostgreSQL, against the test database
of our own (containers/test-database/) and the test account of
containers/live/mailbox-agents/. It writes nothing to that account.

    sh containers/test-database/setup.sh                # once
    sh containers/live/mailbox-agents/setup.sh          # once
    uv run python live/mailbox-agents/postgres_state.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

On the test database it makes, with ``storage provision --apply``, the
role and the database of two instances of ``counting``, and a third
database for a mailbox service, opened by its storage, which closes it.
Then:

1. each instance takes up the mail of the account with ``backfill`` and
   writes into its own database alone,
2. the role of an instance reaches neither the database of the other
   nor the one of the service,
3. the cockpit, signed in with its role, finds both instances, and only
   the first once the second no longer names the read role,
4. a filled state file of a third instance moves with ``storage move``
   into a database of its own, every table compared,
5. the test database is stopped (``docker stop``) while a worker of the
   first instance runs: the worker waits and logs the database away, and
   writes its progress again once the database is back.

Every database and role it made is gone at the end, the read roles too
when this run made them. The command of Docker comes from
``LIVE_DOCKER`` in the environment or in ``live/.env``, else ``docker``.
Each check says ok or FAILED, and the exit code is 1 if one failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from agents_common import (  # beside this script
    ENV,
    agents_command,
    clean_environment,
    live_settings,
    run_checks,
)
from agents_common.test_database import (
    Administrator,
    administrator,
    connected,
    dropped,
    stopped,
)
from common.accounts import read_env

from benethos_mailbox_agents.cockpit import sources
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.store import Store
from benethos_mailbox_agents.store.catalogue import LOGIN, READER
from benethos_mailbox_common.storage.server_place import Server
from benethos_mailbox_service.data.storage import open_repositories

DAYS = "30"
# How long the test database stays stopped, and how long the worker may
# take to write its progress once it is back.
AWAY_SECONDS = 15
BACK_SECONDS = 90


@dataclass
class Live:
    settings: Settings
    env_file: Path
    folder: Path
    admin: Administrator
    tag: str = field(default_factory=lambda: secrets.token_hex(3))
    passwords: dict[str, str] = field(default_factory=dict)
    databases: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)

    def instance(self, letter: str) -> str:
        return f"live-{self.tag}-{letter}"

    def name(self, letter: str) -> str:
        """The role and the database of instance ``letter``, as
        storage provision names them where the settings name none."""
        return f"agent_counting_live_{self.tag}_{letter}"

    def server(self, letter: str) -> Server:
        name = self.name(letter)
        return Server(
            host=self.admin.host,
            port=self.admin.port,
            database=name,
            role=name,
            password=self.passwords[letter],
        )


def _environment(live: Live, letter: str, **values: str) -> dict[str, str]:
    """The environment of a process of instance ``letter``: no setting of
    this shell, its state on the test database, and ``values``."""
    name = live.name(letter)
    password = live.folder / f"password-{letter}"
    password.write_text(live.passwords[letter], encoding="utf-8")
    settings = {
        "data_dir": str(live.folder / f"data-{letter}"),
        "instance": live.instance(letter),
        "storage": "postgres",
        "database_url": (
            f"postgresql://{name}@{live.admin.host}:{live.admin.port}/{name}"
        ),
        "database_password_file": str(password),
        "database_readers": READER,
        **values,
    }
    return clean_environment(**settings)


def _agents(live: Live, letter: str, *args: str, **values: str) -> str:
    """A command of the agents for instance ``letter``. Answers what it
    printed, and fails with what it said on an exit code other than 0."""
    done = subprocess.run(
        agents_command(live.env_file, *args),
        env=_environment(live, letter, **values),
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise AssertionError(f"{args[0]} ended with {done.returncode}: {done.stderr}")
    return done.stdout


def _provisioned(live: Live, letter: str) -> str:
    live.passwords[letter] = secrets.token_hex(16)
    admin_file = live.folder / "admin_password"
    admin_file.write_text(live.admin.password, encoding="utf-8")
    said = _agents(
        live,
        letter,
        *("storage", "provision", "--agent", "counting", "--apply"),
        *("--admin-url", live.admin.url, "--admin-password-file", str(admin_file)),
    )
    live.databases.append(live.name(letter))
    live.roles.append(live.name(letter))
    for role in (READER, LOGIN):
        if f"role {role}" in said:
            live.roles.append(role)
    return said


def _state(live: Live, letter: str) -> Store:
    found = Store.read_server(live.server(letter))
    if found is None:
        raise AssertionError(f"instance {letter} holds no state yet")
    return found


def _rows(live: Live, letter: str) -> int:
    with _state(live, letter) as store:
        return sum(store.counts().values())


async def instances(live: Live) -> str:
    for letter in "ab":
        _provisioned(live, letter)
        _agents(live, letter, "backfill", "--agent", "counting", "--days", DAYS)
    counts = [_rows(live, letter) for letter in "ab"]
    if not all(counts):
        raise AssertionError(f"an instance holds no message: {counts}")
    return f"two databases, {counts[0]} and {counts[1]} messages"


async def service(live: Live) -> str:
    name = f"live_service_{live.tag}"
    password = secrets.token_hex(16)
    with connected(live.admin) as conn:
        conn.execute(f"CREATE ROLE {name} LOGIN PASSWORD '{password}'")
        conn.execute(f"CREATE DATABASE {name} OWNER {name}")
    live.databases.append(name)
    live.roles.append(name)
    with psycopg.connect(
        host=live.admin.host,
        port=live.admin.port,
        user=name,
        password=password,
        dbname=name,
        autocommit=True,
    ) as own:
        own.execute(f"CREATE SCHEMA {name}")
    server = Server(
        host=live.admin.host,
        port=live.admin.port,
        database=name,
        role=name,
        password=password,
    )
    found = open_repositories("postgres", live.folder / "unused.db", server)
    try:
        if found.database_closed is not True:
            raise AssertionError("the service did not close its database")
    finally:
        found.close()
    return f"the database {name}, closed by the service"


def _reaches(live: Live, letter: str, database: str) -> bool:
    try:
        with psycopg.connect(
            host=live.admin.host,
            port=live.admin.port,
            user=live.name(letter),
            password=live.passwords[letter],
            dbname=database,
        ):
            return True
    except psycopg.OperationalError:
        return False


async def apart(live: Live) -> str:
    others = [live.name("b"), f"live_service_{live.tag}"]
    if not _reaches(live, "a", live.name("a")):
        raise AssertionError("the role of the first instance misses its database")
    reached = [name for name in others if _reaches(live, "a", name)]
    if reached:
        raise AssertionError(f"the role of the first instance reaches {reached}")
    return "the first role reaches its database alone"


def _cockpit_names(live: Live, password: str) -> set[str]:
    server = Server(
        host=live.admin.host,
        port=live.admin.port,
        database=live.admin.database,
        role=LOGIN,
        password=password,
    )
    return {item.name for item in sources.Servers((server,)).found()}


async def cockpit(live: Live) -> str:
    password = secrets.token_hex(16)
    with connected(live.admin) as conn:
        conn.execute(f"ALTER ROLE {LOGIN} PASSWORD '{password}'")
    first, second = live.name("a"), live.name("b")
    if not {first, second} <= _cockpit_names(live, password):
        raise AssertionError("the cockpit does not find both instances")
    _agents(live, "b", "run", "--agent", "counting", database_readers="")
    found = _cockpit_names(live, password)
    if first not in found or second in found:
        raise AssertionError("the cockpit still finds the instance taken back")
    return "both found, then only the first once the second took the read back"


async def move(live: Live) -> str:
    folder = live.folder / "data-c"
    live.passwords["c"] = secrets.token_hex(16)
    _agents(
        live,
        "c",
        "backfill",
        "--agent",
        "counting",
        "--days",
        DAYS,
        storage="sqlite",
    )
    path = next(folder.glob("*.db"))
    with Store.open(path, read_only=True) as store:
        before = store.counts()
    _provisioned(live, "c")
    said = _agents(live, "c", "storage", "move", "--agent", "counting")
    with _state(live, "c") as moved:
        after = moved.counts()
    if before != after or "compared table by table" not in said:
        raise AssertionError(f"the move does not hold: {before} != {after}")
    return f"{sum(after.values())} messages moved and compared"


def _progress(live: Live) -> datetime | None:
    with _state(live, "a") as store:
        return store.progress()


async def away(live: Live) -> str:
    docker = os.environ.get("LIVE_DOCKER") or read_env().get("LIVE_DOCKER") or "docker"
    log = live.folder / "worker.log"
    with log.open("w", encoding="utf-8") as sink:
        worker = subprocess.Popen(
            agents_command(live.env_file, "worker", "--agent", "counting"),
            env=_environment(live, "a", poll_seconds="2", backoff_ceiling_seconds="4"),
            stdout=sink,
            stderr=sink,
        )
    try:
        time.sleep(6)
        with stopped(docker):
            time.sleep(AWAY_SECONDS)
            if worker.poll() is not None:
                raise AssertionError("the worker ended while the database was away")
        back = datetime.now(UTC)
        for _ in range(BACK_SECONDS):
            time.sleep(1)
            try:
                last = _progress(live)
            except Exception:  # the server still starting
                continue
            if last is not None and last > back:
                break
        else:
            raise AssertionError("the worker wrote no progress after the database")
    finally:
        worker.terminate()
        worker.wait(timeout=30)
    said = log.read_text(encoding="utf-8")
    if "StateUnavailableError" not in said:
        raise AssertionError("the log does not say the database was away")
    return f"waited {AWAY_SECONDS} s, logged it, and went on after"


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("two instances in two databases", instances),
    ("the database of a service", service),
    ("each role in its own database", apart),
    ("the cockpit and the read role", cockpit),
    ("a state file moved", move),
    ("the database stopped and back", away),
]


async def run(settings: Settings, env_file: Path) -> int:
    admin = administrator()
    print(f"live: test database {admin.host}:{admin.port}")
    with tempfile.TemporaryDirectory() as folder:
        live = Live(settings, env_file.resolve(), Path(folder), admin)
        try:
            failed = await run_checks(live, CHECKS)
        finally:
            dropped(admin, live.databases, live.roles)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The agents on PostgreSQL, live.")
    parser.add_argument("--env-file", type=Path, default=ENV)
    args = parser.parse_args()
    found = live_settings(args.env_file, "postgres_state")
    sys.exit(asyncio.run(run(found, args.env_file)))
