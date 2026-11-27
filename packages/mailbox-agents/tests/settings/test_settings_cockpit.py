"""The settings of the cockpit."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_agents import errors
from benethos_mailbox_agents.settings import PREFIX, load_settings
from benethos_mailbox_common.log import redact


def test_the_cockpit_serves_this_machine_by_default() -> None:
    found = load_settings()

    assert (found.cockpit_host, found.cockpit_port) == ("127.0.0.1", 9480)
    assert found.cockpit_secret is None


def test_the_secret_of_the_cockpit_comes_from_a_file_and_is_masked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "cockpit_secret"
    secret.write_text("cockpit-secret-value\n", encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}COCKPIT_SECRET_FILE", str(secret))

    assert load_settings().secret("cockpit_secret") == "cockpit-secret-value"
    assert redact.redact("x cockpit-secret-value") == "x ***"


def test_an_empty_secret_of_the_cockpit_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(f"{PREFIX}COCKPIT_SECRET", "")
    monkeypatch.setenv(f"{PREFIX}COCKPIT_SECRET_FILE", "")

    found = load_settings()

    assert (found.cockpit_secret, found.cockpit_secret_file) == (None, None)
    with pytest.raises(errors.ConfigError, match=f"{PREFIX}COCKPIT_SECRET is not"):
        found.secret("cockpit_secret")


def test_a_secret_of_the_cockpit_that_is_not_printable_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(f"{PREFIX}COCKPIT_SECRET", "secret\x07value")

    with pytest.raises(errors.ConfigError) as raised:
        load_settings()

    assert "COCKPIT_SECRET holds a character that is not printable ASCII" in (
        raised.value.message
    )
    assert "value" not in raised.value.message


@pytest.mark.parametrize("port", ["-1", "65536"])
def test_a_port_of_the_cockpit_out_of_range_is_refused(
    monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    monkeypatch.setenv(f"{PREFIX}COCKPIT_PORT", port)

    with pytest.raises(errors.ConfigError, match="cockpit_port|COCKPIT_PORT"):
        load_settings()
