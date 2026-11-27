"""The agent contract and the registry."""

from __future__ import annotations

import dataclasses
import importlib
import re
import textwrap
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.contract import (
    REVERSED_BY,
    Action,
    ActionRequest,
    Agent,
    Classifier,
    Context,
    Limits,
    Requires,
    Route,
    Trigger,
    discover,
    load_agent,
)
from benethos_mailbox_agents.errors import ContractError
from benethos_mailbox_agents.records import Decision, Event, FolderRef, MailMessage
from benethos_mailbox_agents.settings import Settings

from ..agents_helpers import DOCS, PACKAGE_DIR, ROOT


class Sample(Agent):
    name = "sample"
    version = "1"
    description = "an agent for the tests"
    triggers = Trigger(routes={"message.created": Route.DECIDE})
    actions = frozenset({Action.ADD_KEYWORD})
    default_keyword = "sample"

    def select(self, event: Event) -> Route | None:
        return Route.DECIDE

    def baseline(self, message: MailMessage) -> Decision:
        return Decision(label="other", source="baseline")

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        return Decision(label="other", source="model")

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        return []


def _variant(**attributes: Any) -> type[Agent]:
    return type("Variant", (Sample,), attributes)


def test_a_valid_agent_takes_its_keyword_from_the_settings() -> None:
    assert Sample(Settings()).keyword == "sample"
    assert Sample(Settings(keyword="mine")).keyword == "mine"


async def test_the_defaults_of_the_optional_methods() -> None:
    agent = Sample(Settings())
    message = MailMessage.model_validate(
        {"ref": {"account_id": "a", "message_id": "m"}}
    )
    context: Any = None

    folder = FolderRef(id="f", name="Folder", role=None, path="Folder")

    assert agent.admit(message)
    assert await agent.observe(message, context) == []
    assert await agent.tick(datetime(2026, 11, 19, tzinfo=UTC), context) == []
    assert agent.prepare() is None
    assert agent.summarize([]) == []
    assert agent.backfill_folder(folder) is False
    assert agent.folders_needed() == ()
    assert agent.describe_folders({"Folder": folder}) == []
    assert agent.may_create("Folder/Sub", {"Folder": folder}) is False
    assert agent.skip_marked is False
    assert agent.report_labels == frozenset()
    assert agent.report_fields == frozenset()


@pytest.mark.parametrize(
    ("attributes", "complaint"),
    [
        ({"name": "Not-Valid"}, "lowercase"),
        ({"version": ""}, "must not be empty"),
        (
            {"triggers": Trigger(routes={"message.read": Route.DECIDE})},
            "unknown events",
        ),
        ({"triggers": Trigger(routes={})}, "no event and no tick"),
        ({"actions": {Action.ADD_KEYWORD}}, "actions"),
        ({"actions": frozenset({"delete"})}, "actions"),
        ({"limits": Limits(model_calls_per_message=-1)}, "negative"),
        ({"requires": Requires(settings=("no_such",))}, "unknown settings"),
        ({"default_keyword": "two words"}, "one word"),
        ({"default_keyword": "$Junk"}, "one word"),
        ({"default_keyword": "Agent-X"}, "one word"),
        ({"default_keyword": "a" + chr(1) + "b"}, "one word"),
    ],
)
def test_a_wrong_declaration_is_refused(
    attributes: dict[str, Any], complaint: str
) -> None:
    with pytest.raises(ContractError, match=complaint):
        _variant(**attributes)(Settings())


def test_a_missing_declaration_is_named() -> None:
    class Bare(Agent):
        def select(self, event: Event) -> Route | None:
            return None

        def baseline(self, message: MailMessage) -> Decision:
            raise NotImplementedError

        async def decide(self, message: MailMessage, context: Context) -> Decision:
            raise NotImplementedError

        async def effect(
            self, decision: Decision, message: MailMessage, context: Context
        ) -> list[ActionRequest]:
            raise NotImplementedError

    with pytest.raises(ContractError, match="name must be declared"):
        Bare(Settings())


