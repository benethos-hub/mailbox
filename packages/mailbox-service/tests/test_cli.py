from __future__ import annotations

import json
from pathlib import Path

import pytest

from benethos_mailbox_service import __version__, config
from benethos_mailbox_service.cli import main, parser
from benethos_mailbox_service.config import Settings, load_settings

# The real one: conftest.py puts the system's folders into a test's own.
SYSTEM_FOLDERS = config.system_folders


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
    # stderr, and the lines the log page shows.
    assert calls["log_config"]["root"]["handlers"] == ["stderr", "book"]
    # The log names where the settings came from, nothing is printed.
    assert "settings: " not in capsys.readouterr().err


def test_the_start_names_the_settings_and_the_database(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from fastapi.testclient import TestClient

    from benethos_mailbox_service.assembly import create_app
    from benethos_mailbox_service.data.storage import SCHEMA_VERSION

    settings = Settings(storage="sqlite", data_dir=tmp_path, sync_interval=0)
    named = tmp_path / "service.env"
    with caplog.at_level("INFO"), TestClient(create_app(settings, settings_file=named)):
        pass
    lines = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert lines == [
        f"the service created the database with schema {SCHEMA_VERSION}",
        f"the service started: settings from {named}, database "
        f"{settings.database_path}, schema {SCHEMA_VERSION}",
        "the service stopped",
    ]


def test_the_start_in_memory_names_no_database(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi.testclient import TestClient

    from benethos_mailbox_service.assembly import create_app

    settings = Settings(storage="memory", sync_interval=0)
    with caplog.at_level("INFO"), TestClient(create_app(settings)):
        pass
    assert (
        "the service started: settings from the environment alone, storage in "
        "memory" in caplog.text
    )


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
        (
            {
                "MAILBOX_SERVICE_IMAP_FIRST_PAUSE": "60",
                "MAILBOX_SERVICE_IMAP_LONGEST_PAUSE": "30",
            },
            "imap_longest_pause",
        ),
        ({"MAILBOX_SERVICE_SIGN_IN_FAILURES": "0"}, "sign_in_failures"),
        ({"MAILBOX_SERVICE_SYNC_WATCHERS": "0"}, "sync_watchers"),
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
    assert json.loads(out)["info"]["title"] == "mailbox-service"
    assert err == ""


@pytest.mark.parametrize("command", [["openapi"], ["keys", "generate"]])
def test_every_command_takes_the_settings_file(
    command: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Also the two that read no settings: before or after the command."""
    settings = tmp_path / "service.env"
    settings.write_text("", encoding="utf-8")
    assert main([*command, "--env-file", str(settings)]) == 0
    assert main(["--env-file", str(settings), *command]) == 0
    assert capsys.readouterr().out


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


@pytest.mark.parametrize("folder", ["config", "data"])
def test_the_repository_layout_in_the_working_directory_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, folder: str
) -> None:
    """Either folder of the repository's layout keeps an installation
    where it was: relative paths count from the working directory."""
    settings_folder(tmp_path, monkeypatch)
    (Path(folder) / "benethos-mailbox-service").mkdir(parents=True)
    assert config.folders().origin == "working directory"
    assert load_settings().data_dir == Path("data/benethos-mailbox-service")


def test_without_the_repository_the_folders_of_the_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings_folder(tmp_path, monkeypatch)
    system, data = config.system_folders()  # in tmp_path, see conftest.py
    assert config.folders().origin == "system"
    assert load_settings().data_dir == data
    assert config.settings_file() is None

    system.mkdir(parents=True)
    (system / ".env").write_text(
        "MAILBOX_SERVICE_KEY_PROVIDER=file\nMAILBOX_SERVICE_KEY_FILE=master.key\n",
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.key_file == system / "master.key"
    assert settings.data_dir == data
    assert config.settings_file() == (system / ".env").resolve()
    (system / ".env").write_text("MAILBOX_SERVICE_DATA_DIR=db\n", encoding="utf-8")
    assert load_settings().data_dir == system / "db"


def test_one_system_folder_for_both_gets_one_below_it_for_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As on Windows and macOS: a copy of the data never holds a key file
    from the config folder."""
    import platformdirs

    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(tmp_path))
    assert SYSTEM_FOLDERS() == (tmp_path / "config", tmp_path / "data")
    other = tmp_path / "share"
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(other))
    assert SYSTEM_FOLDERS() == (tmp_path, other)


def test_paths_names_the_folders_and_never_a_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = settings_folder(tmp_path, monkeypatch)
    with (folder / "service.env").open("a", encoding="utf-8") as file:
        file.write("MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID=client-1\n")
        file.write("MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET=s3cret-value\n")
    assert main(["paths", "--env-file", str(folder / "service.env")]) == 0
    out = capsys.readouterr().out
    assert "the file named on purpose" in out
    assert str((folder / "data" / "mailbox.db").resolve()) in out
    assert f"the key file {(folder / 'secrets' / 'master.key').resolve()}" in out
    assert "s3cret-value" not in out

    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    assert main(["paths"]) == 0
    out = capsys.readouterr().out
    system, _ = config.system_folders()
    assert "the folders of the operating system" in out
    assert "(not there, the defaults apply)" in out
    assert f"Suggested: {(system / 'master.key').resolve()}" in out


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
    parse = parser().parse_args
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

    from benethos_mailbox_service import assembly

    made: list[dict[str, object]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    monkeypatch.setattr(assembly, "create_app", lambda settings, **kw: made.append(kw))
    folder = settings_folder(tmp_path, monkeypatch)
    assert main(["serve", "--env-file", str(folder / "service.env")]) == 0
    assert made[-1]["settings_file"] == (folder / "service.env").resolve()
    assert main(["serve"]) == 0
    assert made[-1]["settings_file"] is None


def test_a_command_that_changes_the_database_logs_it_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The host prints to the person at the terminal and writes the same
    to the log (docs/LOGGING.md rule 6.8)."""
    folder = settings_folder(tmp_path, monkeypatch)
    named = str(folder / "service.env")
    with caplog.at_level("INFO"):
        assert main(["keys", "init", "--env-file", named]) == 0
        assert main(["backup", "copy.backup", "--env-file", named]) == 0
    said = [r.getMessage() for r in caplog.records if ".activity." in r.name]
    assert "the host created the master key and the data key" in said
    assert any(
        line.startswith("the host wrote a backup to copy.backup, schema ")
        for line in said
    )
