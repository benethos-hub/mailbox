"""How each kind of account is connected (UNIFORM U6): every kind has
its description, and a form needs nothing else."""

from __future__ import annotations

from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.providers import CONNECTIONS, settings_defaults


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
