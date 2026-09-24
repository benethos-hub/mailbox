"""What the IMAP adapter hands the sync worker: folder states, contents,
Message-ID headers and IDLE."""

from __future__ import annotations

import pytest

from benethos_mailbox_api.data.providers.imap import mappers
from benethos_mailbox_api.data.providers.imap.client import ImapServer, ImapSession
from benethos_mailbox_api.errors import (
    NotSupportedError,
    ProviderAuthError,
    ProviderUnavailableError,
)

from .imap_fake import FakeMailBox, make_message
from .test_imap import provider, server  # noqa: F401 - the fixture

INBOX = mappers.folder_id("INBOX")
SENT = mappers.folder_id("Sent")


async def test_folder_states_change_when_messages_come_and_go(
    server: FakeMailBox,  # noqa: F811
) -> None:
    imap = provider(server)
    before = await imap.folder_states()
    # Archive is \Noselect and holds nothing.
    assert set(before) == {INBOX, SENT, mappers.folder_id("Archive/2026")}
    assert before[INBOX] == "7.10.6"

    server.add("INBOX", 10, make_message("New"))
    after_new = await imap.folder_states()
    assert after_new[INBOX] != before[INBOX]
    assert after_new[SENT] == before[SENT]

    del server.folders["INBOX"].messages[10]
    del server.folders["INBOX"].messages[1]
    assert (await imap.folder_states())[INBOX] != after_new[INBOX]
    # STATUS, never SELECT: a poll does not open the folders.
    assert not any(c[0] == "select" for c in server.calls)


async def test_folder_contents(server: FakeMailBox) -> None:  # noqa: F811
    imap = provider(server)
    ids = await imap.folder_contents(INBOX)
    assert ids == [mappers.message_id("INBOX", 7, uid) for uid in (1, 2, 3, 4, 5, 9)]


@pytest.mark.parametrize("uid_last", [False, True])
async def test_message_headers(server: FakeMailBox, uid_last: bool) -> None:  # noqa: F811
    server.uid_last = uid_last
    server.add(
        "INBOX",
        20,
        make_message("Folded", extra_headers={}).replace(
            b"Message-ID: <", b"Message-ID:\n <", 1
        ),
    )
    server.add(
        "INBOX", 21, make_message("No id").replace(b"Message-ID:", b"X-Old-Id:", 1)
    )
    imap = provider(server)
    wanted = [mappers.message_id("INBOX", 7, uid) for uid in (1, 20, 21, 99)]
    found = await imap.message_headers(wanted)
    assert found[wanted[0]] == f"<{abs(hash('Invoice 1'))}@example.com>"
    assert found[wanted[1]] == f"<{abs(hash('Folded'))}@example.com>"
    assert found[wanted[2]] is None
    assert wanted[3] not in found  # gone
    fetches = [c for c in server.calls if c[0] == "uid"]
    assert all("BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]" in c[3] for c in fetches)


async def test_message_headers_in_batches(server: FakeMailBox) -> None:  # noqa: F811
    for uid in range(100, 550):
        server.add("Sent", uid, make_message(f"Sent {uid}"))
    imap = provider(server)
    wanted = [mappers.message_id("Sent", 1, uid) for uid in range(100, 550)]
    found = await imap.message_headers(wanted)
    assert len(found) == 450
    assert len([c for c in server.calls if c[0] == "uid"]) == 3


async def test_message_headers_after_a_uidvalidity_change(
    server: FakeMailBox,  # noqa: F811
) -> None:
    imap = provider(server)
    assert await imap.message_headers([mappers.message_id("INBOX", 6, 1)]) == {}


# --- IDLE ------------------------------------------------------------------------


def session(box: FakeMailBox) -> ImapSession:
    session = ImapSession(
        ImapServer("imap.example.com", 993, "tls"), mailbox_factory=box
    )
    session.login("me@example.com", "secret")
    return session


def test_idle_reports_a_change() -> None:
    box = FakeMailBox()
    box.idle_script = [[b"* OK Still here"], [b"* 4 EXISTS", b"* 1 RECENT"]]
    assert session(box).idle(60, stopped=lambda: False) is True
    # "Still here" is no change. After the change, IDLE is ended with DONE.
    assert box.idle_script == []
    assert box.calls[-2:] == [("idle", "INBOX"), ("done",)]


@pytest.mark.parametrize(
    "line", [b"* 3 EXPUNGE", b"* 2 FETCH (FLAGS (\\Seen))", b"* VANISHED 5"]
)
def test_idle_changes(line: bytes) -> None:
    box = FakeMailBox()
    box.idle_script = [[line]]
    assert session(box).idle(60, stopped=lambda: False) is True


def test_idle_ends_after_the_timeout() -> None:
    box = FakeMailBox()
    now = [0.0]

    def clock() -> float:
        now[0] += 10
        return now[0]

    assert session(box).idle(25, stopped=lambda: False, clock=clock) is False
    assert ("done",) in box.calls


def test_idle_stops_when_asked() -> None:
    box = FakeMailBox()
    assert session(box).idle(600, stopped=lambda: True) is False
    assert ("done",) in box.calls


def test_idle_bye_is_a_lost_connection() -> None:
    box = FakeMailBox()
    box.idle_script = [[b"* BYE Server shutting down"]]
    with pytest.raises(ProviderUnavailableError):
        session(box).idle(60, stopped=lambda: False)


async def test_wait_for_change_uses_a_connection_of_its_own(
    server: FakeMailBox,  # noqa: F811
) -> None:
    server.idle_script = [[b"* 7 EXISTS"]]
    imap = provider(server)
    await imap.list_folders()
    assert await imap.wait_for_change(60) is True
    assert server.logins == 2
    assert ("idle", "INBOX") in server.calls
    # The IDLE connection only looks: the inbox is opened read-only.
    assert ("select", "INBOX", True) in server.calls


async def test_wait_for_change_without_idle(server: FakeMailBox) -> None:  # noqa: F811
    server.capabilities = ["IMAP4REV1"]
    with pytest.raises(NotSupportedError):
        await provider(server).wait_for_change(60)


async def test_wait_for_change_with_a_rejected_login(
    server: FakeMailBox,  # noqa: F811
) -> None:
    server.password = "changed"
    imap = provider(server)
    with pytest.raises(ProviderAuthError):
        await imap.wait_for_change(60)
    # Like every other operation: no second attempt until verified.
    with pytest.raises(ProviderAuthError, match="before"):
        await imap.list_folders()


async def test_closed_provider_does_not_wait(server: FakeMailBox) -> None:  # noqa: F811
    imap = provider(server)
    await imap.close()
    assert await imap.wait_for_change(60) is False
    assert server.logins == 0
