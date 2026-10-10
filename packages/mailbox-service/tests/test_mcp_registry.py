"""The MCP server's entry in the MCP Registry.

An entry cannot be changed once the registry took it, so what it repeats
from the package is held to the package here: the version, the name in
all places that name it, the description, the settings and the icons. The
release job of publish.yml sends it.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from benethos_mailbox_client import environment

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / ".github" / "publish" / "mcp-registry" / "server.json"
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


def test_the_entry_lists_the_package_on_pypi_alone() -> None:
    """The image is left out: in a container 127.0.0.1 is not the
    machine of the service. The image stays the way over HTTP."""
    assert [p["registryType"] for p in _entry()["packages"]] == ["pypi"]
    (package,) = _packages("pypi")
    assert package["identifier"] == _project()["name"]
    assert package["registryBaseUrl"] == "https://pypi.org"
    assert package["transport"] == {"type": "stdio"}


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


def test_the_job_waits_for_the_package_and_checks_the_tag() -> None:
    """The registry checks the package on PyPI when it takes the entry,
    and a pre-release is never listed."""
    job = _job("mcp-registry")
    assert re.search(r"^    needs: \[pypi-mcp\]$", job, re.M)
    assert "!github.event.release.prerelease" in job
    assert "contents: read" in job and "id-token: write" in job
    assert "does not match the entry's version" in job
    assert re.search(r"MCP_PUBLISHER_SHA256: [0-9a-f]{64}$", job, re.M)
    assert ".github/publish/mcp-registry/server.json" in job
