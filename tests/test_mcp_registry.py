"""The MCP server's entry in the MCP Registry.

An entry cannot be changed once the registry took it, so what it repeats
from the package is held to the package here: the version, the name in
all places that name it, the description, the settings and the icons. The
job mcp-registry of publish.yml sends it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from benethos_mailbox_client import environment

from .publish_helpers import PACKAGES, ROOT, project_of, workflow_job

ENTRY = ROOT / ".github" / "publish" / "mcp-registry" / "server.json"
MCP = PACKAGES[2]
OWNER = "benethos-hub"
RAW = f"https://raw.githubusercontent.com/{OWNER}/mailbox/main/"


def _entry() -> dict[str, Any]:
    return dict(json.loads(ENTRY.read_text("utf-8")))


def _packages(kind: str) -> list[dict[str, Any]]:
    return [p for p in _entry()["packages"] if p["registryType"] == kind]


def test_the_entry_names_the_packages_version() -> None:
    version = project_of(MCP)["version"]
    assert _entry()["version"] == version
    assert [p["version"] for p in _packages("pypi")] == [version]


def test_the_entry_lists_pypi_and_the_bundle() -> None:
    """The image is left out: in a container 127.0.0.1 is not the
    machine of the service. The image stays the way over HTTP."""
    assert [p["registryType"] for p in _entry()["packages"]] == ["pypi", "mcpb"]
    (package,) = _packages("pypi")
    assert package["identifier"] == project_of(MCP)["name"]
    assert package["registryBaseUrl"] == "https://pypi.org"
    assert package["transport"] == {"type": "stdio"}


def test_the_bundle_is_the_one_the_release_carries() -> None:
    """The action publish/mcp-registry fills in the checksum of the very
    file the release carries. Until then the entry holds its placeholder
    of zeros."""
    version = project_of(MCP)["version"]
    (bundle,) = _packages("mcpb")
    assert bundle["identifier"] == (
        f"https://github.com/{OWNER}/mailbox/releases/download/v{version}/"
        f"{project_of(MCP)['name']}-{version}.mcpb"
    )
    assert bundle["fileSha256"] == "0" * 64
    assert bundle["transport"] == {"type": "stdio"}


def test_the_description_is_the_packages() -> None:
    description = _entry()["description"]
    assert description == project_of(MCP)["description"]
    assert len(description) <= 100


def test_the_name_lies_in_the_owners_namespace() -> None:
    entry = _entry()
    assert entry["name"] == f"io.github.{OWNER}/{project_of(MCP)['name']}"
    assert entry["repository"] == {
        "url": f"https://github.com/{OWNER}/mailbox",
        "source": "github",
    }


def test_the_readme_on_pypi_proves_the_name_once() -> None:
    """The registry reads the README of the version on PyPI. The name
    ends at a space, a line end or the end of the comment."""
    readme = (MCP / project_of(MCP)["readme"]).read_text("utf-8")
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


def test_the_job_waits_for_the_packages() -> None:
    """The registry checks the package on PyPI and the bundle on the
    release when it takes the entry, and a pre-release is never listed.
    The action publish/mcp-registry checks the tag, fills in the checksum
    and publishes the entry at its default path, this one."""
    job = workflow_job("mcp-registry")
    assert re.search(r"^    needs: \[pypi-mcp, mcpb-bundle\]$", job, re.M)
    assert "!github.event.release.prerelease" in job
    assert "contents: read" in job and "id-token: write" in job
    assert job.rstrip().endswith(
        "- uses: benethos-hub/.github/actions/publish/mcp-registry@main"
    )
    assert ENTRY.relative_to(ROOT).as_posix() == (
        ".github/publish/mcp-registry/server.json"
    )
