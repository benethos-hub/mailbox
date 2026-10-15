"""What an IMAP account can do, as its server answers (UNIFORM R4): what
it announces after the login, the special folders it lists, and the flags
the inbox keeps (``PERMANENTFLAGS``)."""

from __future__ import annotations

from ...models import Abilities, Capability, FolderRole
from . import mappers
from .mailbox import Mailbox


def abilities(box: Mailbox, sends: bool) -> Abilities:
    """``sends``: whether the account names an SMTP server."""
    announced = box.session.server_capabilities()
    permanent = box.session.select_writable(
        box.role_folder(FolderRole.INBOX) or "INBOX"
    ).permanent_flags
    found = {
        Capability.READ_STATE,
        Capability.STARS,
        Capability.FOLDERS,
        Capability.SEARCH,
        # The domain threads the messages in its index.
        Capability.THREADS,
    }
    if mappers.keywords_kept(permanent):
        found.add(Capability.KEYWORDS)
    # Without UIDPLUS a plain EXPUNGE would take other deleted messages
    # with it, other clients' too.
    move = "MOVE" in announced or "UIDPLUS" in announced
    if move:
        found.add(Capability.MOVE)
        if box.role_folder(FolderRole.TRASH) is not None:
            found.add(Capability.TRASH)
    if "UIDPLUS" in announced:
        found.add(Capability.PURGE)
    if box.role_folder(FolderRole.DRAFTS) is not None:
        found.add(Capability.DRAFTS)
    if sends:
        found |= {Capability.SEND, Capability.REFUSED}
        if box.role_folder(FolderRole.SENT) is not None:
            found.add(Capability.SENT_COPY)
    if "IDLE" in announced:
        found.add(Capability.PUSH)
    if "CONDSTORE" in announced:
        found.add(Capability.EXTERNAL_CHANGES)
    return Abilities.of(found, written=mappers.marks_kept(permanent))
