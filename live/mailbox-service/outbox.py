"""Live check of the outbox against the test mail server of our own
(containers/test-mail-server/, Stalwart), never against another server.

    uv run python live/mailbox-service/outbox.py
    # the first steps between the two bots of live/.env as well
    uv run python live/mailbox-service/outbox.py --bots

A service of its own runs as a process, with SQLite in a temporary folder,
and its outbox runner beside it. The first account of the test server
sends to the second over IMAP and SMTP. Its SMTP goes through a small
TCP relay of this script, which passes the bytes on as they are (TLS
ends at the server) and can turn connections away, as a server that is
away does. No container is stopped. Then:

1. a mail put into the outbox answers `202`, goes out once in the
   background, arrives, has its copy in the sent folder, its draft is
   gone, and the audit of sends holds `queued` and `sent` with its job,
2. a mail with `send_at` two minutes ahead waits, then goes out,
3. a mail for an hour ahead is cancelled: it stays as a draft, which is
   then deleted,
4. a draft queued for a minute ahead and changed in the meantime is not
   sent: the job ends as `cancelled` with `draft_changed`,
5. with the relay turning connections away, a queued mail waits with
   `provider_unavailable`. Once the relay lets them through again, it
   goes out after its next attempt, exactly once.

``--bots`` runs steps 1 to 3 between bot-0001 and bot-0002 as well,
from the real server, sending two mails. Every mail of this check is
deleted for good at the end, found by its subject.
"""

from __future__ import annotations

import argparse
import secrets
import socket
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from common.accounts import accounts, read_env, register
from common.mail import delete_for_good, messages_with_subject, sweep
from common.processes import free_port
from common.run import Run, polled
from common.service import throwaway_service
from service_common.test_server import (
    HOST,
    IMAP_TLS,
    SMTP_TLS,
    connect,
    test_server_accounts,
    watching_service,
)

from benethos_mailbox_client import SyncMailboxClient

TITLE = "outbox live check"
TEXT = "Sent by live/mailbox-service/outbox.py between the test accounts."
# The runner looks every five seconds, a first failed attempt waits a minute.
JOB_TRIES, JOB_PAUSE = 60, 5.0


class Relay:
    """A TCP relay on a free port of this host to ``target``, which can
    turn new connections away for a while."""

    def __init__(self, target: tuple[str, int]) -> None:
        self.port = free_port()
        self._target = target
        self._open = threading.Event()
        self._open.set()
        self._server = socket.create_server((HOST, self.port))
        threading.Thread(target=self._serve, daemon=True).start()

    def away(self) -> None:
        self._open.clear()

    def back(self) -> None:
        self._open.set()

    def close(self) -> None:
        self._server.close()

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            if not self._open.is_set():
                client.close()
                continue
            try:
                server = socket.create_connection(self._target, timeout=10)
            except OSError:
                client.close()
                continue
            for a, b in ((client, server), (server, client)):
                threading.Thread(target=_pipe, args=(a, b), daemon=True).start()


def _pipe(source: socket.socket, sink: socket.socket) -> None:
    """The bytes of ``source`` into ``sink`` until either side ends, then
    both ends shut. A connection the other side dropped ends it too."""
    with suppress(OSError):
        while data := source.recv(65536):
            sink.sendall(data)
    for end in (source, sink):
        with suppress(OSError):
            end.shutdown(socket.SHUT_RDWR)


def job_in(
    client: httpx.Client, account_id: str, job_id: str, states: set[str]
) -> dict[str, Any] | None:
    """The job once it is in one of ``states``, None when it never got there."""

    def look() -> dict[str, Any] | None:
        found = client.get(f"/v1/accounts/{account_id}/outbox/{job_id}").json()
        return found if found.get("state") in states else None

    return polled(look, JOB_TRIES, JOB_PAUSE)


