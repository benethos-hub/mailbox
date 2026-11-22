"""Alias entry point for ``python -m benethos_mailbox_agents``."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
