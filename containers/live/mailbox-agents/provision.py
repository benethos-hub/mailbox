"""Provisions the live setup, called by setup.sh. Standard library only.

1. Stalwart: the bootstrap (host name, domain, no ACME, no DKIM), a
   restart out of bootstrap mode, the test certificate, and the account
   ``agents@agents.test``.
2. The invented mail, appended over IMAP with the test CA: see mail.py.
3. The model gateway: a key for the agents, made with the master key, for
   the aliases of AGENT_MODELS only and within AGENT_BUDGET_USD.
4. The mailbox service: the administrator's password set through the UI
   and a token made there, the account connected, a user ``agents`` with
   mail.read and mail.write on it, and that user's token. The same step
   writes ``secrets/agent.env``: the settings the agents and agents_smoke.py
   read, the model gateway, the agents' key and its alias among them.

Every secret goes to a file under ``secrets/``, none to the terminal.
"""

from __future__ import annotations

import base64
import http.cookiejar
import imaplib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mail

STALWART = os.environ["STALWART_URL"]
SERVICE = os.environ["SERVICE_URL"]
SECRETS = Path(os.environ["SECRETS"])
# The compose file comes from COMPOSE_FILE, which setup.sh exports.
COMPOSE = ["docker", "compose"]
DOMAIN = "agents.test"
HOST = "mail.agents.test"
ADDRESS = f"agents@{DOMAIN}"
# The aliases of litellm.yaml the agents' key may call, and what it may
# spend: the master key reaches every alias, Claude Opus included, on the
# owner's Claude API key, with no budget. The master key stays in
# secrets/gateway.env.
AGENT_MODELS = ["mail-classifier", "mail-classifier-gpu", "mail-classifier-cpu"]
AGENT_BUDGET_USD = 5.0


def say(text: str) -> None:
    print(f"provision: {text}", file=sys.stderr)


def wait_for(url: str, seconds: float = 90) -> None:
    end = time.monotonic() + seconds
    while True:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except urllib.error.HTTPError:
            return
        except OSError:
            if time.monotonic() > end:
                raise SystemExit(f"provision: {url} does not answer") from None
            time.sleep(1)


# -- Stalwart over JMAP ----------------------------------------------------------


def jmap(user: str, password: str, *calls: list) -> list:
    body = json.dumps(
        {
            "using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
            "methodCalls": list(calls),
        }
    ).encode()
    request = urllib.request.Request(f"{STALWART}/jmap/", body, method="POST")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as answer:
        found = json.load(answer)["methodResponses"]
    for name, result, _ in found:
        if name == "error" or result.get("notCreated") or result.get("notUpdated"):
            raise SystemExit(
                f"provision: Stalwart refused {name}: {json.dumps(result)[:600]}"
            )
    return found


