"""The health check and the metrics."""

from __future__ import annotations

import asyncio
import socket
import sys
import urllib.request
from datetime import timedelta

import httpx
import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.runtime.health import check, window
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.runtime.metrics import Metrics

from ..agents_fake import FakeService, wire_message
from ..agents_helpers import Echo, Wired, configure, settings

MATCH = {"label": "match", "quote": "Your invoice"}


def test_the_window_is_three_polls_and_a_model_call() -> None:
    found = settings(poll_seconds=60, gateway_timeout_seconds=120)

    assert window(found) == timedelta(seconds=300)


async def test_healthy_while_the_loop_makes_progress(world: Wired) -> None:
    found = settings(poll_seconds=60, gateway_timeout_seconds=120)
    assert not check(world.store, found, world.clock()).healthy

    world.store.set_progress(world.clock())
    world.clock.advance(seconds=299)
    assert check(world.store, found, world.clock()).healthy

    world.clock.advance(seconds=2)
    late = check(world.store, found, world.clock())
    assert (late.healthy, late.reason) == (False, "last progress 301s ago")


def sample(metrics: Metrics, name: str, **labels: str) -> float | None:
    return metrics.registry.get_sample_value(name, labels)


async def test_a_pass_fills_the_metrics(world: Wired) -> None:
    worker = Worker(
        agent=Echo(settings(stage="keyword")),
        store=world.store,
        mailbox=world.mailbox,
        gateway=world.gateway,
        now=world.clock,
    )
    await worker.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.add(wire_message("m2", subject="Lunch"))
    world.service.add(wire_message("m3", subject="Hm"))
    world.fake_gateway.answer(
        MATCH,
        {"label": "match", "quote": "not in it"},
        {"label": "maybe", "quote": "x"},
    )

    await worker.run_pass()

    m = worker.metrics
    assert sample(m, "mailbox_agents_messages", state="done") == 1
    assert sample(m, "mailbox_agents_messages", state="decided") == 1
    assert sample(m, "mailbox_agents_messages", state="pending") == 1
    assert sample(m, "mailbox_agents_oldest_pending_age_seconds") == 0
    assert sample(m, "mailbox_agents_model_calls_total") == 2
    assert sample(m, "mailbox_agents_model_tokens_total", direction="in") == 240
    assert sample(m, "mailbox_agents_answers_refused_total", reason="evidence") == 1
    assert sample(m, "mailbox_agents_answers_refused_total", reason="schema") == 1
    assert (
        sample(m, "mailbox_agents_actions_total", action="add_keyword", executed="yes")
        == 1
    )
    assert (
        sample(m, "mailbox_agents_info", agent="echo", version="1", stage="keyword")
        == 1
    )
    assert b"mailbox_agents_last_pass_timestamp_seconds" in m.text()


async def test_an_upstream_away_is_counted(world: Wired) -> None:
    worker = Worker(
        agent=Echo(settings()),
        store=world.store,
        mailbox=world.mailbox,
        gateway=world.gateway,
        now=world.clock,
    )
    await worker.run_pass()
    world.service.add(wire_message("m1"))
    world.fake_gateway.answer(httpx.Response(503))

    await worker.run_pass()

    assert (
        sample(
            worker.metrics,
            "mailbox_agents_step_failures_total",
            kind="gateway_unavailable",
        )
        == 1
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def test_the_metrics_are_served() -> None:
    metrics = Metrics("echo", "1", "shadow")
    port = _free_port()
    with (
        metrics.serving(port, addr="127.0.0.1"),
        urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics") as answer,
    ):
        body = answer.read()

    assert b'mailbox_agents_info{agent="echo"' in body
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=1)


def test_a_port_taken_is_a_configuration_to_correct() -> None:
    with socket.socket() as taken:
        # The server of the metrics binds with SO_REUSEADDR, which on
        # Windows shares a port with another socket that did the same.
        if sys.platform == "win32":
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port: int = taken.getsockname()[1]
        with pytest.raises(ConfigError) as raised:
            with Metrics("echo", "1", "shadow").serving(port, addr="127.0.0.1"):
                pass

    assert raised.value.message.startswith(
        f"the metrics cannot be served on port {port} ("
    )
    assert raised.value.message.endswith("MAILBOX_AGENTS_METRICS_PORT")


def test_health_on_the_command_line(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    assert main(["health", "--agent", "counting"]) == 1
    assert "counting: unhealthy, no progress yet" in capsys.readouterr().out

    main(["run", "--agent", "counting"])
    assert main(["health", "--agent", "counting"]) == 0
    assert "counting: healthy" in capsys.readouterr().out

    monkeypatch.setenv("MAILBOX_AGENTS_POLL_SECONDS", "0.001")
    monkeypatch.setenv("MAILBOX_AGENTS_GATEWAY_TIMEOUT_SECONDS", "0.001")
    asyncio.run(asyncio.sleep(0.05))
    assert main(["health", "--agent", "counting"]) == 1


def test_the_worker_serves_metrics_while_it_runs(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    port = _free_port()
    monkeypatch.setenv("MAILBOX_AGENTS_METRICS_PORT", str(port))
    seen: list[bytes] = []

    async def one_pass(self: Worker, stop: asyncio.Event) -> None:
        await self.run_pass()
        url = f"http://127.0.0.1:{port}/metrics"
        with urllib.request.urlopen(url) as answer:
            seen.append(answer.read())

    monkeypatch.setattr(Worker, "run", one_pass)

    assert main(["worker", "--agent", "counting"]) == 0
    assert b"mailbox_agents_messages" in seen[0]
