"""The optional settings file of the MCP server."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_mcp import cli, config

# The real one: conftest.py puts the config folder into a test's own.
CONFIG_FOLDER = config.config_folder


@pytest.fixture
def clean_environment() -> Iterator[None]:
    """What a test's file put into the environment goes again."""
    before = set(os.environ)
    yield
    for name in set(os.environ) - before:
        del os.environ[name]


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.usefixtures("clean_environment")
def test_the_file_fills_what_the_environment_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = write(
        tmp_path / "mcp.env",
        "MAILBOX_SERVICE_URL=http://127.0.0.1:9090\n"
        "MAILBOX_MCP_PORT=9001\n"
        "MAILBOX_MCP_HOST=0.0.0.0\n"
        "PATH=nothing\n",
    )
    monkeypatch.setenv("MAILBOX_MCP_HOST", "127.0.0.2")
    path = os.environ["PATH"]
    assert config.load(named) == named.resolve()
    assert os.environ["MAILBOX_SERVICE_URL"] == "http://127.0.0.1:9090"
    assert os.environ["MAILBOX_MCP_PORT"] == "9001"
    assert os.environ["MAILBOX_MCP_HOST"] == "127.0.0.2"  # the environment wins
    assert os.environ["PATH"] == path  # nothing else of the process


def test_first_found_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert config.settings_file() is None
    system = write(config.config_folder() / ".env", "")
    assert config.settings_file() == system.resolve()
    local = write(tmp_path / "local" / ".env", "")
    monkeypatch.setattr(config, "ENV_FILE", "local/.env")
    assert config.settings_file() == local.resolve()
    variable = write(tmp_path / "variable.env", "")
    monkeypatch.setenv("MAILBOX_MCP_ENV_FILE", str(variable))
    assert config.settings_file() == variable.resolve()
    option = write(tmp_path / "option.env", "")
    assert config.settings_file(option) == option.resolve()


def test_a_named_file_must_exist(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        config.settings_file(tmp_path / "missing.env")
    with pytest.raises(SystemExit, match="missing.env not found"):
        cli.main(["--env-file", str(tmp_path / "missing.env")])


def test_one_system_folder_for_both_gets_one_below_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import platformdirs

    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(tmp_path))
    assert CONFIG_FOLDER() == tmp_path / "config"
    other = tmp_path / "share"
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(other))
    assert CONFIG_FOLDER() == tmp_path


@pytest.mark.usefixtures("clean_environment")
def test_the_options_read_their_defaults_from_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    named = write(tmp_path / "mcp.env", "MAILBOX_MCP_TRANSPORT=carrier-pigeon\n")
    with pytest.raises(SystemExit):
        cli.main(["--env-file", str(named)])
    assert "not 'carrier-pigeon'" in capsys.readouterr().err