def test_every_action_has_a_way_back() -> None:
    assert set(REVERSED_BY) == set(Action)
    # Only a folder made and a forward drafted are taken back by the owner,
    # not by an agent.
    assert [a for a, back in REVERSED_BY.items() if back is None] == [
        Action.CREATE_FOLDER,
        Action.DRAFT_FORWARD,
    ]


def test_the_actions_of_the_contract_spec_are_the_code() -> None:
    section = (DOCS / "concept" / "agent-contract.md").read_text("utf-8")
    table = section[section.index("| Action |") :]
    named = re.findall(r"^\| `([a-z_]+)` \|", table, flags=re.MULTILINE)

    assert set(named) == {action.value for action in Action}


AGENT_SOURCE = """
from benethos_mailbox_agents.contract import Action, Agent, Classifier, Route, Trigger
from benethos_mailbox_agents.records import Decision


class {cls}(Classifier):
    name = "{name}"
    version = "1"
    description = "found by the registry"
    triggers = Trigger(routes={{}}, tick=True)
    actions = frozenset({{Action.ADD_KEYWORD}})
    default_keyword = "x"

    def select(self, event):
        return None

    def baseline(self, message):
        return Decision(label="x", source="baseline")

    async def decide(self, message, context):
        return Decision(label="x", source="model")

    async def effect(self, decision, message, context):
        return []
"""


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A package of agents in a temporary folder, importable by its name."""
    package_name = f"fake_agents_{uuid.uuid4().hex}"
    root = tmp_path / package_name
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    for name in ("beta", "alpha"):
        (root / name).mkdir()
        (root / name / "__init__.py").write_text("", encoding="utf-8")
        (root / name / "agent.py").write_text(
            AGENT_SOURCE.format(cls=name.title(), name=name), encoding="utf-8"
        )
    (root / "_private").mkdir()
    (root / "half").mkdir()
    (root / "half" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    return package_name


def test_the_registry_finds_every_agent_by_name(package: str) -> None:
    assert list(discover(package)) == ["alpha", "beta"]
    assert load_agent("beta", package).name == "beta"


def test_an_unknown_agent_names_those_there_are(package: str) -> None:
    with pytest.raises(ContractError, match="there are: alpha, beta"):
        load_agent("gamma", package)


def test_a_module_with_two_agents_is_refused(
    package: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AGENT_SOURCE.format(cls="One", name="two")
    source += textwrap.dedent(AGENT_SOURCE.format(cls="Two", name="two"))
    (tmp_path / package / "two").mkdir()
    (tmp_path / package / "two" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / package / "two" / "agent.py").write_text(source, encoding="utf-8")

    importlib.invalidate_caches()

    with pytest.raises(ContractError, match="defines 2 agent classes"):
        discover(package)


def test_an_agent_neither_classifier_nor_actor_is_refused(
    package: str, tmp_path: Path
) -> None:
    source = AGENT_SOURCE.format(cls="Reader", name="reader")
    source = source.replace("class Reader(Classifier):", "class Reader(Agent):")
    (tmp_path / package / "reader").mkdir()
    (tmp_path / package / "reader" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / package / "reader" / "agent.py").write_text(source, encoding="utf-8")

    importlib.invalidate_caches()

    with pytest.raises(ContractError, match="a Classifier or an Actor"):
        discover(package)


def test_a_name_unlike_its_package_is_refused(package: str, tmp_path: Path) -> None:
    (tmp_path / package / "gamma").mkdir()
    (tmp_path / package / "gamma" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / package / "gamma" / "agent.py").write_text(
        AGENT_SOURCE.format(cls="Gamma", name="delta"), encoding="utf-8"
    )

    importlib.invalidate_caches()

    with pytest.raises(ContractError, match="differs from its package"):
        discover(package)


def test_sample_has_no_tick_by_default() -> None:
    assert Sample.triggers.tick is False
    assert isinstance(Sample.actions, frozenset)


# -- the tables of docs/mailbox-agents/concept/agent-contract.md against the code ------

CONTRACT = DOCS / "concept" / "agent-contract.md"


def _table(header: str) -> list[list[str]]:
    """The rows of the table of agent-contract.md whose header row starts
    with ``header``, each as its cells."""
    lines = CONTRACT.read_text("utf-8").splitlines()
    start = next(n for n, line in enumerate(lines) if line.startswith(header))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def _names(cell: str) -> list[str]:
    """The names in backticks of a cell, a call reduced to its name."""
    return [name.partition("(")[0] for name in re.findall(r"`([^`]+)`", cell)]


# Provided by the base class for the registry, not a part an agent writes.
PROVIDED = {"validate_definition"}


def test_the_attribute_table_names_every_attribute_of_an_agent() -> None:
    named = {name for row in _table("| Attribute |") for name in _names(row[0])}

    declared = {name for name in Agent.__annotations__ if not name.startswith("_")}
    assert named == declared


def test_the_method_table_names_every_method_of_an_agent() -> None:
    named = {name for row in _table("| Method |") for name in _names(row[0])}

    methods = {
        name
        for name, value in vars(Agent).items()
        if not name.startswith("_") and callable(getattr(Agent, name))
    }
    assert named == methods - PROVIDED


def test_the_keyword_table_is_each_agents_default() -> None:
    table = {
        _names(row[0])[0]: _names(row[1])[0] for row in _table("| Agent | Keyword |")
    }

    assert table == {name: cls.default_keyword for name, cls in discover().items()}


def test_the_skip_marked_table_is_what_each_agent_declares() -> None:
    table = {_names(row[0])[0]: row[1] for row in _table("| Agent | `skip_marked` |")}

    assert table == {
        name: "on" if cls.skip_marked else "off" for name, cls in discover().items()
    }


@pytest.mark.parametrize("name", sorted(discover()))
def test_each_agent_has_its_spec_and_its_settings_for_operation(name: str) -> None:
    assert (DOCS / "concept" / f"agent-{name.replace('_', '-')}.md").is_file()
    assert (
        ROOT
        / "containers"
        / "production"
        / "mailbox-agents"
        / "agents"
        / name
        / ".env.example"
    ).is_file()


def _of_one_agent() -> list[tuple[Path, str]]:
    """Each test file of one agent, in tests/agents/<name>/ as its source is
    in agents/<name>/, with the agent. A test of all agents, such as
    test_agent_schemas.py beside the folders, is none."""
    agents = set(discover())
    return [
        (path, path.parent.name)
        for path in sorted((PACKAGE_DIR / "tests" / "agents").glob("*/test_*.py"))
        if path.parent.name in agents
    ]


OF_ONE_AGENT = _of_one_agent()


@pytest.mark.parametrize(
    ("path", "own"), OF_ONE_AGENT, ids=[p.name for p, _ in OF_ONE_AGENT]
)
def test_the_tests_of_one_agent_import_no_other_agent(path: Path, own: str) -> None:
    """A rule for all agents goes to a test of its own, such as
    test_agent_schemas.py. Only test_agents_together.py brings several
    agents together."""
    found = set(
        re.findall(r"benethos_mailbox_agents\.agents\.(\w+)", path.read_text("utf-8"))
    )

    assert found <= {own}


def test_every_test_of_an_agent_is_found() -> None:
    assert len(OF_ONE_AGENT) >= len(discover())


def test_the_context_holds_what_the_spec_names() -> None:
    names = [field.name for field in dataclasses.fields(Context)]

    assert names == ["model", "reader", "items", "now"]


@pytest.mark.parametrize(
    "name", ["awaiting_reply", "categorization", "counting", "inquiries"]
)
def test_the_agents_that_read_mail_are_classifiers(name: str) -> None:
    assert issubclass(discover()[name], Classifier)


def test_a_recognizer_scored_alone_is_a_classifier() -> None:
    from benethos_mailbox_agents.agents.categorization.alone import InvoiceAlone

    assert issubclass(InvoiceAlone, Classifier)


def test_a_classifier_drafts_no_forward() -> None:
    from benethos_mailbox_agents.agents.counting.agent import Counting

    class Forwarding(Counting):
        actions = frozenset({Action.DRAFT_FORWARD})

    with pytest.raises(ContractError, match="a classifier drafts no forward"):
        Forwarding.validate_definition()


def test_an_agent_names_no_recipient_by_default() -> None:
    from benethos_mailbox_agents.agents.counting.agent import Counting

    assert Counting(Settings()).recipients() == frozenset()
