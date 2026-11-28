"""Live check of PostgreSQL as the storage of the service, against the
test database and the test mail server of our own
(containers/test-database/, containers/test-mail-server/), never against
another server.

    uv run python live/mailbox-service/postgres.py

A service of its own runs as a process, first with SQLite in a temporary
folder, its log in a file there. Two roles with a schema each are made
on the test database and are gone at the end. The two accounts of the
test mail server connect over IMAP with SMTP. Then:

1. on SQLite, the first account sends a mail to the second, and the
   change feed of the second names it,
2. the service stops, ``storage move --to postgres --check`` finds every
   value fitting, and ``storage move --to postgres`` moves the records
   into the schema of the first role,
3. the service starts on PostgreSQL with the same token, a second mail
   arrives, and the change feed goes on from where it was on SQLite,
4. ``backup`` writes format 3, and ``restore`` reads it into the empty
   schema of the second role,
5. the test database is stopped (``docker stop``): ``/health`` answers
   503 with ``service_unavailable``, the service keeps running, and its
   log says once that the database is away,
6. started again, ``/health`` answers 200, the log says once that it is
   back, and a third mail arrives without a restart.

Every mail of this check is deleted for good at the end. The command of
Docker comes from ``LIVE_DOCKER`` in ``live/.env``, else ``docker``.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from common.accounts import read_env
from common.admin import bootstrap
from common.mail import sweep
from common.processes import free_port, new_master_key, program, service_env, started
from common.run import Run, polled
from common.test_database import (
    Administrator,
    administrator,
    docker_command,
    stopped,
)
from service_common.test_database import Role, role, rows_in
from service_common.test_server import (
    HOST,
    IMAP_TLS,
    SMTP_TLS,
    connect,
    feed_names,
    test_server_accounts,
    watching_service,
    worker_ready,
)

from benethos_mailbox_client import SyncMailboxClient

TITLE = "postgres live check"
AWAY = "cannot reach the database"
BACK = "reaches the database again"


def settings(account: dict[str, str]) -> dict[str, Any]:
    return {
        "host": HOST,
        "port": IMAP_TLS,
        "security": "tls",
        "username": account["username"],
        "smtp_host": HOST,
        "smtp_port": SMTP_TLS,
        "smtp_security": "tls",
    }


class Host:
    """The folder, the settings and the process of the service."""

    def __init__(self, folder: Path, env: dict[str, str]) -> None:
        self.folder = folder
        self.env = env
        self.url = f"http://127.0.0.1:{env['MAILBOX_SERVICE_PORT']}"
        self.log = folder / "service.log"
        self.process: subprocess.Popen[bytes] | None = None

    def command(
        self, *args: str, on: Role | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if on is not None:
            env.update(_database(self.folder, on))
        return subprocess.run(
            [program("benethos-mailbox-service"), *args],
            env=env,
            cwd=self.folder,
            capture_output=True,
            text=True,
        )

    def start(self) -> None:
        with self.log.open("ab") as log:
            self.process = subprocess.Popen(
                [program("benethos-mailbox-service"), "serve"],
                env=self.env,
                cwd=self.folder,
                stdout=subprocess.DEVNULL,
                stderr=log,
            )
        started(self.process, f"{self.url}/health", "the service")

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=30)
            self.process = None

    def said(self, text: str) -> int:
        return self.log.read_text(encoding="utf-8", errors="replace").count(text)


def _database(folder: Path, on: Role) -> dict[str, str]:
    password = folder / f"{on.name}.password"
    password.write_text(on.password, encoding="utf-8")
    return {
        "MAILBOX_SERVICE_DATABASE_URL": on.url,
        "MAILBOX_SERVICE_DATABASE_PASSWORD_FILE": str(password),
    }


def main() -> int:
    env = read_env()
    mail_folder, test_accounts = test_server_accounts(env)
    admin = administrator(env)
    run = Run()
    folder = Path(tempfile.mkdtemp(prefix="mailbox-postgres-"))
    host = Host(
        folder,
        {
            **service_env(str(folder), free_port(), new_master_key()),
            **watching_service(mail_folder),
        },
    )
    try:
        with role(admin) as first, role(admin) as second:
            host.env.update(_database(folder, first))
            checks(run, env, host, admin, test_accounts[:2], (first, second))
    finally:
        host.stop()
        shutil.rmtree(folder, ignore_errors=True)
    return run.finish()


def checks(
    run: Run,
    env: dict[str, str],
    host: Host,
    admin: Administrator,
    pair: list[dict[str, str]],
    roles: tuple[Role, Role],
) -> None:
    subprocess.run(
        [program("benethos-mailbox-service"), "keys", "init"],
        env=host.env,
        cwd=host.folder,
        check=True,
        capture_output=True,
    )
    host.start()
    who = bootstrap(host.env, host.url)
    headers = {"Authorization": f"Bearer {who.token}"}
    with httpx.Client(base_url=host.url, headers=headers, timeout=60) as client:
        ids = connect(
            run, client, "imap", "both accounts connect on SQLite", pair, settings
        )
        if ids is None:
            return
        sender, receiver = ids
        mailbox = SyncMailboxClient(host.url, who.token)
        try:
            steps(run, env, host, admin, client, ids, pair[1], roles)
        finally:
            sweep(
                mailbox,
                [(sender, "sent"), (receiver, "all"), (receiver, "trash")],
                TITLE,
            )
            mailbox.close()


def steps(
    run: Run,
    env: dict[str, str],
    host: Host,
    admin: Administrator,
    client: httpx.Client,
    ids: tuple[str, str],
    receiver: dict[str, str],
    roles: tuple[Role, Role],
) -> None:
    second = roles[1]
    base = f"/v1/accounts/{ids[1]}"
    send = _sender(client, ids[0], receiver["email"])
    polled(lambda: worker_ready(client, ids[1]), tries=30, pause=1.0)
    since = client.get(f"{base}/changes").json()["state"]
    send()
    run.check(
        "1. on SQLite the feed names the first mail", _arrived(client, base, since, 1)
    )
    on_sqlite = client.get(f"{base}/changes").json()["state"]
    host.stop()

    checked = host.command("storage", "move", "--to", "postgres", "--check")
    moved = host.command("storage", "move", "--to", "postgres")
    run.check(
        "2. storage move checks, then moves to PostgreSQL",
        checked.returncode == 0 and moved.returncode == 0,
        (checked.stderr + moved.stderr).strip()[-200:],
    )
    host.env["MAILBOX_SERVICE_STORAGE"] = "postgres"
    host.start()
    polled(lambda: worker_ready(client, ids[1]), tries=30, pause=1.0)
    send()
    after = (
        feed_names(client, base, on_sqlite)
        if _arrived(client, base, on_sqlite, 1)
        else []
    )
    run.check(
        "3. on PostgreSQL the same token works and the feed goes on",
        len([k for k, _ in after if k == "message.created"]) == 1,
        str(after),
    )

    backup = host.folder / "postgres.bak"
    written = host.command("backup", str(backup))
    restored = host.command("restore", str(backup), on=second)
    run.check(
        "4. backup in format 3, restored into an empty schema",
        "format 3" in written.stderr
        and restored.returncode == 0
        and rows_in(admin, second.name, "accounts") == 2,
        (written.stderr + restored.stderr).strip()[-200:],
    )
    away(run, env, host, client, base, send)


def away(
    run: Run,
    env: dict[str, str],
    host: Host,
    client: httpx.Client,
    base: str,
    send: Callable[[], str],
) -> None:
    with stopped(docker_command(env)):
        answer = polled(lambda: _health(host, 503), tries=90, pause=1.0)
        polled(lambda: host.said(AWAY) > 0, tries=30, pause=1.0)
        alive = host.process is not None and host.process.poll() is None
        run.check(
            "5. stopped: /health 503, the service runs, the log says it once",
            answer is not None and alive and host.said(AWAY) == 1,
            f"{host.said(AWAY)} line(s)",
        )
    back = polled(lambda: _health(host, 200), tries=120, pause=1.0)
    polled(lambda: host.said(BACK) > 0, tries=30, pause=1.0)
    mark = client.get(f"{base}/changes").json()["state"]
    send()
    run.check(
        "6. started: /health 200, the log says it once, a mail arrives",
        back is not None and host.said(BACK) == 1 and _arrived(client, base, mark, 1),
        f"{host.said(BACK)} line(s)",
    )


def _sender(client: httpx.Client, sender_id: str, to: str) -> Callable[[], str]:
    def send() -> str:
        title = f"{TITLE} {secrets.token_hex(4)}"
        client.post(
            f"/v1/accounts/{sender_id}/send",
            json={
                "to": [{"email": to}],
                "subject": title,
                "text": "Sent by live/mailbox-service/postgres.py.",
            },
        )
        return title

    return send


def _arrived(client: httpx.Client, base: str, since: str, count: int) -> bool:
    def look() -> bool:
        names = feed_names(client, base, since)
        return len([k for k, _ in names if k == "message.created"]) >= count

    return bool(polled(look, tries=60, pause=1.0))


def _health(host: Host, status: int) -> bool:
    try:
        answer = httpx.get(f"{host.url}/health", timeout=30)
    except httpx.TransportError:
        return False
    if answer.status_code != status:
        return False
    return status == 200 or answer.json()["error"]["code"] == "service_unavailable"


if __name__ == "__main__":
    sys.exit(main())
