"""The settings of the MCP server and its optional settings file."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from benethos_mailbox_mcp import cli, config

# The real one: conftest.py puts the config folder into a test's own.


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_file_fills_what_the_environment_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = write(
        tmp_path / "mcp.env",
        "MAILBOX_SERVICE_URL=http://127.0.0.1:9090\n"
        "MAILBOX_SERVICE_TOKEN=from-the-file\n"
        "MAILBOX_MCP_PORT=9001\n"
        "MAILBOX_MCP_HOST=0.0.0.0\n"
        "PATH=nothing\n",
    )
    monkeypatch.setenv("MAILBOX_MCP_HOST", "127.0.0.2")
    before = dict(os.environ)
    found = config.load_settings(named)
    assert found.service_url == "http://127.0.0.1:9090"
    assert found.service_token is not None
    assert found.service_token.get_secret_value() == "from-the-file"
    assert found.port == 9001
    assert found.host == "127.0.0.2"  # the environment wins
    assert dict(os.environ) == before  # nothing of the process changes


def test_the_command_line_wins(tmp_path: Path) -> None:
    named = write(tmp_path / "mcp.env", "MAILBOX_MCP_PORT=9001\n")
    found = config.load_settings(named, port=9002, host=None)
    assert (found.port, found.host) == (9002, "127.0.0.1")


@pytest.mark.parametrize(
    ("value", "token"), [("", None), ("   ", None), (" abc \n", "abc")]
)
def test_a_bearer_token_of_blanks_is_none(
    monkeypatch: pytest.MonkeyPatch, value: str, token: str | None
) -> None:
    monkeypatch.setenv("MAILBOX_MCP_BEARER_TOKEN", value)
    found = config.load_settings(None).bearer_token
    assert (found.get_secret_value() if found else None) == token


def test_a_setting_is_named_as_it_is_read() -> None:
    assert config.variable("port") == "MAILBOX_MCP_PORT"
    assert config.variable("service_token") == "MAILBOX_SERVICE_TOKEN"
    assert config.variable("MAILBOX_SERVICE_TOKEN") == "MAILBOX_SERVICE_TOKEN"


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


def test_the_options_read_their_defaults_from_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    named = write(tmp_path / "mcp.env", "MAILBOX_MCP_TRANSPORT=carrier-pigeon\n")
    with pytest.raises(SystemExit):
        cli.main(["--env-file", str(named)])
    assert "not 'carrier-pigeon'" in capsys.readouterr().err


def test_an_option_is_checked_as_the_setting_is(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--port", "0"])
    said = capsys.readouterr().err
    assert "MAILBOX_MCP_PORT" in said and "not 0" in said
