"""How each kind of account is connected (UNIFORM U6): every kind has
its description, and a form needs nothing else."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.providers import CONNECTIONS, settings_defaults
from benethos_mailbox_service.data.providers.settings import trust_of
from benethos_mailbox_service.errors import BadRequestError


def test_every_kind_describes_its_connection() -> None:
    assert set(CONNECTIONS) == set(ProviderType)
    for kind, connection in CONNECTIONS.items():
        assert connection.kind == kind.value
        names = [field.name for field in connection.fields]
        assert len(names) == len(set(names)), kind


def test_one_set_up_by_hand_asks_for_its_server() -> None:
    for connection in CONNECTIONS.values():
        if connection.by_hand:
            [host] = [f for f in connection.fields if f.name == "host"]
            assert host.required and not connection.signs_in_at


def test_one_signed_in_elsewhere_has_no_fields() -> None:
    for connection in CONNECTIONS.values():
        if connection.signs_in_at:
            assert not connection.fields and not connection.by_hand


def test_a_described_setting_is_one_the_adapter_takes() -> None:
    """Each field names a setting its kind fills in by default or reads."""
    for kind in (ProviderType.IMAP, ProviderType.POP3, ProviderType.JMAP):
        defaults = settings_defaults(kind, "me@example.org")
        fields = {f.name for f in CONNECTIONS[kind].fields}
        assert set(defaults) <= fields | {"host"}, kind


def test_a_server_set_up_by_hand_takes_the_name_of_its_receiving_server() -> None:
    for kind in (ProviderType.IMAP, ProviderType.POP3, ProviderType.JMAP):
        names = {f.name for f in CONNECTIONS[kind].fields}
        assert "authserv_id" in names, kind
    for kind in (ProviderType.GMAIL, ProviderType.MICROSOFT):
        assert not CONNECTIONS[kind].fields


def test_the_names_of_the_receiving_server() -> None:
    assert trust_of({}) is None
    assert trust_of({"authserv_id": ""}) is None
    assert trust_of({"authserv_id": " , "}) is None
    found = trust_of({"authserv_id": " MX.Example.org , .example.net."})
    assert found is not None
    assert found.ids == ("mx.example.org", ".example.net")


@pytest.mark.parametrize(
    "value",
    ["mx example.org", "mx.exämple.org", "..example.org", "a_b.org", "-bad-.de", 7],
)
def test_a_name_that_is_no_host_is_refused(value: object) -> None:
    with pytest.raises(BadRequestError, match="settings.authserv_id must be"):
        trust_of({"authserv_id": value})
