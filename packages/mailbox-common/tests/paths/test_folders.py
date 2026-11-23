"""The settings file named on purpose and the folders of the system."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import platformdirs
import pytest

from benethos_mailbox_common.paths.folders import (
    Folders,
    SystemFolders,
    named_file,
    program_folders,
    system_folders,
)

VARIABLE = "MAILBOX_TEST_ENV_FILE"


def test_a_file_named_on_the_command_line_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VARIABLE, str(tmp_path / "from-env.env"))
    assert named_file(tmp_path / "given.env", VARIABLE) == tmp_path / "given.env"
    assert named_file(None, VARIABLE) == tmp_path / "from-env.env"


def test_without_a_name_there_is_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIABLE, "")
    assert named_file(None, VARIABLE) is None
    monkeypatch.delenv(VARIABLE)
    assert named_file(None, VARIABLE) is None


def test_one_system_folder_for_both_gets_one_below_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As on Windows and macOS: a copy of the data never holds a key file
    from the config folder."""
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(tmp_path))
    assert system_folders("app") == SystemFolders(
        config=tmp_path / "config", data=tmp_path / "data"
    )
    other = tmp_path / "share"
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(other))
    assert system_folders("app") == SystemFolders(config=tmp_path, data=other)


def test_the_folders_are_the_apps_own(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = []

    def where(app: str, **options: object) -> str:
        asked.append((app, options))
        return f"/{app}"

    monkeypatch.setattr(platformdirs, "user_config_dir", where)
    monkeypatch.setattr(platformdirs, "user_data_dir", where)
    system_folders("benethos-x")
    assert asked == [("benethos-x", {"appauthor": False, "roaming": False})] * 2


def test_without_the_extra_the_import_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """platformdirs comes with ``benethos-mailbox-common[paths]``."""
    monkeypatch.setitem(sys.modules, "platformdirs", None)
    monkeypatch.delitem(sys.modules, "benethos_mailbox_common.paths.folders")
    with pytest.raises(ModuleNotFoundError, match=r"benethos-mailbox-common\[paths\]"):
        importlib.import_module("benethos_mailbox_common.paths.folders")


def test_the_folders_of_a_program_first_found_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *a, **k: "/c")
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: "/d")
    local, data = Path("config/app/.env"), Path("data/app")

    named = program_folders("app", Path("x/s.env"), VARIABLE, local, data)
    assert named == Folders(
        "named",
        (tmp_path / "x").resolve(),
        (tmp_path / "x/s.env").resolve(),
        (tmp_path / "x").resolve() / data,
    )
    assert program_folders("app", None, VARIABLE, local, data) == Folders(
        "system", Path("/c"), Path("/c/.env"), Path("/d")
    )
    (tmp_path / "data/app").mkdir(parents=True)
    assert program_folders("app", None, VARIABLE, local, data) == Folders(
        "working directory", Path("config/app"), local, data
    )
