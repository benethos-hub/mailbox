"""What an account can do, checked by the domain before its adapter is
asked (docs/UNIFORM.md, rules R2 to R4): the needs of each operation, the
answer for a lack, the abilities stored with the account and asked again
where the server contradicts them."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    Abilities,
    Account,
    Capability,
    Mark,
    MessageFilter,
    MessageUpdate,
    ProviderType,
)
from benethos_mailbox_service.domain.accounts import (
    NEEDS,
    Needs,
    for_delete,
    for_list,
    for_update,
)
from benethos_mailbox_service.domain.accounts.abilities import lacking
from benethos_mailbox_service.domain.accounts.adapters import RELEARN_PAUSE
from benethos_mailbox_service.errors import NotSupportedError

from ...conftest import memory_of, relearn

# --- what each operation needs ------------------------------------------------------


def test_each_field_of_a_change_needs_its_own() -> None:
    def needs(**change: object) -> set[Capability]:
        return set(for_update(MessageUpdate.model_validate(change)).capabilities)

    assert needs(unread=False) == {Capability.READ_STATE}
    assert needs(starred=True) == {Capability.STARS}
    assert needs(add_keywords=["work"]) == {Capability.KEYWORDS}
    assert needs(folder_ids=["a"]) == {Capability.MOVE}
    assert needs(folder_ids=["a", "b"]) == {Capability.MOVE, Capability.LABELS}
    assert needs(add_folder_ids=["a"]) == {Capability.MOVE, Capability.LABELS}


def test_a_mark_needs_to_be_written_not_keywords() -> None:
    needs = for_update(MessageUpdate(add_keywords=["$Answered"]))
    assert needs == Needs(marks=frozenset({Mark.ANSWERED}))
    # Another $ keyword is a keyword. A new list replaces the marks too.
    other = for_update(MessageUpdate(add_keywords=["$label1"]))
    assert other.capabilities == {Capability.KEYWORDS}
    replaced = for_update(MessageUpdate(keywords=["$junk"]))
    assert replaced == Needs(frozenset({Capability.KEYWORDS}), frozenset({Mark.JUNK}))


def test_deleting_and_listing() -> None:
    assert for_delete(False).capabilities == {Capability.TRASH}
    assert for_delete(True).capabilities == {Capability.PURGE}
    assert for_list(None) == for_list(MessageFilter()) == Needs()
    assert for_list(MessageFilter(unread=True)).capabilities == {Capability.SEARCH}


def test_the_table_names_operations_of_the_api(client: TestClient) -> None:
    operations = {
        operation["operationId"]
        for path in client.get("/openapi.json").json()["paths"].values()
        for operation in path.values()
    }
    assert set(NEEDS) <= operations


def test_a_lack_is_named() -> None:
    able = Abilities.of({Capability.STARS}, written={Mark.DRAFT})
    assert lacking(able, Needs(frozenset({Capability.STARS}))) is None
    refused = lacking(able, Needs(frozenset({Capability.MOVE, Capability.TRASH})))
    assert isinstance(refused, NotSupportedError)
    assert refused.message == "this account cannot move messages or delete into a trash"
    marked = lacking(able, Needs(marks=frozenset({Mark.JUNK})))
    assert marked is not None and "$junk" in marked.message


def test_what_is_written_is_read() -> None:
    able = Abilities.of({Capability.STARS}, read={Mark.DRAFT}, written={Mark.JUNK})
    assert (able.marks.read, able.marks.written) == (
        [Mark.DRAFT, Mark.JUNK],
        [Mark.JUNK],
    )


# --- the abilities of an account ------------------------------------------------------


def test_an_account_lacking_keywords_refuses_them(
    client: TestClient, services: Services, account_id: str
) -> None:
    memory_of(services, account_id).given = Abilities.of(
        {Capability.READ_STATE, Capability.STARS}
    )
    relearn(services, account_id)
    url = f"/v1/accounts/{account_id}/messages/m0"
    refused = client.patch(url, json={"starred": True, "add_keywords": ["work"]})
    assert refused.status_code == 501
    assert refused.json()["error"]["message"] == "this account cannot keep keywords"
    # Nothing changed, the star neither (R6).
    assert client.get(url).json()["starred"] is False
    assert client.patch(url, json={"starred": True}).status_code == 200


def test_an_account_connected_before_is_asked_once(
    client: TestClient, services: Services, account_id: str
) -> None:
    """Stored before schema 21: nothing is known until the server is asked,
    and the first operation that needs something asks it."""
    accounts = services.repositories.accounts
    record = accounts.get(account_id)
    settings = accounts.settings(account_id)
    accounts.delete(account_id)
    accounts.add(
        Account(id=record.id, provider=record.provider, email=record.email), settings
    )
    url = f"/v1/accounts/{account_id}"
    assert client.get(url).json()["capabilities"] == []
    starred = client.patch(f"{url}/messages/m0", json={"starred": True})
    assert starred.status_code == 200
    assert "stars" in client.get(url).json()["capabilities"]


async def test_a_contradiction_asks_the_server_again(
    services: Services, account_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The server refuses what the stored abilities let pass: they are
    asked again and the change is logged once."""
    adapters = services.adapters
    before = adapters.stored(account_id)
    assert before is not None and before.has(Capability.KEYWORDS)
    memory_of(services, account_id).given = Abilities.of({Capability.READ_STATE})

    async def refused(_: object) -> None:
        raise NotSupportedError("the server keeps no keywords any more")

    with caplog.at_level(logging.INFO), pytest.raises(NotSupportedError):
        await adapters.call(account_id, refused)
    after = adapters.stored(account_id)
    assert after is not None and after.capabilities == [Capability.READ_STATE]
    [line] = [
        r for r in caplog.records if r.name.endswith(".activity.accounts.capabilities")
    ]
    assert "-keywords" in line.getMessage()


