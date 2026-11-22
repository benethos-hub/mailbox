"""Settings: prefix, .env, secrets from files, and the table of
docs/mailbox-agents/concept/configuration.md."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_agents import errors
from benethos_mailbox_agents.settings import PREFIX, Settings, load_settings

from ..agents_helpers import DOCS, PACKAGE_DIR, ROOT


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No setting of the machine, and no default .env, reaches a test."""
    import os

    for name in list(os.environ):
        if name.startswith(PREFIX):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    errors.forget_secrets()
    yield
    errors.forget_secrets()


def test_the_defaults() -> None:
    found = load_settings()

    assert found.stage == "shadow"
    assert found.accounts == []
    assert found.prompt_retention_days == 0
    assert found.reply_days == 3
    assert found.data_dir == Path("data")


def test_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_AGENTS_STAGE", "keyword")
    monkeypatch.setenv("MAILBOX_AGENTS_ACCOUNTS", "acc1, acc2,")
    monkeypatch.setenv("MAILBOX_AGENTS_LOG_LEVEL", "debug")

    found = load_settings()

    assert found.stage == "keyword"
    assert found.accounts == ["acc1", "acc2"]
    assert found.log_level == "DEBUG"


def test_from_a_named_env_file(tmp_path: Path) -> None:
    env = tmp_path / "agent.env"
    env.write_text("MAILBOX_AGENTS_MODEL=classifier\n", encoding="utf-8")

    assert load_settings(env).model == "classifier"


def test_the_default_env_file_is_read_when_it_exists(tmp_path: Path) -> None:
    folder = tmp_path / "config" / "benethos-mailbox-agents"
    folder.mkdir(parents=True)
    (folder / ".env").write_text("MAILBOX_AGENTS_POLL_SECONDS=5\n", encoding="utf-8")

    assert load_settings().poll_seconds == 5


def test_a_named_env_file_must_exist(tmp_path: Path) -> None:
    with pytest.raises(errors.ConfigError, match="does not exist"):
        load_settings(tmp_path / "missing.env")


def test_a_secret_from_a_file_is_read_and_registered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "token"
    secret.write_text("service-token-value\n", encoding="utf-8")
    monkeypatch.setenv("MAILBOX_AGENTS_SERVICE_TOKEN_FILE", str(secret))

    found = load_settings()

    assert found.secret("service_token") == "service-token-value"
    assert errors.redact("x service-token-value") == "x [redacted]"


def test_a_secret_given_directly_wins_over_its_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_KEY", "direct-key-value")
    monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_KEY_FILE", str(tmp_path / "none"))

    assert load_settings().secret("gateway_key") == "direct-key-value"


def test_an_empty_secret_lets_its_file_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "service_token"
    secret.write_text("from-the-file\n", encoding="utf-8")
    monkeypatch.setenv("MAILBOX_AGENTS_SERVICE_TOKEN", "")
    monkeypatch.setenv("MAILBOX_AGENTS_SERVICE_TOKEN_FILE", str(secret))
    monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_KEY", "")

    found = load_settings(None)

    assert found.secret("service_token") == "from-the-file"
    assert found.gateway_key is None
    assert found.missing(("gateway_key",)) == ["MAILBOX_AGENTS_GATEWAY_KEY"]


@pytest.mark.parametrize(
    "name",
    [
        "keyword",
        "ca_file",
        "sorting_file",
        "inquiries_patterns_file",
        "service_token_file",
        "gateway_key_file",
    ],
)
def test_an_empty_line_is_not_set(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(f"{PREFIX}{name.upper()}", "")

    assert getattr(load_settings(), name) is None


def test_an_unreadable_secret_file_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_KEY_FILE", str(tmp_path / "none"))

    with pytest.raises(errors.ConfigError, match="GATEWAY_KEY_FILE"):
        load_settings()


def test_a_secret_file_with_the_mark_of_utf8_is_read_without_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "token"
    secret.write_text("﻿service-token-value\r\n", encoding="utf-8")
    monkeypatch.setenv("MAILBOX_AGENTS_SERVICE_TOKEN_FILE", str(secret))

    assert load_settings().secret("service_token") == "service-token-value"


@pytest.mark.parametrize("value", ["tokén-value", "token\x07value"])
@pytest.mark.parametrize("from_file", [False, True])
def test_a_secret_that_is_not_printable_ascii_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str, from_file: bool
) -> None:
    if from_file:
        secret = tmp_path / "key"
        secret.write_text(value, encoding="utf-8")
        monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_KEY_FILE", str(secret))
    else:
        monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_KEY", value)

    with pytest.raises(errors.ConfigError) as raised:
        load_settings()

    named = "GATEWAY_KEY_FILE" if from_file else "GATEWAY_KEY holds"
    assert named in raised.value.message
    assert "not printable ASCII" in raised.value.message
    assert "value" not in raised.value.message


