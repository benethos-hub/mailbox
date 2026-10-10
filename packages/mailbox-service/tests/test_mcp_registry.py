"""The MCP server's entry in the MCP Registry.

An entry cannot be changed once the registry took it, so what it repeats
from the package is held to the package here: the version, the name in
all places that name it, the description, the settings and the icons. The
release job of publish.yml sends it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from benethos_mailbox_client import environment

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / ".github" / "publish" / "mcp-registry" / "server.json"
FILL = ENTRY.parent / "fill_bundle_checksum.py"
MCP = ROOT / "packages" / "mailbox-mcp"
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
OWNER = "benethos-hub"
RAW = f"https://raw.githubusercontent.com/{OWNER}/mailbox/main/"


def _entry() -> dict[str, Any]:
    return dict(json.loads(ENTRY.read_text("utf-8")))


def _project() -> dict[str, Any]:
    return dict(tomllib.loads((MCP / "pyproject.toml").read_text("utf-8"))["project"])


def _packages(kind: str) -> list[dict[str, Any]]:
    return [p for p in _entry()["packages"] if p["registryType"] == kind]


def test_the_entry_names_the_packages_version() -> None:
    version = _project()["version"]
    assert _entry()["version"] == version
    assert [p["version"] for p in _packages("pypi")] == [version]


def test_the_entry_lists_pypi_and_the_bundle() -> None:
    """The image is left out: in a container 127.0.0.1 is not the
    machine of the service. The image stays the way over HTTP."""
    assert [p["registryType"] for p in _entry()["packages"]] == ["pypi", "mcpb"]
    (package,) = _packages("pypi")
    assert package["identifier"] == _project()["name"]
    assert package["registryBaseUrl"] == "https://pypi.org"
    assert package["transport"] == {"type": "stdio"}


def test_the_bundle_is_the_one_the_release_carries() -> None:
    """The release job fills in the checksum of the very file it
    attached. Until then the entry holds the placeholder."""
    version = _project()["version"]
    (bundle,) = _packages("mcpb")
    assert bundle["identifier"] == (
        f"https://github.com/{OWNER}/mailbox/releases/download/v{version}/"
        f"{_project()['name']}-{version}.mcpb"
    )
    assert bundle["fileSha256"] == _fill().PLACEHOLDER
    assert bundle["transport"] == {"type": "stdio"}


def _fill() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fill_bundle_checksum", FILL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_checksum_is_the_bundles_and_written_once(tmp_path: Path) -> None:
    fill = _fill()
    entry = tmp_path / "server.json"
    entry.write_bytes(ENTRY.read_bytes())
    (bundle,) = _packages("mcpb")
    attached = tmp_path / bundle["identifier"].rsplit("/", 1)[-1]
    attached.write_bytes(b"the bundle")
    assert fill.fill(entry, attached) == hashlib.sha256(b"the bundle").hexdigest()
    (filled,) = [
        p
        for p in json.loads(entry.read_text("utf-8"))["packages"]
        if p["registryType"] == "mcpb"
    ]
    assert filled["fileSha256"] == hashlib.sha256(b"the bundle").hexdigest()
    with pytest.raises(SystemExit, match="not the placeholder"):
        fill.fill(entry, attached)
    other = tmp_path / "other.mcpb"
    other.write_bytes(b"x")
    entry.write_bytes(ENTRY.read_bytes())
    with pytest.raises(SystemExit, match="not the file the entry points at"):
        fill.fill(entry, other)


def test_without_the_bundle_the_rest_is_kept(tmp_path: Path) -> None:
    fill = _fill()
    entry = tmp_path / "server.json"
    entry.write_bytes(ENTRY.read_bytes())
    fill.drop(entry)
    kept = json.loads(entry.read_text("utf-8"))
    assert kept["packages"] == _packages("pypi")
    with pytest.raises(SystemExit, match="no bundle"):
        fill.drop(entry)


def test_the_description_is_the_packages() -> None:
    description = _entry()["description"]
    assert description == _project()["description"]
    assert len(description) <= 100


def test_the_name_lies_in_the_owners_namespace() -> None:
    entry = _entry()
    assert entry["name"] == f"io.github.{OWNER}/{_project()['name']}"
    assert entry["repository"] == {
        "url": f"https://github.com/{OWNER}/mailbox",
        "source": "github",
    }


def test_the_readme_on_pypi_proves_the_name_once() -> None:
    """The registry reads the README of the version on PyPI. The name
    ends at a space, a line end or the end of the comment."""
    readme = (MCP / _project()["readme"]).read_text("utf-8")
    found = re.findall(r"mcp-name: (\S+?)(?=\s|-->|$)", readme, re.M)
    assert found == [_entry()["name"]]
    assert f"<!-- mcp-name: {_entry()['name']} -->" in readme


def test_the_settings_are_the_clients() -> None:
    """Over stdio the server needs a token. The address has the
    client's default, and http to another machine stays off unless
    set."""
    (package,) = _packages("pypi")
    settings = {v["name"]: v for v in package["environmentVariables"]}
    assert list(settings) == [
        environment.TOKEN_ENV,
        environment.URL_ENV,
        environment.ALLOW_HTTP_ENV,
    ]
    token = settings[environment.TOKEN_ENV]
    assert (token["isRequired"], token["isSecret"]) == (True, True)
    address = settings[environment.URL_ENV]
    assert address["isRequired"] is False
    assert address["default"] == environment.DEFAULT_URL
    allow = settings[environment.ALLOW_HTTP_ENV]
    assert (allow["isRequired"], allow["format"], allow["default"]) == (
        False,
        "boolean",
        "false",
    )
    assert not any(v.get("isSecret") for v in settings.values() if v is not token)


def test_each_icon_is_a_file_of_the_repository() -> None:
    for icon in _entry()["icons"]:
        assert icon["src"].startswith(RAW), icon["src"]
        assert len(icon["src"]) <= 255
        path = ROOT / icon["src"].removeprefix(RAW)
        assert path.is_file(), path
        if icon["mimeType"] == "image/png":
            png = path.read_bytes()
            size = [int.from_bytes(png[at : at + 4], "big") for at in (16, 20)]
            assert icon["sizes"] == ["{}x{}".format(*size)]


def _job(name: str) -> str:
    text = WORKFLOW.read_text("utf-8")
    found = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", text, re.M)
    assert found, name
    return found.group(1)


def test_the_job_waits_for_the_packages_and_checks_the_tag() -> None:
    """The registry checks the package on PyPI and the bundle on the
    release when it takes the entry, and a pre-release is never listed.
    The checksum goes in before the entry, and a refused entry goes
    again without the bundle."""
    job = _job("mcp-registry")
    assert re.search(r"^    needs: \[pypi-mcp, mcpb-bundle\]$", job, re.M)
    filled = job.index('fill_bundle_checksum.py "$ENTRY"')
    assert filled < job.index("mcp-publisher publish")
    assert "fill_bundle_checksum.py --drop" in job
    assert "!github.event.release.prerelease" in job
    assert "contents: read" in job and "id-token: write" in job
    assert "does not match the entry's version" in job
    assert re.search(r"MCP_PUBLISHER_SHA256: [0-9a-f]{64}$", job, re.M)
    assert ".github/publish/mcp-registry/server.json" in job
