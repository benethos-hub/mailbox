from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_api import __version__
from benethos_mailbox_api.__main__ import main
from benethos_mailbox_api.config import Settings


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_serve_starts_uvicorn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: dict[str, object] = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(kw))
    assert main(["serve", "--port", "9999"]) == 0
    assert calls["port"] == 9999
    assert calls["host"] == "127.0.0.1"
    assert "storage: memory" in capsys.readouterr().err


def test_serve_names_the_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import uvicorn

    from benethos_mailbox_api import main as assembly

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    # No app: without uvicorn nothing would close its database.
    monkeypatch.setattr(assembly, "create_app", lambda settings: None)
    monkeypatch.setenv("MAILBOX_API_STORAGE", "sqlite")
    monkeypatch.setenv("MAILBOX_API_DATA_DIR", str(tmp_path))
    assert main(["serve"]) == 0
    assert f"database: {tmp_path.resolve() / 'mailbox.db'}" in capsys.readouterr().err


def test_default_data_dir_is_under_data_in_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MAILBOX_API_DATA_DIR")
    monkeypatch.chdir(tmp_path)
    assert Settings().database_path == (
        tmp_path.resolve() / "data" / "benethos-mailbox-api" / "mailbox.db"
    )


def test_env_example_holds_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MAILBOX_API_DATA_DIR",
        "MAILBOX_API_STORAGE",
        "MAILBOX_API_KEY_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    example = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "benethos-mailbox-api"
        / ".env.example"
    )
    from_file = Settings(_env_file=example)  # type: ignore[call-arg]
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    assert from_file == defaults
    assert from_file.api_key is None