def test_a_secret_file_that_is_no_utf8_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "key"
    secret.write_bytes(b"key-\xe9-value")
    monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_KEY_FILE", str(secret))

    with pytest.raises(errors.ConfigError) as raised:
        load_settings()

    assert "GATEWAY_KEY_FILE cannot be read (UnicodeDecodeError)" in (
        raised.value.message
    )
    assert "value" not in raised.value.message


def test_a_missing_secret_is_named() -> None:
    with pytest.raises(errors.ConfigError, match="MAILBOX_AGENTS_SERVICE_TOKEN"):
        load_settings().secret("service_token")


def test_a_wrong_value_is_named_never_quoted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_AGENTS_STAGE", "everything-now")

    with pytest.raises(errors.ConfigError) as raised:
        load_settings()

    assert "MAILBOX_AGENTS_STAGE" in str(raised.value)
    assert "everything-now" not in str(raised.value)


@pytest.mark.parametrize(
    "keyword",
    ["two words", "(x)", 'q"', "$Junk", "Agent-X", "a" + chr(1) + "b", "-x"],
)
def test_a_keyword_is_lower_case_letters_digits_and_dashes(keyword: str) -> None:
    with pytest.raises(errors.ConfigError, match="KEYWORD") as raised:
        load_settings(keyword=keyword)

    assert "Junk" not in str(raised.value)


@pytest.mark.parametrize("keyword", ["agent-invoice", "agent-2", "x"])
def test_a_keyword_of_that_form_passes(keyword: str) -> None:
    assert load_settings(keyword=keyword).keyword == keyword


def test_missing_names_the_unset_settings() -> None:
    found = load_settings(model="m")

    assert found.missing(("model", "service_url")) == ["MAILBOX_AGENTS_SERVICE_URL"]


def _configuration_spec() -> str:
    return (DOCS / "concept" / "configuration.md").read_text("utf-8")


def test_every_setting_of_the_configuration_spec_exists() -> None:
    """The table of docs/mailbox-agents/concept/configuration.md against the code."""
    rows = [
        line for line in _configuration_spec().splitlines() if line.startswith("| `")
    ]
    names = {
        name.lower()
        for row in rows
        for name in re.findall(r"`([A-Z_]+)`", row.split("|")[1])
    }

    assert names
    assert names <= set(Settings.model_fields)


def test_the_env_example_names_every_setting() -> None:
    example = ROOT / "config" / "benethos-mailbox-agents" / ".env.example"
    named = set(re.findall(r"MAILBOX_AGENTS_([A-Z_]+)=", example.read_text("utf-8")))

    assert {name.lower() for name in named} == set(Settings.model_fields)


TEST_CA = PACKAGE_DIR / "tests" / "data" / "test-ca.pem"


def test_a_ca_file_is_the_one_authority_trusted() -> None:
    context = load_settings(ca_file=TEST_CA).ssl_context()

    assert context is not None
    names = [dict(n[0] for n in c["subject"]) for c in context.get_ca_certs()]
    assert names == [{"commonName": "mailbox-agents test CA"}]


def test_without_a_ca_file_the_roots_stay() -> None:
    assert load_settings().ssl_context() is None
    assert load_settings(ca_file="").ca_file is None


@pytest.mark.parametrize("name", ["missing.pem", "no-certificate.pem"])
def test_a_ca_file_that_is_no_ca_stops_the_start(tmp_path: Path, name: str) -> None:
    (tmp_path / "no-certificate.pem").write_text("no certificate\n", encoding="utf-8")

    with pytest.raises(errors.ConfigError, match="MAILBOX_AGENTS_CA_FILE"):
        load_settings(ca_file=tmp_path / name)
