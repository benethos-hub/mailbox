"""The command ``storage move`` without a database server: it is named
in the help, it needs the settings of a server whatever the storage
says, and it refuses a file that is there before it opens anything."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_service.cli import main, parser

PASSWORD = "an-invented-role-password"  # pragma: allowlist secret


def test_the_help_names_storage_move(capsys: pytest.CaptureFixture[str]) -> None:
    assert "storage" in parser().format_help()
    with pytest.raises(SystemExit):
        main(["storage", "move", "--help"])
    out = capsys.readouterr().out
    assert "--to {postgres,sqlite}" in out
    assert "--check" in out


def test_a_move_needs_the_settings_of_a_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    assert main(["storage", "move", "--to", "postgres", "--check"]) == 1
    err = capsys.readouterr().err
    assert "storage move: storage postgres needs database_url" in err


def test_a_file_that_is_there_is_refused_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    password = tmp_path / "database_password"
    password.write_text(PASSWORD, encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "mailbox.db").write_bytes(b"")
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    # Nothing listens there: the refusal comes before a connection.
    monkeypatch.setenv(
        "MAILBOX_SERVICE_DATABASE_URL", "postgresql://svc@127.0.0.1:9/mailbox"
    )
    monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_PASSWORD_FILE", str(password))
    assert main(["storage", "move", "--to", "sqlite"]) == 1
    err = capsys.readouterr().err
    assert "exists: a move goes into a new database only" in err
    assert PASSWORD not in err