async def test_refusals_ask_the_server_once_a_minute(
    services: Services, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that asks again and again for what the account cannot do
    makes no round trip to the server each time."""
    adapters = services.adapters
    now = [1000.0]
    monkeypatch.setattr(adapters, "_clock", lambda: now[0])
    asked: list[str] = []
    memory = memory_of(services, account_id)
    learn = memory.abilities

    async def counted() -> Abilities:
        asked.append(account_id)
        return await learn()

    monkeypatch.setattr(memory, "abilities", counted)

    async def refused(_: object) -> None:
        raise NotSupportedError("not here")

    for _ in range(3):
        with pytest.raises(NotSupportedError):
            await adapters.call(account_id, refused)
    assert len(asked) == 1
    now[0] += RELEARN_PAUSE
    with pytest.raises(NotSupportedError):
        await adapters.call(account_id, refused)
    assert len(asked) == 2


def test_verify_asks_the_server_again(
    client: TestClient, services: Services, account_id: str
) -> None:
    memory_of(services, account_id).given = Abilities.of(
        {Capability.SEARCH}, read={Mark.DRAFT}
    )
    verified = client.post(f"/v1/accounts/{account_id}/verify").json()
    assert verified["capabilities"] == ["search"]
    assert verified["marks"] == {"read": ["$draft"], "written": []}


def test_an_account_without_an_adapter_answers_what_is_stored(
    client: TestClient, services: Services
) -> None:
    """Its adapter cannot be built now, e.g. without the OAuth app of its
    provider: it answers what its server said before (decision 6.11)."""
    accounts = services.repositories.accounts
    accounts.add(
        Account(id="acc_gmail", provider=ProviderType.GMAIL, email="g@example.com")
    )
    accounts.set_abilities("acc_gmail", Abilities.of({Capability.LABELS}))
    found = client.get("/v1/accounts/acc_gmail").json()
    assert found["capabilities"] == ["labels"]