def seen(found: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """The state and the last error of a job, None for both without one."""
    if found is None:
        return None, None
    return found.get("state"), found.get("last_error")


def queue(
    client: httpx.Client, sender_id: str, to: str, title: str, **extra: Any
) -> httpx.Response:
    return client.post(
        f"/v1/accounts/{sender_id}/send",
        json={"to": [{"email": to}], "subject": title, "text": TEXT, **extra},
    )


def drafts_of(client: httpx.Client, account_id: str) -> list[str]:
    page = client.get(f"/v1/accounts/{account_id}/drafts").json()
    return [d["id"] for d in page["items"]]


def in_time(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def basics(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    ids: tuple[str, str],
    receiver: str,
    where: str,
) -> None:
    """Steps 1 to 3: at once, at a time, cancelled."""
    sender_id, receiver_id = ids
    title = f"{TITLE} {secrets.token_hex(4)}"
    queued = queue(client, sender_id, receiver, title, outbox=True)
    job = queued.json()
    run.check(
        f"{where}: a mail put into the outbox answers 202 with its job",
        queued.status_code == 202 and job.get("state") == "queued",
        f"{queued.status_code} {job.get('state')}",
    )
    if queued.status_code != 202:
        return
    done = job_in(client, sender_id, job["id"], {"sent", "failed", "unknown"})
    run.check(
        f"{where}: the runner sends it in the background",
        seen(done)[0] == "sent",
        str(seen(done)),
    )
    arrived = messages_with_subject(mailbox, receiver_id, title)
    run.check(f"{where}: it arrives once", len(arrived) == 1, str(len(arrived)))
    copies = messages_with_subject(mailbox, sender_id, title, folder="sent")
    run.check(f"{where}: its copy is in the sent folder", len(copies) == 1)
    gone = job["draft_id"] not in drafts_of(client, sender_id)
    run.check(f"{where}: its draft is gone", gone)
    audit = client.get(f"/v1/accounts/{sender_id}/sends").json()["items"]
    mine = [r for r in audit if r.get("outbox_job_id") == job["id"]]
    outcomes = sorted(r["outcome"] for r in mine)
    run.check(
        f"{where}: the audit of sends holds queued and sent",
        outcomes == ["queued", "sent"],
        str(outcomes),
    )

    later = f"{title} later"
    timed = queue(client, sender_id, receiver, later, send_at=in_time(120)).json()
    waiting = client.get(f"/v1/accounts/{sender_id}/outbox/{timed['id']}").json()
    run.check(
        f"{where}: a mail for two minutes ahead waits",
        waiting.get("state") == "queued",
        str(waiting.get("state")),
    )
    went = job_in(client, sender_id, timed["id"], {"sent", "failed", "unknown"})
    run.check(
        f"{where}: it goes out at its time",
        seen(went)[0] == "sent",
        str(seen(went)),
    )
    run.check(
        f"{where}: and arrives",
        len(messages_with_subject(mailbox, receiver_id, later)) == 1,
    )

    stopped = queue(
        client, sender_id, receiver, f"{title} cancelled", send_at=in_time(3600)
    ).json()
    cancelled = client.delete(f"/v1/accounts/{sender_id}/outbox/{stopped['id']}")
    run.check(
        f"{where}: a mail for an hour ahead is cancelled, its draft stays",
        cancelled.status_code == 200
        and stopped["draft_id"] in drafts_of(client, sender_id),
        str(cancelled.status_code),
    )
    client.delete(f"/v1/accounts/{sender_id}/drafts/{stopped['draft_id']}")


def changed_draft(
    run: Run, client: httpx.Client, mailbox: SyncMailboxClient, ids: tuple[str, str]
) -> None:
    """Step 4: a draft changed after it was queued is not sent."""
    sender_id, receiver_id = ids
    title = f"{TITLE} changed {secrets.token_hex(4)}"
    receiver = client.get(f"/v1/accounts/{receiver_id}").json()["email"]
    body = {"to": [{"email": receiver}], "subject": title, "text": TEXT}
    draft = client.post(f"/v1/accounts/{sender_id}/drafts", json=body).json()
    base = f"/v1/accounts/{sender_id}/drafts/{draft['id']}"
    job = client.post(f"{base}/send", json={"send_at": in_time(60)}).json()
    replaced = client.put(base, json={**body, "text": "Changed after it was queued."})
    ended = job_in(client, sender_id, job["id"], {"sent", "cancelled", "failed"})
    run.check(
        "a draft changed after it was queued is not sent",
        seen(ended) == ("cancelled", "draft_changed"),
        str(seen(ended)),
    )
    run.check(
        "and nothing arrived",
        not messages_with_subject(mailbox, receiver_id, title, tries=2),
    )
    client.delete(f"/v1/accounts/{sender_id}/drafts/{replaced.json()['id']}")


def outage(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    ids: tuple[str, str],
    relay: Relay,
) -> None:
    """Step 5: the server away, then back."""
    sender_id, receiver_id = ids
    title = f"{TITLE} away {secrets.token_hex(4)}"
    receiver = client.get(f"/v1/accounts/{receiver_id}").json()["email"]
    relay.away()
    try:
        job = queue(client, sender_id, receiver, title, outbox=True).json()

        def waits() -> dict[str, Any] | None:
            found = client.get(f"/v1/accounts/{sender_id}/outbox/{job['id']}").json()
            return found if found.get("attempts", 0) >= 1 else None

        waiting = polled(waits, JOB_TRIES, JOB_PAUSE)
        run.check(
            "with the server away the mail waits for its next attempt",
            seen(waiting) == ("queued", "provider_unavailable"),
            str(seen(waiting)),
        )
    finally:
        relay.back()
    went = job_in(client, sender_id, job["id"], {"sent", "failed", "unknown"})
    run.check(
        "once it is back the mail goes out",
        seen(went)[0] == "sent",
        str(seen(went)),
    )
    arrived = messages_with_subject(mailbox, receiver_id, title)
    run.check("and arrives exactly once", len(arrived) == 1, str(len(arrived)))


def ours(subject: str) -> bool:
    """A mail of this check, of this run or an earlier one."""
    return subject.startswith(TITLE)


def test_server(run: Run) -> None:
    env = read_env()
    folder, test_accounts = test_server_accounts(env)
    sender, receiver = test_accounts[:2]
    relay = Relay((HOST, SMTP_TLS))

    def settings(account: dict[str, str]) -> dict[str, Any]:
        return {
            "host": HOST,
            "port": IMAP_TLS,
            "security": "tls",
            "username": account["username"],
            "smtp_host": HOST,
            "smtp_port": relay.port,
            "smtp_security": "tls",
        }

    try:
        with (
            throwaway_service("mailbox-outbox-", watching_service(folder)) as service,
            service.admin(timeout=120) as client,
            service.mailbox() as mailbox,
        ):
            ids = connect(
                run,
                client,
                "imap",
                "the test accounts connect over IMAP, SMTP through the relay",
                (sender, receiver),
                settings,
            )
            if ids is None:
                return
            places = [(i, f) for i in ids for f in (None, "sent", "drafts")]
            sweep(mailbox, places, TITLE)
            try:
                basics(run, client, mailbox, ids, receiver["email"], "test server")
                changed_draft(run, client, mailbox, ids)
                outage(run, client, mailbox, ids, relay)
            finally:
                delete_for_good(mailbox, places, TITLE, matches=ours)
    finally:
        relay.close()


def bots(run: Run) -> None:
    env = read_env()
    first, second = accounts(env)[:2]
    with (
        throwaway_service("mailbox-outbox-bots-") as service,
        service.admin(timeout=120) as client,
        service.mailbox() as mailbox,
    ):
        made: list[str] = []
        for bot in (first, second):
            bot_id, outcome = register(mailbox, env, bot)
            if not run.check("a bot connects", bot_id is not None, outcome):
                return
            assert bot_id is not None
            made.append(bot_id)
        ids = (made[0], made[1])
        places = [(i, f) for i in ids for f in (None, "sent", "drafts")]
        try:
            basics(run, client, mailbox, ids, second["email"], "bots")
        finally:
            delete_for_good(mailbox, places, TITLE, matches=ours)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bots", action="store_true", help="the bots as well")
    options = parser.parse_args()
    run = Run()
    steps: list[Callable[[Run], None]] = [test_server]
    if options.bots:
        steps.append(bots)
    for step in steps:
        started = time.monotonic()
        step(run)
        print(f"  ({step.__name__}: {time.monotonic() - started:.0f} s)")
    return run.finish()


if __name__ == "__main__":
    raise SystemExit(main())
