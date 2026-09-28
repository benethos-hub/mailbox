from __future__ import annotations

import json
from pathlib import Path

import pytest

from benethos_mailbox_service import __version__
from benethos_mailbox_service.__main__ import _parser, main
from benethos_mailbox_service.config import Settings, load_settings
from benethos_mailbox_service.logs import log_config


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
    assert calls["log_config"] == log_config("info")
    assert "storage: memory" in capsys.readouterr().err


def test_serve_names_the_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import uvicorn

    from benethos_mailbox_service import main as assembly

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    # No app: without uvicorn nothing would close its database.
    monkeypatch.setattr(assembly, "create_app", lambda settings: None)
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path))
    assert main(["serve"]) == 0
    assert f"database: {tmp_path.resolve() / 'mailbox.db'}" in capsys.readouterr().err


def test_default_data_dir_is_under_data_in_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MAILBOX_SERVICE_DATA_DIR")
    monkeypatch.chdir(tmp_path)
    assert Settings().database_path == (
        tmp_path.resolve() / "data" / "benethos-mailbox-service" / "mailbox.db"
    )


def test_env_example_holds_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MAILBOX_SERVICE_DATA_DIR",
        "MAILBOX_SERVICE_STORAGE",
        "MAILBOX_SERVICE_KEY_PROVIDER",
        "MAILBOX_SERVICE_SYNC_INTERVAL",
    ):
        monkeypatch.delenv(name, raising=False)
    example = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "benethos-mailbox-service"
        / ".env.example"
    )
    from_file = Settings(_env_file=example)  # type: ignore[call-arg]
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    assert from_file == defaults


@pytest.mark.parametrize(
    ("settings", "named"),
    [
        ({"MAILBOX_SERVICE_LOG_LEVEL": "verbose"}, "log_level"),
        ({"MAILBOX_SERVICE_PORT": "70000"}, "port"),
        ({"MAILBOX_SERVICE_PORT": "0"}, "port"),
        (
            {
                "MAILBOX_SERVICE_WEBHOOK_FIRST_RETRY": "60",
                "MAILBOX_SERVICE_WEBHOOK_LONGEST_RETRY": "30",
            },
            "webhook_longest_retry",
        ),
    ],
)
def test_settings_that_cannot_work_are_named(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: dict[str, str],
    named: str,
) -> None:
    import uvicorn

    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("the service must not start")

    monkeypatch.setattr(uvicorn, "run", never)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    assert main(["serve"]) == 1
    assert named in capsys.readouterr().err


def test_the_log_level_in_any_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_LOG_LEVEL", "WARNING")
    assert Settings().log_level == "warning"


def test_openapi_needs_no_key_and_no_oauth_app(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    monkeypatch.delenv("MAILBOX_SERVICE_KEY_FILE", raising=False)
    monkeypatch.setenv("MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID", "client-1")
    monkeypatch.setenv(
        "MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET_FILE", str(tmp_path / "none")
    )
    assert main(["openapi"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["info"]["title"] == "Mailbox Service"
    assert err == ""


# --- the settings file ----------------------------------------------------------------


def settings_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A settings file with relative paths in a folder of its own, and a
    working directory elsewhere. What the tests set in the environment
    would win over the file, so it goes."""
    for name in ("DATA_DIR", "STORAGE", "KEY_PROVIDER"):
        monkeypatch.delenv(f"MAILBOX_SERVICE_{name}")
    folder = tmp_path / "etc"
    folder.mkdir()
    (folder / "service.env").write_text(
        "MAILBOX_SERVICE_STORAGE=sqlite\n"
        "MAILBOX_SERVICE_DATA_DIR=data\n"
        "MAILBOX_SERVICE_KEY_PROVIDER=file\n"
        "MAILBOX_SERVICE_KEY_FILE=secrets/master.key\n",
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return folder


@pytest.mark.parametrize("by", ["option", "variable"])
def test_a_named_settings_file_is_the_base_of_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, by: str
) -> None:
    folder = settings_folder(tmp_path, monkeypatch)
    named = Path("..") / "etc" / "service.env"
    if by == "variable":
        monkeypatch.setenv("MAILBOX_SERVICE_ENV_FILE", str(named))
    settings = load_settings(named if by == "option" else None)
    assert settings.storage == "sqlite"
    assert settings.database_path == folder.resolve() / "data" / "mailbox.db"
    assert settings.key_file == folder.resolve() / "secrets" / "master.key"


def test_an_absolute_path_in_a_named_file_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = settings_folder(tmp_path, monkeypatch)
    elsewhere = (tmp_path / "db").resolve()
    with (folder / "service.env").open("a", encoding="utf-8") as file:
        file.write(f"MAILBOX_SERVICE_DATA_DIR={elsewhere}\n")
    assert load_settings(folder / "service.env").data_dir == elsewhere


def test_without_a_named_file_the_working_directory_is_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_folder(tmp_path, monkeypatch)
    assert load_settings().data_dir == Path("data/benethos-mailbox-service")


@pytest.mark.parametrize(
    "command",
    [
        ["serve"],
        ["users", "create-admin"],
        ["keys", "init"],
        ["backup", "out.backup"],
        ["restore", "in.backup"],
    ],
)
def test_every_command_refuses_a_named_file_that_is_not_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    missing = tmp_path / "missing.env"
    assert main([*command, "--env-file", str(missing)]) == 1
    assert f"settings file {missing} not found" in capsys.readouterr().err


def test_the_option_goes_before_or_after_the_command() -> None:
    parse = _parser().parse_args
    assert parse(["--env-file", "a.env", "users", "create-admin"]).env_file == Path(
        "a.env"
    )
    assert parse(["users", "create-admin", "--env-file", "b.env"]).env_file == Path(
        "b.env"
    )
    assert parse(["--env-file", "a.env", "serve", "--env-file", "b.env"]).env_file == (
        Path("b.env")
    )
    assert parse(["serve"]).env_file is None


def test_the_commands_keep_their_data_beside_a_named_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Started from another folder, every command finds the same data."""
    folder = settings_folder(tmp_path, monkeypatch)
    named = str(folder / "service.env")
    assert main(["keys", "init", "--env-file", named]) == 0
    assert main(["--env-file", named, "users", "create-admin"]) == 0
    assert main(["backup", "copy.backup", "--env-file", named]) == 0
    assert (folder / "secrets" / "master.key").is_file()
    assert (folder / "data" / "mailbox.db").is_file()
    assert (tmp_path / "elsewhere" / "copy.backup").is_file()
    assert not (tmp_path / "elsewhere" / "data").exists()
    capsys.readouterr()


def test_serve_names_the_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import uvicorn

    from benethos_mailbox_service import main as assembly

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    monkeypatch.setattr(assembly, "create_app", lambda settings: None)
    folder = settings_folder(tmp_path, monkeypatch)
    assert main(["serve", "--env-file", str(folder / "service.env")]) == 0
    err = capsys.readouterr().err
    assert f"settings: {(folder / 'service.env').resolve()}" in err
    assert f"database: {(folder / 'data' / 'mailbox.db').resolve()}" in err
    assert main(["serve"]) == 0
    assert "settings: the environment alone" in capsys.readouterr().err