def stalwart() -> str:
    """Set Stalwart up. Answers the account's password."""
    wait_for(f"{STALWART}/jmap/session")
    say("Stalwart bootstrap")
    ((_, result, _),) = jmap(
        "admin",
        os.environ["STALWART_BOOTSTRAP_PASSWORD"],
        [
            "x:Bootstrap/set",
            {
                "update": {
                    "singleton": {
                        "defaultHostname": HOST,
                        "defaultDomain": DOMAIN,
                        "requestTlsCertificate": False,
                        "generateDkimKeys": False,
                    }
                }
            },
            "0",
        ],
    )
    admin = result["updated"]["singleton"]
    user, password = admin["username"], admin["secret"]
    (SECRETS / "stalwart-admin").write_text(f"{user}:{password}\n", encoding="utf-8")

    say("Stalwart out of bootstrap mode")
    subprocess.run(
        [*COMPOSE, "up", "-d", "--force-recreate", "stalwart"],
        check=True,
        env={**os.environ, "STALWART_RECOVERY_ADMIN": ""},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    wait_for(f"{STALWART}/jmap/session")

    say("the certificate and the account")
    tls = SECRETS / "tls"
    found = jmap(user, password, ["x:Domain/get", {"ids": None}, "d"])
    domain_id = next(d["id"] for d in found[0][1]["list"] if d["name"] == DOMAIN)
    mailbox_password = os.environ["MAILBOX_PASSWORD"]
    jmap(
        user,
        password,
        [
            "x:Certificate/set",
            {
                "create": {
                    "test": {
                        "certificate": {
                            "@type": "Text",
                            "value": (tls / "server.pem").read_text(encoding="utf-8"),
                        },
                        "privateKey": {
                            "@type": "Text",
                            "secret": (tls / "server.key").read_text(encoding="utf-8"),
                        },
                    }
                }
            },
            "c",
        ],
        [
            "x:Account/set",
            {
                "create": {
                    "agents": {
                        "@type": "User",
                        "name": "agents",
                        "domainId": domain_id,
                        "description": "made for the agents, invented mail only",
                        "credentials": {
                            "0": {"@type": "Password", "secret": mailbox_password}
                        },
                        "roles": {"@type": "User"},
                        "permissions": {"@type": "Inherit"},
                        "quotas": {},
                        "aliases": {},
                    }
                }
            },
            "a",
        ],
    )
    say("Stalwart restarted to take the certificate")
    subprocess.run(
        [*COMPOSE, "restart", "stalwart"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    wait_for(f"{STALWART}/jmap/session")
    return mailbox_password


# -- the invented mail over IMAP ------------------------------------------------


def fill(password: str) -> None:
    context = ssl.create_default_context(cafile=str(SECRETS / "tls" / "ca.pem"))
    end = time.monotonic() + 60
    while True:
        try:
            imap = imaplib.IMAP4_SSL(
                "127.0.0.1", 38993, ssl_context=context, timeout=10
            )
            break
        except (OSError, ssl.SSLError):
            if time.monotonic() > end:
                raise
            time.sleep(1)
    with imap:
        imap.login(ADDRESS, password)
        roles = {"inbox": "INBOX"}
        for line in imap.list()[1]:
            text = line.decode() if isinstance(line, bytes) else str(line)
            name = text.rsplit(' "/" ', 1)[-1].strip().strip('"')
            if "\\Sent" in text:
                roles["sent"] = name
        if "sent" not in roles:
            raise SystemExit("provision: the account has no folder for sent mail")
        for folder in mail.FOLDERS:
            imap.create(f'"{folder}"')
        count = 0
        for role, flags, message in mail.messages(ADDRESS):
            folder = roles.get(role, role)
            status, _ = imap.append(
                f'"{folder}"', flags or None, None, message.as_bytes()
            )
            if status != "OK":
                raise SystemExit(f"provision: APPEND to {folder} failed")
            count += 1
        imap.logout()
    say(f"{count} invented messages in {len(mail.FOLDERS) + 2} folders")


# -- the mailbox service ------------------------------------------------------------


class Ui:
    """The service's configuration UI, for the one step the API cannot do:
    the first token."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def get(self, path: str) -> str:
        with self._opener.open(SERVICE + path, timeout=30) as answer:
            return answer.read().decode()

    def post(self, path: str, data: dict[str, str]) -> str:
        body = urllib.parse.urlencode(data).encode()
        with self._opener.open(SERVICE + path, body, timeout=30) as answer:
            return answer.read().decode()


def _field(html: str, name: str) -> str:
    found = re.search(rf'name="{name}" value="([^"]+)"', html)
    if not found:
        raise SystemExit(f"provision: the UI page has no {name}")
    return found.group(1)


def admin_token() -> str:
    wait_for(f"{SERVICE}/health")
    ui = Ui()
    one_time = os.environ["SERVICE_ONE_TIME_PASSWORD"]
    password = os.environ["SERVICE_PASSWORD"]
    page = ui.get("/ui/login")
    page = ui.post(
        "/ui/login",
        {
            "nonce": _field(page, "nonce"),
            "next": "/ui",
            "name": "admin",
            "password": one_time,
        },
    )
    ui.post(
        "/ui/password",
        {
            "csrf_token": _field(page, "csrf_token"),
            "name": "admin",
            "current_password": one_time,
            "new_password": password,
            "repeat_password": password,
        },
    )
    (SECRETS / "service-admin").write_text(f"admin:{password}\n", encoding="utf-8")
    user = re.search(r'href="/ui/users/(usr_[0-9a-f]+)"', ui.get("/ui/users"))
    if not user:
        raise SystemExit("provision: the UI lists no administrator")
    page = ui.get(f"/ui/users/{user.group(1)}?tab=access")
    page = ui.post(
        f"/ui/users/{user.group(1)}/tokens",
        {"csrf_token": _field(page, "csrf_token"), "name": "setup", "days": "1"},
    )
    token = re.search(r'<code class="secret" id="secret">(mbx_[A-Za-z0-9_-]+)', page)
    if not token:
        raise SystemExit("provision: the UI showed no token")
    return token.group(1)


def api(token: str, method: str, path: str, body: object | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(SERVICE + path, data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            text = answer.read()
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"provision: {method} {path} answered {exc.code}: "
            f"{exc.read().decode()[:800]}"
        ) from None


def service(password: str, gateway_key: str) -> None:
    token = admin_token()
    say("the account connected to the service")
    account = api(
        token,
        "POST",
        "/v1/accounts",
        {
            "provider": "imap",
            "email": ADDRESS,
            "display_name": "Agents (invented mail)",
            "settings": {
                "host": HOST,
                "port": 993,
                "security": "tls",
                "smtp_host": HOST,
                "smtp_port": 465,
                "smtp_security": "tls",
            },
            "credentials": {"password": password},
        },
    )
    account_id = account["id"]
    say("the user agents with mail.read and mail.write")
    user = api(
        token,
        "POST",
        "/v1/users",
        {
            "name": "agents",
            "grants": [
                {"accounts": [account_id], "allow": ["mail.read", "mail.write"]}
            ],
        },
    )
    made = api(token, "POST", f"/v1/users/{user['id']}/tokens", {"name": "live"})
    agent_token = made.get("token") or made.get("secret")
    if not agent_token:
        raise SystemExit(f"provision: no token in the answer, keys {sorted(made)}")
    (SECRETS / "service-token").write_text(agent_token + "\n", encoding="utf-8")
    (SECRETS / "agent.env").write_text(
        "\n".join(
            [
                "# Made by containers/live/mailbox-agents/setup.sh, test account only.",
                f"MAILBOX_AGENTS_SERVICE_URL={SERVICE}",
                f"MAILBOX_AGENTS_SERVICE_TOKEN={agent_token}",
                f"MAILBOX_AGENTS_ACCOUNTS={account_id}",
                "MAILBOX_AGENTS_STAGE=shadow",
                "MAILBOX_AGENTS_DATA_DIR=containers/live/mailbox-agents/secrets/data",
                "MAILBOX_AGENTS_INVOICES_FOLDERS=Providers/*",
                "MAILBOX_AGENTS_INVOICES_SUBFOLDER={folder}/Rechnungen",
                "MAILBOX_AGENTS_CATEGORIZATION_FILE=containers/live/mailbox-agents/categorization.json",
                f"MAILBOX_AGENTS_GATEWAY_URL={os.environ['GATEWAY_URL']}",
                f"MAILBOX_AGENTS_GATEWAY_KEY={gateway_key}",
                f"MAILBOX_AGENTS_MODEL={os.environ['GATEWAY_MODEL']}",
                # A local model on the CPU takes its time.
                "MAILBOX_AGENTS_GATEWAY_TIMEOUT_SECONDS=600",
                "",
            ]
        ),
        encoding="utf-8",
    )


def gateway() -> str:
    """A key of the gateway for the agents: the aliases of AGENT_MODELS
    only, within AGENT_BUDGET_USD. Made with the master key."""
    base = os.environ["GATEWAY_URL"].removesuffix("/v1")
    say("waiting for the gateway")
    wait_for(base + "/health/liveliness", 180)
    say("a key of the gateway for the agents, the mail-classifier aliases only")
    body = json.dumps(
        {
            "models": AGENT_MODELS,
            "max_budget": AGENT_BUDGET_USD,
            "key_alias": "live-agents",
        }
    ).encode()
    request = urllib.request.Request(base + "/key/generate", body, method="POST")
    request.add_header("Authorization", f"Bearer {os.environ['GATEWAY_MASTER_KEY']}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=60) as answer:
        made = json.loads(answer.read())
    key = made.get("key")
    if not isinstance(key, str) or not key:
        raise SystemExit(f"provision: no key in the answer, keys {sorted(made)}")
    return key


def main() -> None:
    os.umask(0o077)
    password = stalwart()
    fill(password)
    service(password, gateway())


if __name__ == "__main__":
    main()
