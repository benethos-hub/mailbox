"""What the two distributions ship beside their code.

Each package carries a copy of the repository's LICENSE, since a wheel can
only include files from its own folder, and both are released together
under one version.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = [ROOT / "packages" / "mailbox-service", ROOT / "packages" / "mailbox-mcp"]


def _project(package: Path) -> dict[str, object]:
    data = tomllib.loads((package / "pyproject.toml").read_text("utf-8"))
    return dict(data["project"])


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_the_license_is_the_repositorys(package: Path) -> None:
    assert (package / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert _project(package)["license-files"] == ["LICENSE"]


def test_both_packages_share_one_version() -> None:
    versions = {_project(package)["version"] for package in PACKAGES}
    assert len(versions) == 1, versions
