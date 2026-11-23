"""Settings from the command line, the environment, a file and the
defaults, in that order."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from pydantic import Field, ValidationError, model_validator

from benethos_mailbox_common.settings.files import (
    FileSettings,
    env_name,
    load,
    problems,
    secret_file,
)


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


class Guarded(FileSettings):
    model_config = {"env_prefix": "MAILBOX_TEST_"}

    port: int = Field(default=8000, ge=1, le=65535)
    token: str = Field(default="", alias="MAILBOX_TOKEN", max_length=10)
    client_id: str = ""
    client_secret: str = ""

    @model_validator(mode="after")
    def _together(self) -> Guarded:
        if self.client_secret and not self.client_id:
            raise ValueError("a client secret needs its client id")
        return self


def test_problems_name_each_setting_and_never_the_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAILBOX_TEST_PORT", "99999")
    monkeypatch.setenv("MAILBOX_TOKEN", "x" * 5000)
    with pytest.raises(ValidationError) as caught:
        Guarded(_env_file=None)
    found = problems(Guarded, caught.value)
    assert [line.split(":")[0] for line in found] == [
        "MAILBOX_TEST_PORT",
        "MAILBOX_TOKEN",
    ]
    assert "xxxxx" not in str(found)
    assert "99999" not in str(found)

    monkeypatch.delenv("MAILBOX_TEST_PORT")
    monkeypatch.delenv("MAILBOX_TOKEN")
    monkeypatch.setenv("MAILBOX_TEST_CLIENT_SECRET", "secret-from-the-test")
    with pytest.raises(ValidationError) as caught:
        Guarded(_env_file=None)
    found = problems(Guarded, caught.value)
    assert found == ["Value error, a client secret needs its client id"]
    assert "secret-from-the-test" not in str(found)


def test_the_name_of_a_setting_is_its_alias_or_prefixed() -> None:
    assert env_name(Guarded, "token") == "MAILBOX_TOKEN"
    assert env_name(Guarded, "client_id") == "MAILBOX_TEST_CLIENT_ID"
    assert env_name(Guarded, "MAILBOX_TOKEN") == "MAILBOX_TOKEN"


def test_a_secret_file_loses_its_blanks_and_the_mark_of_utf8(
    tmp_path: Path,
) -> None:
    path = tmp_path / "secret"
    path.write_bytes(b"\xef\xbb\xbf  token \r\n")
    assert secret_file(path) == "token"
    path.write_text("plain\n", encoding="utf-8")
    assert secret_file(path) == "plain"
