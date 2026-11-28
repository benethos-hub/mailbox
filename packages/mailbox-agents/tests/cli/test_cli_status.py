"""The command status: the folders that matter to each agent, in each
account, and why they were not checked."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest

from benethos_mailbox_agents.agents.categorization import agent as categorization_agent
from benethos_mailbox_agents.agents.categorization.lists import Listed
from benethos_mailbox_agents.cli import main, status
from benethos_mailbox_agents.records import FolderRef
from benethos_mailbox_agents.settings import PREFIX

from ..agents_fake import FakeService
from ..agents_helpers import Echo, configure


class Watching(Echo):
    """An agent that expects the folders of ``needed`` and says it looks in
    each folder below Invoices: what status says of an agent's folders."""

    needed: tuple[str, ...] = ()

    def folders_needed(self) -> tuple[str, ...]:
        return self.needed

    def describe_folders(self, folders: Mapping[str, FolderRef]) -> list[str]:
        return [
            f"{path}: looked in"
            for path in sorted(folders)
            if path.startswith("Invoices/")
        ]


def watching(monkeypatch: pytest.MonkeyPatch, *needed: str) -> None:
    """Status lists this agent alone, expecting ``needed``."""
    agent = type("Watched", (Watching,), {"needed": needed})
    monkeypatch.setattr(status, "discover", lambda: {"echo": agent})


def test_status_names_a_folder_that_is_missing(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}ACCOUNTS", "acc1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "Invoices", "Missing")

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "  folder missing in acc1: Missing\n" in out
    assert "folder missing in acc1: Invoices\n" not in out


def test_status_lists_the_folders_that_matter(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}ACCOUNTS", "acc1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "Invoices")
    service.folders["acc1"].append(
        {"id": "hz-re", "name": "Rechnungen", "role": None, "parent_id": "inv-hosting"}
    )

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert (
        "  folders in acc1:\n"
        "    Invoices/CloudHost: looked in\n"
        "    Invoices/Hosting: looked in\n"
        "    Invoices/Hosting/Rechnungen: looked in\n"
        "    Invoices/Telco: looked in\n"
        "    Invoices/mo: looked in\n"
    ) in out
    assert "Trash" not in out and "Sent" not in out


def test_status_writes_a_control_character_of_a_folder_escaped(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}ACCOUNTS", "acc1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "Invoices")
    clear = chr(27) + "[2J"
    service.folders["acc1"].append(
        {"id": "x", "name": f"Odd{clear}", "role": None, "parent_id": "inv"}
    )

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert chr(27) not in out
    assert "    Invoices/Odd" + "\\x1b[2J: looked in" in out


def test_status_names_a_folder_there_in_another_case(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}ACCOUNTS", "acc1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "invoices")

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "  folder in another case in acc1: invoices\n" in out
    assert "folder missing in acc1: invoices" not in out


def test_status_reads_the_categorization_list_once(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    listed = tmp_path / "categorization.json"
    listed.write_text(
        '{"groups": [{"name": "A", "folder": "A", "senders": ["*@a.example"]}]}',
        encoding="utf-8",
    )
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}ACCOUNTS", "acc1")
    monkeypatch.setenv(f"{PREFIX}CATEGORIZATION_FILE", str(listed))
    reads: list[Path] = []
    real = categorization_agent.load_chain

    def counted(path: Path) -> Listed:
        reads.append(path)
        return real(path)

    monkeypatch.setattr(categorization_agent, "load_chain", counted)

    assert main(["status"]) == 0

    assert "categorization 3: ready" in capsys.readouterr().out
    assert reads == [listed]


def test_status_without_accounts_checks_every_granted_account(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "Invoices", "Missing")
    service.folders["acc2"] = [{"id": "inbox", "name": "INBOX", "role": "inbox"}]

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "  folder missing in acc1: Missing\n" in out
    assert "folder missing in acc1: Invoices\n" not in out
    assert "  folder missing in acc2: Invoices\n" in out
    assert "  folder missing in acc2: Missing\n" in out
    assert "folders not checked" not in out
    assert any(r.url.path == "/v1/me" for r in service.requests)


def test_status_says_when_no_account_is_granted(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "Invoices")
    service.folders.clear()

    assert main(["status"]) == 0
    assert "  folders not checked: no account is granted" in capsys.readouterr().out


def test_status_lists_the_folders_of_an_account_beside_one_refused(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}ACCOUNTS", "acc1,acc2")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "Invoices")
    listed = service._folders

    def folders(request: httpx.Request, parts: list[str]) -> httpx.Response:
        if parts[1] == "acc2":
            return httpx.Response(
                403, json={"error": {"code": "forbidden", "message": "refused"}}
            )
        return listed(request, parts)

    monkeypatch.setattr(service, "_folders", folders)

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "  folders in acc1:\n" in out
    assert "  folders not checked in acc2: " in out
    assert "folders not checked: " not in out


def test_status_says_why_folders_were_not_checked(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    watching(monkeypatch, "Invoices")
    service.down = True

    assert main(["status"]) == 0
    assert "  folders not checked: the mailbox service" in capsys.readouterr().out

    monkeypatch.setenv(f"{PREFIX}ACCOUNTS", "acc1")

    assert main(["status"]) == 0
    assert (
        "  folders not checked in acc1: the mailbox service" in capsys.readouterr().out
    )
