"""The service as a process of the script's own: its environment, its
start and its end."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from benethos_mailbox_service.data.secrets import cipher, encode_recovery


def program(name: str) -> str:
    """The console script ``name``, which ``uv run`` puts on the path."""
    command = shutil.which(name)
    if command is None:
        sys.exit(f"{name} not found: run this with uv run")
    return command


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def started(process: subprocess.Popen[bytes], url: str, what: str) -> None:
    """Returns once ``url`` answers, else ends the process and the script."""
    for _ in range(60):
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.TransportError:
            time.sleep(0.5)
    process.terminate()
    sys.exit(f"{what} did not start")


def stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    process.wait(timeout=10)


def service_env(
    data_dir: str, port: int, master_key: str | None = None
) -> dict[str, str]:
    """The environment of a service on ``port`` with SQLite in ``data_dir``,
    the master key in the environment, and no background sync. The service
    runs in ``data_dir`` (``run_dir``): the settings of the developer's
    config/ folder, such as a public URL or an OAuth app, stay out."""
    return {
        **os.environ,
        "MAILBOX_SERVICE_DATA_DIR": str(Path(data_dir).resolve()),
        "MAILBOX_SERVICE_STORAGE": "sqlite",
        "MAILBOX_SERVICE_KEY_PROVIDER": "env",
        "MAILBOX_SERVICE_MASTER_KEY": master_key or encode_recovery(cipher.new_key()),
        "MAILBOX_SERVICE_HOST": "127.0.0.1",
        "MAILBOX_SERVICE_PORT": str(port),
        "MAILBOX_SERVICE_SYNC_INTERVAL": "0",
        "MAILBOX_SERVICE_SYNC_IDLE": "false",
    }


def run_dir(env: dict[str, str]) -> str:
    """Where a service of a script runs: its data directory. Settings read
    config/benethos-mailbox-service/.env from the working directory, and
    there is none there."""
    folder = Path(env["MAILBOX_SERVICE_DATA_DIR"])
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def start_service(
    env: dict[str, str], url: str, init_keys: bool = True
) -> subprocess.Popen[bytes]:
    """``benethos-mailbox-service serve`` with ``env``, once it answers."""
    command = program("benethos-mailbox-service")
    if init_keys:
        subprocess.run(
            [command, "keys", "init"],
            env=env,
            cwd=run_dir(env),
            check=True,
            capture_output=True,
        )
    process = subprocess.Popen(
        [command, "serve"],
        env=env,
        cwd=run_dir(env),
        stdout=subprocess.DEVNULL,
        # Nobody reads it: a pipe would fill up and block the service.
        stderr=subprocess.DEVNULL,
    )
    started(process, f"{url}/health", "the service")
    return process
