"""What the tests of invoices share: the invented messages and the gold
set, an agent in a stage, and the model's answer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benethos_mailbox_agents.agents.invoices.agent import Invoices

from ..agents_fake import invented
from ..agents_helpers import (
    settings,
)

GOLD = Path(__file__).resolve().parent.parent / "data" / "gold-invoices.jsonl"


MESSAGES = {m["id"]: m for m in invented()}


# The folders of the fake service: Invoices, and below it Hosting, mo,
# CloudHost and Telco.
LOOKS_IN = ["Invoices/*"]


SUBFOLDER = "{folder}/Rechnungen"


def agent(stage: str = "full", **values: Any) -> Invoices:
    found: dict[str, Any] = {
        "invoices_folders": LOOKS_IN,
        "invoices_subfolder": SUBFOLDER,
    }
    return Invoices(settings(stage=stage, **{**found, **values}))


def answer(label: str, quote: str, near_miss: str = "none") -> dict[str, Any]:
    return {"label": label, "near_miss": near_miss, "quote": quote}
