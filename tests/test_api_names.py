"""Names the MCP server takes from the API as literals, held to the API's
own document, docs/openapi.json. The MCP server cannot import the
service, so its names are checked here, where both are read."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from .repository_helpers import ROOT

RENDER = ROOT / "packages/mailbox-mcp/src/benethos_mailbox_mcp/render.py"


def _keys_of(path: Path, name: str) -> set[str]:
    """The keys of the dict a module assigns to ``name``."""
    tree = ast.parse(path.read_text("utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == name for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            return {ast.literal_eval(key) for key in node.value.keys if key}
    raise AssertionError(f"{path} assigns no dict {name}")


def test_the_limits_an_account_names_are_capabilities_of_the_api() -> None:
    """``render.ACCOUNT_LIMITS`` names what an account cannot do by the
    API's ``Capability``. A name the API does not know would never match."""
    document = json.loads((ROOT / "docs/openapi.json").read_text("utf-8"))
    capabilities = set(document["components"]["schemas"]["Capability"]["enum"])
    limits = _keys_of(RENDER, "ACCOUNT_LIMITS")
    assert limits, "ACCOUNT_LIMITS is empty"
    assert limits <= capabilities, sorted(limits - capabilities)
