"""The gold files of the test account of containers/live/mailbox-agents/.

    uv run python live/mailbox-agents/gold.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]
        [--out FOLDER]

The invented mail of containers/live/mailbox-agents/mail.py comes with its
labels. This fetches the messages of the test account, finds each by its
Message-ID and writes gold-<agent>.jsonl beside the settings file, or into
the folder --out names, so an agent can be evaluated against it:

    uv run benethos-mailbox-agents
        --env-file containers/live/mailbox-agents/secrets/agent.env
        eval --agent invoices
        --gold containers/live/mailbox-agents/secrets/gold-invoices.jsonl
        --reports containers/live/mailbox-agents/secrets/reports

It only reads. Never point it at an account that is not a test account.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from agents_common import (  # beside this script
    DAYS,
    ENV,
    ROOT,
    connect_mailbox,
    live_settings,
    mail,
)

from benethos_mailbox_agents.settings import Settings


def target(env_file: Path, out: Path | None) -> Path:
    """Where the gold files go: the folder ``--out`` names, else the folder
    of the settings file, so a live setup made elsewhere keeps its own."""
    return out if out is not None else env_file.resolve().parent


async def collect(settings: Settings) -> dict[str, list[str]]:
    """The lines of each agent's gold file, from the messages of the test
    account that mail.py labels."""
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
    return lines


def save(lines: dict[str, list[str]], folder: Path) -> list[Path]:
    """Each agent's lines as ``folder``/gold-<agent>.jsonl."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for agent, found in sorted(lines.items()):
        path = folder / f"gold-{agent}.jsonl"
        path.write_bytes(("\n".join(found) + "\n").encode("utf-8"))
        written.append(path)
    return written


def _shown(path: Path) -> Path:
    """``path`` from the repository when it lies in it, else as it is."""
    resolved = path.resolve()
    return resolved.relative_to(ROOT) if resolved.is_relative_to(ROOT) else resolved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The gold files of the test account.")
    parser.add_argument("--env-file", type=Path, default=ENV)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    found = live_settings(args.env_file, "gold")
    folder = target(args.env_file, args.out)
    for path in save(asyncio.run(collect(found)), folder):
        count = len(path.read_text(encoding="utf-8").splitlines())
        print(f"gold: {_shown(path)} ({count} messages)")
