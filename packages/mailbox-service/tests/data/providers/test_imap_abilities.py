"""What an IMAP account can do follows from what its server answers
(docs/UNIFORM.md, rule R4): the capabilities it announces, the special
folders it lists and the flags its inbox keeps."""

from __future__ import annotations

from benethos_mailbox_service.data.models import Capability, Mark

from ...imap_adapter import provider, sending
from ...imap_fake import FakeFolder, FakeMailBox
from ...smtp_fake import FakeSmtpServer

EVERY_SERVER = {
    Capability.READ_STATE,
    Capability.STARS,
    Capability.FOLDERS,
    Capability.SEARCH,
    Capability.THREADS,
}


async def test_a_full_server(server: FakeMailBox) -> None:
    server.announced += ["CONDSTORE"]
    server.folders["Trash"] = FakeFolder(flags=("\\Trash",))
    server.folders["Drafts"] = FakeFolder(flags=("\\Drafts",))
    server.folders["Sent"] = FakeFolder(flags=("\\Sent",))
    found = await sending(server, FakeSmtpServer()).abilities()
    assert set(found.capabilities) == EVERY_SERVER | {
        Capability.KEYWORDS,
        Capability.MOVE,
        Capability.TRASH,
        Capability.PURGE,
        Capability.DRAFTS,
        Capability.SEND,
        Capability.SENT_COPY,
        Capability.REFUSED,
        Capability.PUSH,
        Capability.EXTERNAL_CHANGES,
    }
    assert found.marks.written == sorted(Mark)


async def test_a_plain_server(server: FakeMailBox) -> None:
    """No MOVE, UIDPLUS, IDLE or CONDSTORE, no special folders, no SMTP,
    and only the system flags kept."""
    server.announced = ["IMAP4REV1"]
    server.permanent_flags = ["\\Answered", "\\Flagged", "\\Deleted", "\\Seen"]
    server.folders["Trash"] = FakeFolder(flags=("\\Trash",))
    found = await provider(server).abilities()
    # A trash without a way to move into it is no trash.
    assert set(found.capabilities) == EVERY_SERVER
    assert found.marks.written == [Mark.ANSWERED, Mark.DRAFT]


async def test_some_marks_without_own_keywords(server: FakeMailBox) -> None:
    server.permanent_flags = ["\\Answered", "\\Seen", "$Forwarded", "$Junk"]
    found = await provider(server).abilities()
    assert Capability.KEYWORDS not in found.capabilities
    assert found.marks.written == [
        Mark.ANSWERED,
        Mark.DRAFT,
        Mark.FORWARDED,
        Mark.JUNK,
    ]


async def test_uidplus_alone_moves_and_purges(server: FakeMailBox) -> None:
    server.announced = ["IMAP4REV1", "UIDPLUS"]
    found = await provider(server).abilities()
    assert {Capability.MOVE, Capability.PURGE} <= set(found.capabilities)
    assert Capability.PUSH not in found.capabilities


async def test_move_alone_cannot_purge(server: FakeMailBox) -> None:
    server.announced = ["IMAP4REV1", "MOVE"]
    found = await provider(server).abilities()
    assert Capability.MOVE in found.capabilities
    assert Capability.PURGE not in found.capabilities
