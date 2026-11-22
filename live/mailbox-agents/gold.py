"""The gold files of the test account of containers/live/mailbox-agents/.

    uv run python live/mailbox-agents/gold.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

The invented mail of containers/live/mailbox-agents/mail.py comes with its
labels. This fetches the messages of the test account, finds each by its
Message-ID and writes
containers/live/mailbox-agents/secrets/gold-<agent>.jsonl, so an agent can
be evaluated against it:

    uv run benethos-mailbox-agents
        --env-file containers/live/mailbox-agents/secrets/agent.env
        eval --agent invoices
        --gold containers/live/mailbox-agents/secrets/gold-invoices.jsonl
        --reports containers/live/mailbox-agents/secrets/reports

It only reads. Never point it at an account that is not a test account.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from agents_common import (  # beside this script
    DAYS,
    LIVE,
    ROOT,
    connect_mailbox,
    mail,
    parse_settings,
)

from benethos_mailbox_agents.settings import Settings


async def write(settings: Settings) -> list[Path]:
    lines: dict[str, list[str]] = {}
    async with connect_mailbox(settings) as mailbox:
        refs = await mailbox.recent(
            date.today() - timedelta(days=DAYS),
            settings.accounts,
            roles=("inbox", "sent"),
        )
        for ref in refs:
            message = await mailbox.message(ref)
            local = mail.local(message.message_id_header)
            for agent, (label, fields) in mail.GOLD.get(local, {}).items():
                item = {
                    "account_id": ref.account_id,
                    "message_id": ref.message_id,
                    "label": label,
                    "fields": fields,
                    "note": local,
                }
                lines.setdefault(agent, []).append(json.dumps(item))
    written = []
    for agent, found in sorted(lines.items()):
        path = LIVE / "secrets" / f"gold-{agent}.jsonl"
        path.write_bytes(("\n".join(found) + "\n").encode("utf-8"))
        written.append(path)
    return written


if __name__ == "__main__":
    found = parse_settings("gold", "The gold files of the test account.")
    for path in asyncio.run(write(found)):
        count = len(path.read_text(encoding="utf-8").splitlines())
        print(f"gold: {path.relative_to(ROOT)} ({count} messages)")
