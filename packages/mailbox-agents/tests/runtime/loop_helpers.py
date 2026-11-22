"""What the tests of the worker loop share: a reference by id, the state
of a message, and the answer that matches."""

from __future__ import annotations

from benethos_mailbox_agents.records import MessageRef

from ..agents_fake import ACCOUNT
from ..agents_helpers import Wired

MATCH = {"label": "match", "quote": "Your invoice"}


def ref(message_id: str) -> MessageRef:
    return MessageRef(account_id=ACCOUNT, message_id=message_id)


def state_of(world: Wired, message_id: str) -> str:
    row = world.store.message(ref(message_id))
    assert row is not None
    return row.state
