"""invoices: an invoice marked in the inbox and moved later, the backfill
of the folders it looks in, and marked mail the state file does not
know."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_agents.agents.invoices.schema import (
    MAX_ADDRESS,
    MAX_FILES,
    MAX_FILES_TEXT,
    MAX_NAME,
    MAX_SUBJECT,
    MAX_TEXT,
    parts,
    render,
)
from benethos_mailbox_agents.records import (
    Address,
    Attachment,
    MailMessage,
    MessageRef,
)

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import (
    Wired,
    actions,
    item,
    mail,
    run,
    wired,
    worker,
)
from .invoices_helpers import agent, answer

# -- the open item: an invoice marked in the inbox, moved later ----------------------


async def test_an_invoice_in_the_inbox_gets_an_open_item(invoices_world: Wired) -> None:
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77")
    )

    await run(invoices_world, "inv-unlisted", agent())

    found = item(invoices_world, "inv-unlisted")
    assert found is not None and found.is_open
    assert found.due.year == 9999


async def test_the_item_closes_as_filed_in_the_end_station(
    invoices_world: Wired,
) -> None:
    """``Invoices/*`` takes in the inbox folder ``Invoices/mo``: the invoice
    moved there from the inbox closes its item as filed, and nothing more
    is asked for."""
    into_o2 = agent(invoices_inbox_folder="Invoices/mo")
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77"),
        answer("invoice", "Ihre Rechnung R-77"),
    )
    marking = worker(invoices_world, into_o2)
    await marking.run_pass()

    await run(invoices_world, "inv-unlisted", into_o2)
    await run(invoices_world, "filed", agent())
    invoices_world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    assert mail(invoices_world, "inv-unlisted")["folder_ids"] == ["inv-mo"]
    found = item(invoices_world, "inv-unlisted")
    assert found is not None and (found.is_open, found.reason) == (False, "filed")
    assert item(invoices_world, "filed") is None
    assert invoices_world.service.made() == [
        {"name": "Rechnungen", "parent_id": "inv-hosting"}
    ]
    assert len(invoices_world.fake_gateway.requests) == 2


async def test_the_item_closes_in_an_inbox_folder_not_looked_in(
    invoices_world: Wired,
) -> None:
    into_o2 = agent(
        invoices_folders=["Invoices/Hosting"], invoices_inbox_folder="Invoices/mo"
    )
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77")
    )
    marking = worker(invoices_world, into_o2)
    await marking.run_pass()

    await run(invoices_world, "inv-unlisted", into_o2)
    invoices_world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    assert mail(invoices_world, "inv-unlisted")["folder_ids"] == ["inv-mo"]
    found = item(invoices_world, "inv-unlisted")
    assert found is not None and found.reason == "moved_elsewhere"
    assert invoices_world.service.made() == []


async def test_an_invoice_moved_elsewhere_closes_its_item_and_stays(
    invoices_world: Wired,
) -> None:
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77")
    )
    marking = worker(invoices_world, agent())
    await marking.run_pass()
    await run(invoices_world, "inv-unlisted", agent())

    mail(invoices_world, "inv-unlisted")["folder_ids"] = ["inv"]
    invoices_world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    assert mail(invoices_world, "inv-unlisted")["folder_ids"] == ["inv"]
    found = item(invoices_world, "inv-unlisted")
    assert found is not None and found.reason == "moved_elsewhere"


async def test_an_update_in_the_inbox_leaves_the_item_open(
    invoices_world: Wired,
) -> None:
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77")
    )
    marking = worker(invoices_world, agent())
    await marking.run_pass()
    await run(invoices_world, "inv-unlisted", agent())

    invoices_world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    found = item(invoices_world, "inv-unlisted")
    assert found is not None and found.is_open
    assert invoices_world.service.made() == []


async def test_an_update_of_an_invoice_deleted_since_closes_its_item(
    invoices_world: Wired,
) -> None:
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77")
    )
    marking = worker(invoices_world, agent())
    await marking.run_pass()
    await run(invoices_world, "inv-unlisted", agent())

    del invoices_world.service.messages[(ACCOUNT, "inv-unlisted")]
    invoices_world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    found = item(invoices_world, "inv-unlisted")
    assert found is not None and (found.is_open, found.reason) == (
        False,
        "message_gone",
    )


async def test_an_update_of_a_message_without_an_item_does_nothing(
    invoices_world: Wired,
) -> None:
    marking = worker(invoices_world, agent())
    await marking.run_pass()
    mail(invoices_world, "plain")["folder_ids"] = ["inv-hosting"]
    invoices_world.service.change("message.updated", "plain")

    await marking.run_pass()

    assert mail(invoices_world, "plain")["folder_ids"] == ["inv-hosting"]
    assert invoices_world.fake_gateway.requests == []


# -- backfill takes in the folders it looks in ---------------------------------------


async def test_backfill_takes_up_the_folders_it_looks_in(invoices_world: Wired) -> None:
    taken = await worker(invoices_world, agent()).backfill(30)

    pending = {
        row.ref.message_id for row in invoices_world.store.messages("pending", 100)
    }
    assert "filed" in pending
    assert "at-top" not in pending
    assert taken == len(pending)


async def test_backfill_reads_the_inbox_once(invoices_world: Wired) -> None:
    """The inbox, which invoices always looks in, is read with sent mail by
    its role, and not once more as a folder it looks in."""
    taken = await worker(invoices_world, agent()).backfill(30)

    pending = [row.ref for row in invoices_world.store.messages("pending", 100)]
    assert taken == len(pending) == len(set(pending))
    listed = [
        (r.url.path, r.url.params.get("folder"))
        for r in invoices_world.service.requests
        if r.url.path.endswith("/messages")
    ]
    assert listed.count(("/v1/messages", "inbox")) == 1
    assert ("/v1/accounts/acc1/messages", "inbox") not in listed


async def test_backfill_without_accounts_asks_every_account_for_its_folders(
    tmp_path: Path,
) -> None:
    """An account whose inbox and sent mail are empty, as sorting leaves
    one, still has its folders looked in when no account is named."""
    async with wired(tmp_path) as found:
        found.service.add(
            wire_message(
                "filed",
                folder_ids=["inv-hosting"],
                subject="Ihre Rechnung R-77",
                text="Ihre Rechnung R-77 liegt bei.",
            ),
            change=None,
        )

        taken = await worker(found, agent()).backfill(30)

    assert taken == 1


# -- marked mail the state file does not know -----------------------------------------


@pytest.mark.parametrize("message_id", ["filed", "inv-unlisted"])
async def test_a_marked_invoice_the_state_file_does_not_know_is_skipped(
    invoices_world: Wired, message_id: str
) -> None:
    """In a folder it looks in and in the inbox: no baseline, no model call,
    no action, and it stays where it lies."""
    mail(invoices_world, message_id)["keywords"] = ["agent-invoice"]
    before = list(mail(invoices_world, message_id)["folder_ids"])

    assert await run(invoices_world, message_id, agent()) == "skipped"

    ref = MessageRef(account_id=ACCOUNT, message_id=message_id)
    assert invoices_world.store.steps(ref) == []
    assert invoices_world.fake_gateway.requests == []
    assert actions(invoices_world, message_id) == []
    assert mail(invoices_world, message_id)["folder_ids"] == before
    assert invoices_world.service.made() == []


async def test_a_marked_invoice_the_state_file_knows_goes_on(
    invoices_world: Wired,
) -> None:
    """Marked in stage keyword, taken up again after a change of stage:
    the stored decision is used and it moves."""
    invoices_world.fake_gateway.answer(answer("invoice", "Ihre Rechnung R-77"))
    await run(invoices_world, "filed", agent("keyword"))
    assert mail(invoices_world, "filed")["keywords"] == ["agent-invoice"]

    assert await run(invoices_world, "filed", agent(), again=True) == "done"

    assert mail(invoices_world, "filed")["folder_ids"] == ["inv-hosting/Rechnungen"]
    assert len(invoices_world.fake_gateway.requests) == 1


async def test_a_marked_inbox_invoice_moved_later_is_still_filed(
    invoices_world: Wired,
) -> None:
    """The update route is untouched: an invoice marked in the inbox and
    moved by sorting into a folder it looks in moves on."""
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77")
    )
    marking = worker(invoices_world, agent())
    await marking.run_pass()
    await run(invoices_world, "inv-unlisted", agent())
    assert mail(invoices_world, "inv-unlisted")["keywords"] == ["agent-invoice"]

    mail(invoices_world, "inv-unlisted")["folder_ids"] = ["inv-hosting"]
    invoices_world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    assert mail(invoices_world, "inv-unlisted")["folder_ids"] == [
        "inv-hosting/Rechnungen"
    ]
    found = item(invoices_world, "inv-unlisted")
    assert found is not None and found.reason == "filed"
    assert len(invoices_world.fake_gateway.requests) == 1


async def test_a_marked_inbox_invoice_moved_while_the_feed_expired_is_filed(
    invoices_world: Wired,
) -> None:
    """Its update fell into the gap of a feed that expired. The backfill
    takes up new messages only, so the open item is looked at anew."""
    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77")
    )
    marking = worker(invoices_world, agent())
    await marking.run_pass()
    await run(invoices_world, "inv-unlisted", agent())

    mail(invoices_world, "inv-unlisted")["folder_ids"] = ["inv-hosting"]
    invoices_world.store.set_cursor("stale", invoices_world.clock())
    invoices_world.service.expired.add("stale")
    await marking.run_pass()

    assert mail(invoices_world, "inv-unlisted")["folder_ids"] == [
        "inv-hosting/Rechnungen"
    ]
    found = item(invoices_world, "inv-unlisted")
    assert found is not None and found.reason == "filed"


def test_a_stranger_cannot_blow_up_the_call() -> None:
    """Subject, name and attachments are the sender's choice: each is cut,
    the same for the model and for the evidence check."""
    message = MailMessage(
        ref=MessageRef(account_id=ACCOUNT, message_id="m1"),
        sender=Address(email="billing@hosting.example", name="N" * 20_000),
        subject="S" * 20_000,
        text="T" * 20_000,
        attachments=tuple(
            Attachment(filename=f"invoice-{n}.pdf", content_type="x/y", size=1)
            for n in range(5000)
        ),
    )

    rendered = render(message)

    assert len(rendered) < MAX_TEXT + MAX_SUBJECT + MAX_NAME + MAX_FILES_TEXT + 200
    assert "N" * MAX_NAME + " <" in rendered
    assert "S" * (MAX_SUBJECT + 1) not in rendered
    name, subject, *files, text = parts(message)
    assert name == "N" * MAX_NAME + " <billing@hosting.example>"
    assert subject == "S" * MAX_SUBJECT
    assert 0 < len(files) <= MAX_FILES
    assert all(f in rendered for f in files)
    assert f"invoice-{len(files)}.pdf" not in rendered
    assert text == "T" * MAX_TEXT


async def test_taking_the_keyword_off_has_a_skipped_invoice_looked_at_again(
    invoices_world: Wired,
) -> None:
    """The owner takes the keyword off a marked invoice the state file did
    not know: the update takes it up again (decided 2026-11-19)."""
    invoices_world.fake_gateway.answer(answer("invoice", "Ihre Rechnung R-77"))
    running = worker(invoices_world, agent())
    await running.run_pass()
    mail(invoices_world, "filed")["keywords"] = ["agent-invoice"]
    invoices_world.service.change("message.created", "filed")
    await running.run_pass()
    ref = MessageRef(account_id=ACCOUNT, message_id="filed")
    row = invoices_world.store.message(ref)
    assert row is not None and row.state == "skipped"

    mail(invoices_world, "filed")["keywords"] = []
    invoices_world.service.change("message.updated", "filed")
    await running.run_pass()
    await running.run_pass()

    row = invoices_world.store.message(ref)
    assert row is not None and row.state == "done"
    assert len(invoices_world.fake_gateway.requests) == 1
    assert mail(invoices_world, "filed")["folder_ids"] == ["inv-hosting/Rechnungen"]


async def test_an_update_that_keeps_the_keyword_leaves_it_skipped(
    invoices_world: Wired,
) -> None:
    running = worker(invoices_world, agent())
    await running.run_pass()
    mail(invoices_world, "filed")["keywords"] = ["agent-invoice"]
    invoices_world.service.change("message.created", "filed")
    await running.run_pass()

    invoices_world.service.change("message.updated", "filed")
    await running.run_pass()
    await running.run_pass()

    row = invoices_world.store.message(
        MessageRef(account_id=ACCOUNT, message_id="filed")
    )
    assert row is not None and row.state == "skipped"
    assert invoices_world.fake_gateway.requests == []
    assert mail(invoices_world, "filed")["folder_ids"] == ["inv-hosting"]


async def test_a_lone_surrogate_in_the_mail_ends_no_worker(
    invoices_world: Wired,
) -> None:
    odd = chr(0xDCFC)
    invoices_world.service.add(
        wire_message(
            "odd",
            subject=f"Ihre Rechnung R-90{odd}",
            text=f"Ihre Rechnung R-90 liegt bei.{odd}",
        ),
        change=None,
    )
    invoices_world.fake_gateway.answer(answer("invoice", "Ihre Rechnung R-90"))

    assert await run(invoices_world, "odd", agent()) == "done"


def test_a_long_address_is_cut_for_the_model_and_the_check() -> None:
    address = "a" * 100_000 + "@hosting.example"
    message = MailMessage(
        ref=MessageRef(account_id=ACCOUNT, message_id="m1"),
        sender=Address(email=address, name="Billing"),
        subject="Rechnung",
        text="Text",
    )

    rendered = render(message)

    assert len(rendered) < MAX_ADDRESS + 200
    name = parts(message)[0]
    assert name == f"Billing <{address[:MAX_ADDRESS]}>"
    assert name in rendered
