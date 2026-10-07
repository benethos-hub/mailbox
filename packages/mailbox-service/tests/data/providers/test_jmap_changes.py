"""The ``jmap`` adapter against a JMAP server in memory: sending, drafts,
changing messages, what the sync reads and push."""

from __future__ import annotations

import json

import pytest

from benethos_mailbox_service.data.models import MessageUpdate
from benethos_mailbox_service.data.providers.jmap import JmapProvider
from benethos_mailbox_service.errors import (
    BadRequestError,
    ChangesExpiredError,
    ConflictError,
    NotFoundError,
    NotSupportedError,
    ProviderUnavailableError,
)

from ...imap_fake import make_message
from ...jmap_fake import USER, FakeJmap
from ...provider_ops import delete, update
from .test_jmap import NOW, adapter


@pytest.fixture
def server() -> FakeJmap:
    return FakeJmap()


@pytest.fixture
def jmap(server: FakeJmap) -> JmapProvider:
    return adapter(server)


# --- sending --------------------------------------------------------------------------


async def test_send_moves_the_copy_to_sent(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    raw = make_message("Out", sender=USER, to="you@example.org")
    sent = await jmap.send(raw, USER, ["you@example.org", "hidden@example.org"])
    [submission] = server.submissions
    assert submission["identityId"] == "i1"
    assert submission["envelope"] == {
        "mailFrom": {"email": USER},
        "rcptTo": [{"email": "you@example.org"}, {"email": "hidden@example.org"}],
    }
    copy = server.emails[submission["emailId"]]
    assert copy["mailboxIds"] == {"sent": True}
    assert copy["keywords"] == {"$seen": True}
    assert sent.sent_copy is not None and sent.sent_copy.folder_ids == ["sent"]
    assert sent.refused == [] and sent.copy_error is None


async def test_send_picks_the_identity(jmap: JmapProvider, server: FakeJmap) -> None:
    server.identities = [
        {"id": "i1", "email": "other@example.com"},
        {"id": "i2", "email": "*@example.org"},
        {"id": "i3", "email": "boss@example.org"},
    ]
    await jmap.send(make_message("A"), "BOSS@example.org", ["x@example.net"])
    await jmap.send(make_message("B"), "me@example.org", ["x@example.net"])
    await jmap.send(make_message("C"), "me@elsewhere.net", ["x@example.net"])
    assert [s["identityId"] for s in server.submissions] == ["i3", "i2", "i1"]
    server.identities = []
    with pytest.raises(ConflictError, match="no identity"):
        await jmap.send(make_message("D"), USER, ["x@example.net"])


async def test_send_without_a_sent_folder_keeps_no_copy(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    del server.mailboxes["sent"]
    sent = await jmap.send(make_message("Out"), USER, ["you@example.org"])
    assert sent.sent_copy is None and server.emails == {}
    del server.mailboxes["drafts"]
    with pytest.raises(ConflictError, match="no drafts or sent folder"):
        await jmap.send(make_message("Out"), USER, ["you@example.org"])


async def test_send_without_drafts_goes_through_sent(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    del server.mailboxes["drafts"]
    sent = await jmap.send(make_message("Out"), USER, ["you@example.org"])
    assert sent.sent_copy is not None and sent.sent_copy.folder_ids == ["sent"]


async def test_a_refused_submission_leaves_nothing(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.refuse_submission = {"type": "forbiddenToSend", "description": "quota"}
    with pytest.raises(ConflictError, match="quota"):
        await jmap.send(make_message("Out"), USER, ["you@example.org"])
    assert server.emails == {}
    server.refuse_submission = None
    server.refuse_import = {"type": "tooLarge"}
    with pytest.raises(BadRequestError, match="tooLarge"):
        await jmap.send(make_message("Out"), USER, ["you@example.org"])
    assert server.submissions == []


async def test_a_submission_error_of_the_method(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.method_errors["EmailSubmission/set"] = "serverUnavailable"
    with pytest.raises(ProviderUnavailableError):
        await jmap.send(make_message("Out"), USER, ["you@example.org"])
    assert server.emails == {}


async def test_sent_but_the_copy_is_not_found(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.method_errors["Email/get"] = "serverFail"
    sent = await jmap.send(make_message("Out"), USER, ["you@example.org"])
    assert (
        sent.sent_copy is None and sent.copy_error and "serverFail" in sent.copy_error
    )


async def test_sending_needs_submission(jmap: JmapProvider, server: FakeJmap) -> None:
    del server.capabilities["urn:ietf:params:jmap:submission"]
    with pytest.raises(NotSupportedError, match="no sending"):
        await jmap.send(make_message("Out"), USER, ["you@example.org"])


# --- drafts ---------------------------------------------------------------------------


async def test_drafts(jmap: JmapProvider, server: FakeJmap) -> None:
    first = await jmap.save_draft(make_message("Draft 1"), None)
    assert first.folder_ids == ["drafts"] and "$draft" in first.keywords
    second = await jmap.save_draft(make_message("Draft 2"), first.id)
    assert first.id not in server.emails
    listed = await jmap.list_drafts(limit=5, cursor=None)
    assert [d.id for d in listed.items] == [second.id]
    assert b"Draft 2" in await jmap.get_draft(second.id)
    inbox = server.add_email(make_message("Not a draft"))
    for operation in (
        jmap.get_draft(inbox),
        jmap.delete_draft(inbox),
        jmap.save_draft(make_message("X"), inbox),
    ):
        with pytest.raises(NotFoundError, match="draft"):
            await operation
    await jmap.delete_draft(second.id)
    assert second.id not in server.emails


async def test_a_draft_the_server_refuses(jmap: JmapProvider, server: FakeJmap) -> None:
    server.refuse_import = {"type": "overQuota"}
    with pytest.raises(ConflictError, match="overQuota"):
        await jmap.save_draft(make_message("Draft"), None)
    del server.mailboxes["drafts"]
    with pytest.raises(ConflictError, match="drafts"):
        await jmap.list_drafts(limit=5, cursor=None)


# --- changing -------------------------------------------------------------------------


async def test_flags_and_keywords(jmap: JmapProvider, server: FakeJmap) -> None:
    email_id = server.add_email(make_message("One"), keywords={"$answered": True})
    changed = await update(
        jmap,
        email_id,
        MessageUpdate(unread=False, starred=True, keywords=["Work", "$forwarded"]),
    )
    assert changed.unread is False and changed.starred
    assert changed.keywords == ["$forwarded", "work"]
    assert server.emails[email_id]["keywords"] == {
        "$seen": True,
        "$flagged": True,
        "work": True,
        "$forwarded": True,
    }
    again = await update(jmap, email_id, MessageUpdate(unread=True, starred=False))
    assert again.unread and not again.starred


async def test_move_and_labels(jmap: JmapProvider, server: FakeJmap) -> None:
    folder = server.add_mailbox("Archive", role="archive")
    email_id = server.add_email(make_message("One"))
    moved = await update(jmap, email_id, MessageUpdate(folder_ids=[folder]))
    assert moved.id == email_id and moved.folder_ids == [folder]
    both = await update(jmap, email_id, MessageUpdate(folder_ids=["inbox", folder]))
    assert both.folder_ids == sorted(["inbox", folder])
    with pytest.raises(NotFoundError, match="folder"):
        await update(jmap, email_id, MessageUpdate(folder_ids=["nowhere"]))
    # Already there: nothing to change.
    calls = len(server.calls)
    await update(jmap, email_id, MessageUpdate(folder_ids=[folder, "inbox"]))
    assert "Email/set" not in server.calls[calls:]


async def test_update_answers_per_message(jmap: JmapProvider, server: FakeJmap) -> None:
    one = server.add_email(make_message("One"))
    refused = server.add_email(make_message("Two"))
    server.refuse_set[refused] = {"type": "forbidden"}
    results = await jmap.update_messages(
        [one, "m999", refused, "bad id"], MessageUpdate(starred=True)
    )
    assert results[one].starred  # type: ignore[union-attr]
    assert isinstance(results["m999"], NotFoundError)
    assert isinstance(results["bad id"], NotFoundError)
    assert isinstance(results[refused], ConflictError)
    server.refuse_set[refused] = {"type": "notFound"}
    gone = await jmap.update_messages([refused], MessageUpdate(starred=True))
    assert isinstance(gone[refused], NotFoundError)


async def test_delete_to_the_trash_and_for_good(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    email_id = server.add_email(make_message("One"))
    in_trash = await delete(jmap, email_id, permanent=False)
    assert in_trash is not None and in_trash.folder_ids == ["trash"]
    with pytest.raises(ConflictError, match="trash already"):
        await delete(jmap, email_id, permanent=False)
    assert await delete(jmap, email_id, permanent=True) is None
    assert email_id not in server.emails
    with pytest.raises(NotFoundError):
        await delete(jmap, email_id, permanent=True)
    results = await jmap.delete_messages(["bad id", "m999"], permanent=False)
    assert all(isinstance(r, NotFoundError) for r in results.values())
    assert isinstance(
        (await jmap.delete_messages(["bad id"], permanent=True))["bad id"],
        NotFoundError,
    )
    refused = server.add_email(make_message("Two"))
    server.refuse_set[refused] = {"type": "forbidden"}
    server.emails[refused]["keywords"] = {}
    outcome = await jmap.delete_messages([refused], permanent=False)
    assert isinstance(outcome[refused], ConflictError)


async def test_destroy_refused(jmap: JmapProvider, server: FakeJmap) -> None:
    email_id = server.add_email(make_message("One"))
    draft_id = server.add_email(make_message("Draft"), mailbox="drafts")
    server.email_set = lambda args, using: [  # type: ignore[method-assign]
        (
            "Email/set",
            {"notDestroyed": {i: {"type": "forbidden"} for i in args["destroy"]}},
        )
    ]
    outcome = await jmap.delete_messages([email_id], permanent=True)
    assert isinstance(outcome[email_id], ConflictError)
    with pytest.raises(ConflictError):
        await jmap.delete_draft(draft_id)


async def test_without_a_trash(jmap: JmapProvider, server: FakeJmap) -> None:
    del server.mailboxes["trash"]
    email_id = server.add_email(make_message("One"))
    outcome = await jmap.delete_messages([email_id], permanent=False)
    assert isinstance(outcome[email_id], ConflictError)


# --- for the sync ---------------------------------------------------------------------


async def test_folder_states_and_contents(jmap: JmapProvider, server: FakeJmap) -> None:
    one = server.add_email(make_message("One"))
    assert (await jmap.folder_states())["inbox"] == "1.1"
    assert await jmap.folder_contents("inbox") == [one]
    with pytest.raises(NotFoundError):
        await jmap.folder_contents("bad id")
    assert await jmap.flag_changes("inbox", "x", [one]) == []
    assert await jmap.message_headers([one, "m999"]) == {
        one: "<" + str(abs(hash("One"))) + "@example.com>"
    }


async def test_contents_in_pages(
    jmap: JmapProvider, server: FakeJmap, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benethos_mailbox_service.data.providers.jmap import changes

    monkeypatch.setattr(changes, "QUERY_PAGE", 2)
    ids = [server.add_email(make_message(f"M{n}")) for n in range(5)]
    assert sorted(await jmap.folder_contents("inbox")) == sorted(ids)
    server.query_cap = 1
    assert sorted(await jmap.folder_contents("inbox")) == sorted(ids)


async def test_changes_since_a_state(jmap: JmapProvider, server: FakeJmap) -> None:
    kept = server.add_email(make_message("Kept"))
    moved = server.add_email(make_message("Moved"))
    gone = server.add_email(make_message("Gone"))
    first = await jmap.folder_changes("inbox", None)
    assert {c.id for c in first.changed} == {kept, moved, gone}
    assert first.token == server.state
    new = server.add_email(make_message("New"))
    server.other_client_changes(moved, mailboxIds={"trash": True})
    server.other_client_changes(kept, keywords={"$seen": True})
    server.other_client_deletes(gone)
    fleeting = server.add_email(make_message("Fleeting"))
    server.other_client_deletes(fleeting)
    inbox = await jmap.folder_changes("inbox", first.token)
    trash = await jmap.folder_changes("trash", first.token)
    assert {(c.id, c.created) for c in inbox.changed} == {(new, NOW), (kept, None)}
    assert sorted(inbox.removed) == sorted([moved, gone])
    assert [(c.id, c.created) for c in trash.changed] == [(moved, None)]
    assert sorted(trash.removed) == sorted([kept, gone])
    assert inbox.token == trash.token == server.state
    # Asked once for both folders.
    assert server.calls.count("Email/changes") == 1


async def test_changes_in_several_answers(
    jmap: JmapProvider, server: FakeJmap, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benethos_mailbox_service.data.providers.jmap import changes

    monkeypatch.setattr(changes, "MAX_CHANGES", 1)
    start = (await jmap.folder_changes("inbox", None)).token
    one = server.add_email(make_message("One"))
    two = server.add_email(make_message("Two"))
    found = await jmap.folder_changes("inbox", start)
    assert {c.id for c in found.changed} == {one, two}
    assert server.calls.count("Email/changes") == 2


async def test_a_message_gone_before_it_is_read(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    start = (await jmap.folder_changes("inbox", None)).token
    email_id = server.add_email(make_message("One"))
    server.other_client_changes(email_id, keywords={"$seen": True})
    start2 = server.state
    server.other_client_changes(email_id, keywords={})
    del server.emails[email_id]  # gone without a record yet
    found = await jmap.folder_changes("inbox", start2)
    assert found.removed == [email_id] and found.changed == []
    assert start


async def test_an_expired_state(jmap: JmapProvider, server: FakeJmap) -> None:
    server.oldest = 5
    with pytest.raises(ChangesExpiredError):
        await jmap.folder_changes("inbox", "s1")
    with pytest.raises(NotFoundError):
        await jmap.folder_changes("bad id", "s1")


# --- push -----------------------------------------------------------------------------


def state_event(state: str) -> list[str]:
    data = {"@type": "StateChange", "changed": {"acc1": {"Email": state}}}
    return ["event: state", f"data: {json.dumps(data)}", ""]


async def test_push_reports_a_change(jmap: JmapProvider, server: FakeJmap) -> None:
    server.events = [
        "event: ping",
        'data: {"interval": 60}',
        "",
        *state_event(server.state),
        *state_event("s99"),
    ]
    assert await jmap.wait_for_change(5) is True
    stream = server.requests[-1]
    assert stream.url.path == "/jmap/eventsource/"
    assert stream.headers["accept"] == "text/event-stream"


async def test_push_catches_a_change_between_waits(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.hold = True
    assert await jmap.wait_for_change(0.2) is False
    server.add_email(make_message("Meanwhile"))
    assert await jmap.wait_for_change(0.2) is True


async def test_push_that_ends(jmap: JmapProvider, server: FakeJmap) -> None:
    with pytest.raises(ProviderUnavailableError, match="closed its event stream"):
        await jmap.wait_for_change(5)


async def test_push_without_an_event_source(
    jmap: JmapProvider, server: FakeJmap
) -> None:
    server.event_source = False
    with pytest.raises(NotSupportedError):
        await jmap.wait_for_change(1)


async def test_close(jmap: JmapProvider) -> None:
    await jmap.close()
