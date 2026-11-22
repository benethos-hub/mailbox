"""Where the files of the repository are, for the tests of the client."""

from __future__ import annotations

from pathlib import Path

# The root of the repository, found once for the suite.
ROOT = Path(__file__).resolve().parents[3]
# The contract the client is held to.
OPENAPI = ROOT / "docs" / "mailbox-service" / "openapi.json"
