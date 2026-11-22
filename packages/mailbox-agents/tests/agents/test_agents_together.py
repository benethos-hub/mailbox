"""invoices beside sorting, each with a state file of its own: an invoice
reaches the subfolder of its group in either order."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.invoices.agent import Invoices
from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.errors import MailboxUnavailableError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.runtime.model import NoModel
from benethos_mailbox_agents.store import Store

from ..fakes import ACCOUNT, invented
from ..helpers import Wired, item, mail, run, settings, wired, worker

QUOTE = "please find attached invoice INV-77"


def invoices(**values: Any) -> Invoices:
    """invoices in full, looking in the folders below Invoices, with the
    subfolder Rechnungen."""
    found: dict[str, Any] = {
        "invoices_folders": ["Invoices/*"],
        "invoices_subfolder": "{folder}/Rechnungen",
    }
    return Invoices(settings(stage="full", **{**found, **values}))


def answer() -> dict[str, Any]:
    return {"label": "invoice", "near_miss": "none", "quote": QUOTE}


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        for message in invented():
            found.service.add(message, change=None)
        yield found


async def sort(world: Wired, tmp_path: Path, message_id: str) -> None:
    """The agent sorting, with a state file of its own, moves the mail of
    accounts@paperworks.example into Invoices/Hosting."""
    listed = tmp_path / "sorting.json"
    listed.write_text(
        '{"groups": [{"name": "Paperworks", "folder": "Invoices/Hosting",'
        ' "senders": ["*@paperworks.example"]}]}',
        encoding="utf-8",
    )
    sorting = Sorting(settings(stage="full", sorting_file=listed))
    with Store.open(tmp_path / "sorting.db") as store:
        moving = Worker(
            agent=sorting,
            store=store,
            mailbox=world.mailbox,
            gateway=NoModel(),
            now=world.clock,
        )
        store.enqueue(
            MessageRef(account_id=ACCOUNT, message_id=message_id), world.clock()
        )
        await moving.process_due()


async def test_invoices_first_then_sorting_moves_it_on(
    world: Wired, tmp_path: Path
) -> None:
    world.fake_gateway.answer(answer())
    marking = worker(world, invoices())
    await marking.run_pass()
    await run(world, "inv-unlisted", invoices())

    await sort(world, tmp_path, "inv-unlisted")
    assert mail(world, "inv-unlisted")["folder_ids"] == ["inv-hosting"]
    world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    assert mail(world, "inv-unlisted")["folder_ids"] == ["inv-hosting/Rechnungen"]
    assert sorted(mail(world, "inv-unlisted")["keywords"]) == [
        "agent-invoice",
        "agent-sorted",
    ]
    found = item(world, "inv-unlisted")
    assert found is not None and (found.is_open, found.reason) == (False, "filed")
    assert len(world.fake_gateway.requests) == 1


async def test_an_invoice_not_moved_into_a_missing_inbox_folder_is_filed_later(
    world: Wired, tmp_path: Path
) -> None:
    missing = invoices(invoices_inbox_folder="Missing")
    world.fake_gateway.answer(answer())
    marking = worker(world, missing)
    await marking.run_pass()
    await run(world, "inv-unlisted", missing)

    found = item(world, "inv-unlisted")
    assert found is not None and found.is_open
    await sort(world, tmp_path, "inv-unlisted")
    world.service.change("message.updated", "inv-unlisted")
    await marking.run_pass()

    assert mail(world, "inv-unlisted")["folder_ids"] == ["inv-hosting/Rechnungen"]
    found = item(world, "inv-unlisted")
    assert found is not None and found.reason == "filed"


async def test_a_filing_cut_short_by_the_service_is_done_on_the_next_pass(
    world: Wired, tmp_path: Path
) -> None:
    world.fake_gateway.answer(answer())
    marking = worker(world, invoices())
    await marking.run_pass()
    await run(world, "inv-unlisted", invoices())
    await sort(world, tmp_path, "inv-unlisted")
    world.service.change("message.updated", "inv-unlisted")
    world.service.write_refusal = (503, "unavailable")

    with pytest.raises(MailboxUnavailableError):
        await marking.run_pass()
    world.service.write_refusal = None
    await marking.run_pass()

    assert mail(world, "inv-unlisted")["folder_ids"] == ["inv-hosting/Rechnungen"]
    found = item(world, "inv-unlisted")
    assert found is not None and (found.is_open, found.reason) == (False, "filed")


async def test_sorting_first_then_invoices_moves_it_on(
    world: Wired, tmp_path: Path
) -> None:
    await sort(world, tmp_path, "inv-unlisted")
    world.fake_gateway.answer(answer())

    assert await run(world, "inv-unlisted", invoices()) == "done"

    assert mail(world, "inv-unlisted")["folder_ids"] == ["inv-hosting/Rechnungen"]
    assert item(world, "inv-unlisted") is None


async def test_an_invoice_sorting_moves_while_the_model_answers_is_filed_there(
    world: Wired,
) -> None:
    """sorting moves the invoice out of the inbox while invoices asks the
    model about it: invoices files it where it lies when it acts, not into
    the inbox folder."""

    def sorting_moves_it() -> None:
        mail(world, "inv-unlisted")["folder_ids"] = ["inv-hosting"]

    world.fake_gateway.answer(answer())
    world.fake_gateway.during = sorting_moves_it

    assert (
        await run(world, "inv-unlisted", invoices(invoices_inbox_folder="Invoices/mo"))
        == "done"
    )

    assert mail(world, "inv-unlisted")["folder_ids"] == ["inv-hosting/Rechnungen"]
    assert item(world, "inv-unlisted") is None
