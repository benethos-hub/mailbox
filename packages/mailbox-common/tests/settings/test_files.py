"""Settings from the command line, the environment, a file and the
defaults, in that order."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from pydantic import Field, ValidationError

from benethos_mailbox_common.settings.files import FileSettings, load


class Example(FileSettings):
    model_config = {"env_prefix": "MAILBOX_TEST_"}

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    path: str = "/"


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.env"
    path.write_text(
        "MAILBOX_TEST_HOST=file.example\n"
        "MAILBOX_TEST_PORT=9000\n"
        "MAILBOX_TEST_PATH=/file\n"
        "MAILBOX_OTHER_NAME=left alone\n",
        encoding="utf-8",
    )
    return path


def test_given_wins_over_the_environment_which_wins_over_the_file(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILBOX_TEST_PORT", "9100")
    monkeypatch.setenv("MAILBOX_TEST_PATH", "/environment")
    found = load(Example, env_file, path="/given")
    assert (found.host, found.port, found.path) == ("file.example", 9100, "/given")


def test_without_a_file_the_environment_and_the_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILBOX_TEST_PORT", "9100")
    for missing in (None, tmp_path / "missing.env"):
        found = load(Example, missing)
        assert (found.host, found.port) == ("127.0.0.1", 9100)


def test_a_bad_value_is_refused(env_file: Path) -> None:
    with pytest.raises(ValidationError, match="port"):
        load(Example, env_file, port=0)


def test_without_the_extra_the_import_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """pydantic-settings comes with ``benethos-mailbox-common[settings]``."""
    monkeypatch.setitem(sys.modules, "pydantic_settings", None)
    monkeypatch.delitem(sys.modules, "benethos_mailbox_common.settings.files")
    with pytest.raises(
        ModuleNotFoundError, match=r"benethos-mailbox-common\[settings\]"
    ):
        importlib.import_module("benethos_mailbox_common.settings.files")
