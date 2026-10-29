"""The Claude Desktop bundle of the MCP server.

The manifest is committed as it ships, so nothing makes it anew on a
release. What it repeats from the package is held to the package here:
the version, the metadata, the tools and the settings. The bundle itself
is staged by .github/publish/mcpb/build.py, which runs into a temporary
folder below.
"""

from __future__ import annotations

import inspect
import json
import re
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

from benethos_mailbox_client import environment
from benethos_mailbox_mcp.tools import TOOLS

from .publish_helpers import PACKAGES, ROOT, project_of, workflow_job
from .scripts_helpers import script_module

BUNDLE = ROOT / ".github" / "publish" / "mcpb"
MCP = PACKAGES[2]


def _manifest() -> dict[str, Any]:
    return dict(json.loads((BUNDLE / "manifest.json").read_text("utf-8")))


def _build() -> ModuleType:
    return script_module("mcpb_build", BUNDLE / "build.py")


def _first_sentence(text: str) -> str:
    """A tool's description cut to its first sentence, as Claude Desktop
    shows it before the install. "e.g." ends no sentence."""
    line = " ".join(text.split()).replace("`", "")
    head = re.split(r"(?<!e\.g)(?<!i\.e)\. ", line)[0]
    return head.rstrip(".") + "."


def test_the_bundle_has_the_packages_version_and_metadata() -> None:
    manifest, project = _manifest(), project_of(MCP)
    assert manifest["name"] == project["name"]
    assert manifest["version"] == project["version"]
    assert manifest["description"] == project["description"]
    assert manifest["author"] == {"name": project["authors"][0]["name"]}
    assert manifest["license"] == project["license"]
    assert manifest["compatibility"]["runtimes"] == {
        "python": project["requires-python"]
    }


def test_the_bundle_lists_every_tool_in_order() -> None:
    """Which of them a token sees depends on its rights. Claude Desktop
    shows all of them before the install."""
    wanted = [
        {
            "name": tool.fn.__name__,
            "description": _first_sentence(tool.fn.__doc__ or ""),
        }
        for tool in TOOLS
    ]
    listed = _manifest()["tools"]
    assert listed == wanted, "expected:\n" + json.dumps(wanted, indent=2)
    assert all(inspect.getdoc(tool.fn) for tool in TOOLS)


def test_uv_starts_the_locked_server() -> None:
    server = _manifest()["server"]
    assert server["type"] == "uv"
    assert server["entry_point"] == "server.py"
    args = server["mcp_config"]["args"]
    assert server["mcp_config"]["command"] == "uv"
    assert args[:1] == ["run"] and args[-1] == server["entry_point"]
    assert "--frozen" in args
    assert (BUNDLE / server["entry_point"]).is_file()


def test_the_settings_are_the_clients() -> None:
    """A token, required and kept secret. The address with the client's
    default, and http to another machine off unless switched on. The
    server sends nothing to a service of anyone else, so the manifest
    names no privacy policy."""
    manifest = _manifest()
    config = manifest["user_config"]
    assert list(config) == ["service_token", "service_url", "allow_http"]
    token, address, allow = config.values()
    assert (token["type"], token["sensitive"], token["required"]) == (
        "string",
        True,
        True,
    )
    assert (address["required"], address["default"]) == (False, environment.DEFAULT_URL)
    assert (allow["type"], allow["required"], allow["default"]) == (
        "boolean",
        False,
        False,
    )
    assert not address.get("sensitive") and not allow.get("sensitive")
    assert manifest["server"]["mcp_config"]["env"] == {
        environment.TOKEN_ENV: "${user_config.service_token}",
        environment.URL_ENV: "${user_config.service_url}",
        environment.ALLOW_HTTP_ENV: "${user_config.allow_http}",
    }
    assert "privacy_policies" not in manifest


def test_the_staged_bundle_pins_the_package_on_pypi(tmp_path: Path) -> None:
    build, project = _build(), project_of(MCP)
    target = tmp_path / "bundle"
    build.stage(target)
    assert sorted(p.name for p in target.iterdir()) == [
        "LICENSE",
        "README.md",
        "icon.png",
        "manifest.json",
        "pyproject.toml",
        "server.py",
    ]
    staged = tomllib.loads((target / "pyproject.toml").read_text("utf-8"))
    assert staged["project"]["dependencies"] == [
        f"{project['name']}=={project['version']}"
    ]
    assert staged["project"]["requires-python"] == project["requires-python"]
    assert staged["tool"]["uv"] == {"package": False}
    icon = (target / "icon.png").read_bytes()
    assert icon == (ROOT / "assets" / "brand" / "icon.png").read_bytes()
    assert (target / _manifest()["icon"]).is_file()


def test_the_job_packs_after_the_upload_and_attaches_twice() -> None:
    """Staged and locked against PyPI here, then packed, checked against
    its version and attached twice by the action publish/mcpb."""
    job = workflow_job("mcpb-bundle")
    assert re.search(r"^    needs: \[pypi-mcp\]$", job, re.M)
    assert "contents: write" in job and "persist-credentials: false" in job
    staged = job.index("uv run --no-project .github/publish/mcpb/build.py")
    locked = job.index("--refresh-package benethos-mailbox-mcp")
    packed = job.index("benethos-hub/.github/actions/publish/mcpb@main")
    assert staged < locked < packed
    assert "--frozen" not in job  # the lock is made here, used on install
    assert f"name: {project_of(MCP)['name']}\n" in job
