"""Where the agents read their settings and keep their state files: the
file named on purpose, the layout of the repository, the folders of the
operating system. Every folder is one of the test's."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_agents.settings import (
    DATA_DIR,
    DEFAULT_ENV_FILE,
    PREFIX,
    folders,
    load_settings,
)
from benethos_mailbox_common.paths import folders as system


@pytest.fixture
def elsewhere(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A working directory without the layout of the repository."""
    here = tmp_path / "work"
    here.mkdir()
    monkeypatch.chdir(here)
    return here


def test_the_layout_of_the_repository_keeps_the_state_in_its_folder(
    elsewhere: Path,
) -> None:
    (elsewhere / DEFAULT_ENV_FILE.parent).mkdir(parents=True)

    found = load_settings()

    assert folders().origin == "working directory"
    assert found.data_dir == DATA_DIR == Path("data") / "benethos-mailbox-agents"


def test_a_relative_path_counts_from_the_named_file(
    elsewhere: Path, tmp_path: Path
) -> None:
    other = tmp_path / "x"
    other.mkdir()
    (other / "token").write_text("service-token-value\n", encoding="utf-8")
    env = other / "agents.env"
    env.write_text(
        f"{PREFIX}DATA_DIR=data\n"
        f"{PREFIX}SORTING_FILE=s.json\n"
        f"{PREFIX}SERVICE_TOKEN_FILE=token\n"
        f"{PREFIX}OTLP_HEADERS_FILE=otlp.headers\n",
        encoding="utf-8",
    )

    found = load_settings(env)

    assert found.data_dir == other / "data"
    assert found.sorting_file == other / "s.json"
    assert found.otlp_headers_file == other / "otlp.headers"
    assert found.secret("service_token") == "service-token-value"


def test_the_variable_names_the_file_as_the_option_does(
    elsewhere: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / "named.env"
    env.write_text(f"{PREFIX}STAGE=keyword\n", encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}ENV_FILE", str(env))

    found = load_settings()

    assert found.stage == "keyword"
    assert found.data_dir == tmp_path / DATA_DIR


def test_an_absolute_path_stays_as_it_is(elsewhere: Path, tmp_path: Path) -> None:
    data = tmp_path / "state"
    env = tmp_path / "agents.env"
    env.write_text(f"{PREFIX}DATA_DIR={data}\n", encoding="utf-8")

    assert load_settings(env).data_dir == data


def test_a_path_given_in_code_is_left_as_given(elsewhere: Path, tmp_path: Path) -> None:
    env = tmp_path / "agents.env"
    env.write_text(f"{PREFIX}DATA_DIR=data\n", encoding="utf-8")

    assert load_settings(env, data_dir=Path("mine")).data_dir == Path("mine")


def test_without_the_layout_the_folders_of_the_system_are_taken(
    elsewhere: Path,
) -> None:
    system_data = system.system_folders("benethos-mailbox-agents").data

    assert folders().origin == "system"
    assert load_settings().data_dir == system_data
