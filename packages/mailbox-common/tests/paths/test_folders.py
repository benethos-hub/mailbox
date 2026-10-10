"""The settings file named on purpose and the folders of the system."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import pytest

from benethos_mailbox_common.paths.folders import named_file, system_folders

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
    assert system_folders("app") == (tmp_path / "config", tmp_path / "data")
    other = tmp_path / "share"
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(other))
    assert system_folders("app") == (tmp_path, other)


def test_the_folders_are_the_apps_own(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = []

    def where(app: str, **options: object) -> str:
        asked.append((app, options))
        return f"/{app}"

    monkeypatch.setattr(platformdirs, "user_config_dir", where)
    monkeypatch.setattr(platformdirs, "user_data_dir", where)
    system_folders("benethos-x")
    assert asked == [("benethos-x", {"appauthor": False, "roaming": False})] * 2
