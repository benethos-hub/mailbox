# benethos-mailbox-service

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI mailbox-service](https://img.shields.io/pypi/v/benethos-mailbox-service?label=PyPI%20mailbox-service)](https://pypi.org/project/benethos-mailbox-service/)
[![Container](https://img.shields.io/badge/ghcr.io-mailbox--service-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-service)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-service)](https://pypi.org/project/benethos-mailbox-service/)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

> **Pre-alpha, version 0.1.0.** Not ready for production use: the API,
> the stored data and the configuration may change without notice.

The Mailbox Service: one REST API (OpenAPI 3.1) for several mail
providers and accounts, with a configuration UI in the browser. It runs
permanently, holds the connections to the accounts, keeps their
credentials encrypted and syncs in the background. It keeps a feed of
what changed in the mailboxes and posts it to webhooks. Scripts, apps and
the
MCP server [`benethos-mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp)
reach mail only through it, each with a token of its own.

What the project is for: [the repository's README](https://github.com/benethos-hub/mailbox#readme).

## Install

From PyPI, with [uv](https://docs.astral.sh/uv/) or pip:

```sh
uv tool install benethos-mailbox-service      # or: pipx install benethos-mailbox-service
benethos-mailbox-service --version
```

`uvx benethos-mailbox-service ...` runs it without installing. In a clone of
the repository, every command below also works as
`uv run benethos-mailbox-service ...`.

The container image is `ghcr.io/benethos-hub/benethos-mailbox-service`. See
[Container](#container).

## First start

```sh
benethos-mailbox-service keys init              # once: the keys; prints the recovery key
benethos-mailbox-service users create-admin     # once: a user with every right; prints a one-time password
benethos-mailbox-service serve
```

- `keys init` creates the master key in the operating system's credential
  store and the data key in the database. It prints a **recovery key**
  once. Keep it apart from the machine and its backups. Without it, a
  database cannot be opened on another machine.
- `users create-admin` creates the user `admin` and prints a one-time
  password once. Sign in to the UI with it. The UI then asks for a
  password of your own, 15 characters at least. Tokens for the API are
  made in the UI, on a user's page.
- Further users are API users unless their UI sign-in is switched on:
  they work with tokens only, e.g. a script or an MCP server.
- A forgotten password: `users set-password <name>` on the host gives
  that user a new one-time password, and switches its UI sign-in on.
- Both write the secret alone to standard output and everything else to
  standard error, so it can be piped straight into a password manager.
  Printed to a terminal, it stays in its scrollback, and in a container
  or CI job, in the log of that run. Clear these afterwards.
- `serve` listens on `http://127.0.0.1:8080`:
  - `/ui`: the configuration UI (sign in with the user name and password)
  - `/docs`: the interactive API documentation
  - `/health`: open, for health checks

Then connect accounts in the UI (Accounts, Connect an account) or with
`POST /v1/accounts`. An IMAP account needs its address and an app
password. The service looks up the servers from the address. Microsoft
accounts sign in with OAuth and need an app registration first:
[docs/microsoft.md](https://github.com/benethos-hub/mailbox/blob/main/docs/microsoft.md).

## Where things live

The service works from the folder it is started in:

| What | Where |
|---|---|
| settings | the environment, or `config/benethos-mailbox-service/.env` (the environment wins) |
| the database | `data/benethos-mailbox-service/mailbox.db`, readable by its owner only |
| the master key | the OS credential store (keyring), or a file or variable (see `MAILBOX_SERVICE_KEY_PROVIDER`) |

A template for the settings file with every option:
[config/benethos-mailbox-service/.env.example](https://github.com/benethos-hub/mailbox/blob/main/config/benethos-mailbox-service/.env.example).

To keep the settings somewhere else, name the file. Every command takes
`--env-file PATH`, before or after the command, or reads
`MAILBOX_SERVICE_ENV_FILE`:

```
benethos-mailbox-service --env-file /etc/mailbox/service.env users create-admin
benethos-mailbox-service serve --env-file /etc/mailbox/service.env
```

A file named this way must exist. A relative path in the settings then
counts from its folder, not from the folder the service is started in:
`MAILBOX_SERVICE_DATA_DIR=data` puts the database in `/etc/mailbox/data/`.
So every command finds the same data wherever it is started. `serve`
names the settings file it read and the database at start.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `MAILBOX_SERVICE_HOST`, `MAILBOX_SERVICE_PORT` | `127.0.0.1`, `8080` | where the service listens (`serve --host/--port` win) |
| `MAILBOX_SERVICE_PUBLIC_URL` | from each request | the address people reach the service at, e.g. behind a proxy. The OAuth redirect address is built from it. |
| `MAILBOX_SERVICE_FORWARDED_ALLOW_IPS` | `127.0.0.1` | behind a reverse proxy: its address, whose `X-Forwarded-*` headers give the client address, scheme and host |
| `MAILBOX_SERVICE_LOG_LEVEL` | `INFO` | `critical`, `error`, `warning`, `info`, `debug` or `trace`, see [Logs](#logs) |
| `MAILBOX_SERVICE_DATA_DIR` | `data/benethos-mailbox-service` | where the database lives |
| `MAILBOX_SERVICE_STORAGE` | `sqlite` | or `memory`, which keeps nothing |
| `MAILBOX_SERVICE_KEY_PROVIDER` | `keyring` | where the master key lives: `keyring`, `file` or `env` |
| `MAILBOX_SERVICE_KEY_FILE` | | the key file, for `file` |
| `MAILBOX_SERVICE_MASTER_KEY` | | the recovery key, for `env` |
| `MAILBOX_SERVICE_SYNC_INTERVAL` | `300` | seconds between two polls of every folder. `0` switches the sync off. |
| `MAILBOX_SERVICE_SYNC_IDLE` | `true` | watch the inbox over IMAP IDLE, with a second connection per account |
| `MAILBOX_SERVICE_CHANGES_DAYS` | `7` | days the change feed keeps a change |
| `MAILBOX_SERVICE_WEBHOOK_ATTEMPTS` | `8` | tries of a webhook post before its events are dropped |
| `MAILBOX_SERVICE_WEBHOOK_FIRST_RETRY` | `30` | seconds before the second try, doubled for each further one |
| `MAILBOX_SERVICE_WEBHOOK_LONGEST_RETRY` | `3600` | the longest pause between two tries, in seconds |
| `MAILBOX_SERVICE_WEBHOOK_TIMEOUT` | `10` | seconds a webhook receiver may take to answer |
| `MAILBOX_SERVICE_DISCOVERY_ISPDB` | `true` | whether autodiscovery asks Thunderbird's ISPDB (tells Mozilla the domain) |
| `MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS` | `[]` | JSON list of hosts that may resolve to private addresses, e.g. an internal mail server. Autodiscovery may look them up and accounts may use them. |
| `MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID` | | the Entra app for Microsoft accounts. Without it they cannot be connected. |
| `MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET` | | its client secret, or better: |
| `MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET_FILE` | | a file holding it |
| `MAILBOX_SERVICE_OAUTH_MICROSOFT_TENANT` | `common` | who may sign in: `common`, `consumers`, `organizations` or one tenant |

## Logs

`serve` writes one log to stderr: the terminal, `docker compose logs`, or
the journal under systemd. There is no log file. Each line has the time,
the level, where it comes from and the message:

```
2026-09-28 10:14:03 INFO     benethos_mailbox_service.domain.auth: sign-in to the UI as admin (usr_...) from 127.0.0.1
2026-09-28 10:14:03 INFO     uvicorn.access: 127.0.0.1:52344 - "POST /ui/sign-in HTTP/1.1" 303
```

At a terminal the lines are shorter and in colour: the time of day, the
level in colour, the source without the package name (`http` for the
access log), and a request as method, path and status with its name:

```
10:14:03 INFO    domain.auth    sign-in to the UI as admin (usr_...) from 127.0.0.1
10:14:03 INFO    http           POST /ui/sign-in 303 See Other 127.0.0.1:52344
```

`NO_COLOR` set to any value keeps the plain lines at a terminal too.

`MAILBOX_SERVICE_LOG_LEVEL` sets the level of the service and of uvicorn.
Libraries write from `warning` on at any level, so `debug` shows the
service without the commands a library sends to a mail server. The
service logs sign-ins to the UI and changes to users, roles, tokens and
passwords, and to whom the recovery key was shown. A password, token or
secret the service holds is written as `***`, should a message or a
traceback carry one.

## Commands

| Command | What it does |
|---|---|
| `serve [--host H] [--port P]` | runs the service |
| `keys init` | creates the keys, prints the recovery key once |
| `keys import` | stores the master key from a recovery key read from stdin, e.g. on a new machine |
| `keys generate` | prints a new master key for a key file or a container secret, stores nothing |
| `users create-admin [--name N]` | creates a user with every right and prints a one-time password |
| `users set-password NAME` | gives the user a new one-time password and prints it, and switches its UI sign-in on |
| `backup FILE` | writes an encrypted backup, while the service runs |
| `backup verify FILE [--recovery-key]` | checks a backup |
| `restore FILE [--recovery-key [--replace-master-key]]` | replaces the database with a backup. Stop the service first. |
| `openapi` | prints the OpenAPI document |

A backup holds accounts, users, rights, token hashes and the encrypted
credentials, never mail. It is encrypted as a whole and opens only with
the master key or the recovery key, which are not in it. `restore` keeps
the previous database beside the restored one. It refuses while a
service runs on the database: a running service holds the lock file
`mailbox.db.lock` beside it. With `--recovery-key` it reads the recovery
key from stdin, for a new machine. When the key provider holds another
master key there, `restore` refuses: the database kept beside the
restored one opens with that key alone. Note its recovery key, then pass
`--replace-master-key`.

## Users, rights and tokens

Every route under `/v1` needs `Authorization: Bearer <token>`. Only
`/health` is open. A token belongs to a user. The user's grants decide
what it may do, per account and per operation: for example read mail,
write drafts, send, manage accounts. Grants can limit sending to certain
recipients and to a number of mails per day. Every send is recorded in an
audit. `GET /v1/me` shows what a token may do.

Users, roles and tokens are managed in the UI (Users, Roles) or under
`/v1/users` and `/v1/roles`. A token is shown once, when it is created,
and so is a one-time password from `POST /v1/users/{user_id}/password`.
Give each script and each assistant its own user with only the rights it
needs. Until `users create-admin` has made the first user, the API
answers `503 setup_required`. Every call is made by a user, so the
audit names one.

## Changes and webhooks

`GET /v1/changes` names each message created, updated or deleted since
the `state` of an earlier answer, across the accounts the token may read.
`GET /v1/accounts/{account_id}/changes` does the same for one account.
Both need `mail.read`. A state older than `MAILBOX_SERVICE_CHANGES_DAYS`
answers `410 changes_expired`, and the client starts again without
`since`.

`POST /v1/webhooks` registers a URL, with the right `webhooks.manage`.
The service posts the events there as JSON, signed in
`X-Mailbox-Signature`, and tries a failed post again as the
`MAILBOX_SERVICE_WEBHOOK_*` settings say. The signing secret is in the
answer to `POST`, the only time it is shown. A host in the local network
is allowed. The format of a post is in
[CONCEPT.md, section 6.5](https://github.com/benethos-hub/mailbox/blob/main/docs/CONCEPT.md#65-changes-and-webhooks).

## Container

The image `ghcr.io/benethos-hub/benethos-mailbox-service` runs as an
unprivileged user on a read-only root file system. It takes its settings
from the environment only and sets `MAILBOX_SERVICE_HOST=0.0.0.0`,
`MAILBOX_SERVICE_DATA_DIR=/data`, `MAILBOX_SERVICE_KEY_PROVIDER=file` and
`MAILBOX_SERVICE_KEY_FILE=/run/secrets/master_key`. The database lives in the
volume at `/data`. The master key is a file mounted at
`/run/secrets/master_key`. Tags: the version (`0.1.0`), the minor version
(`0.1`) and `latest`.

### With docker run

```sh
IMAGE=ghcr.io/benethos-hub/benethos-mailbox-service:0.1.0

# once: a master key file, the keys in the database, the first user
docker run --rm "$IMAGE" keys generate > master_key
chmod 400 master_key
sudo chown 10001 master_key  # Linux: the container user (uid 10001) reads it
docker volume create mailbox-data
docker run --rm -v mailbox-data:/data -v "$PWD/master_key:/run/secrets/master_key:ro" "$IMAGE" keys init
docker run --rm -v mailbox-data:/data -v "$PWD/master_key:/run/secrets/master_key:ro" "$IMAGE" users create-admin

# the service, on the loopback address of the host only
docker run -d --name mailbox-service --restart unless-stopped \
  -p 127.0.0.1:8080:8080 --read-only --tmpfs /tmp \
  -v mailbox-data:/data -v "$PWD/master_key:/run/secrets/master_key:ro" \
  "$IMAGE"
```

The file `master_key` holds the recovery key. Whoever has it and a backup
has the credentials. Keep a copy apart from the host.

### With compose

The repository's
[containers/compose.yaml](https://github.com/benethos-hub/mailbox/blob/main/containers/compose.yaml)
runs the service. With the profile `mcp` it also runs the MCP server over
HTTP. Both listen on `127.0.0.1` only. From the folder that holds the
file:

```sh
export MAILBOX_SERVICE_IMAGE=ghcr.io/benethos-hub/benethos-mailbox-service:0.1.0

mkdir -p secrets
docker run --rm "$MAILBOX_SERVICE_IMAGE" keys generate > secrets/master_key
chmod 400 secrets/master_key
sudo chown 10001 secrets/master_key          # Linux: the container user reads it

docker compose run --rm mailbox-service keys init
docker compose run --rm mailbox-service users create-admin
docker compose up -d
curl http://127.0.0.1:8080/health
```

Without `MAILBOX_SERVICE_IMAGE`, compose builds the image from a clone of the
repository. Settings go into the `environment` of the service in the
compose file.

Operation:

```sh
docker compose logs -f mailbox-service
docker compose pull && docker compose up -d                        # update
docker compose exec mailbox-service benethos-mailbox-service backup /data/backup.mbx
docker compose cp mailbox-service:/data/backup.mbx .

# restore, into a stopped service
docker compose stop mailbox-service
docker compose cp backup.mbx mailbox-service:/data/backup.mbx
docker compose run --rm mailbox-service restore /data/backup.mbx
docker compose up -d
```

Beyond your own machine, put a TLS reverse proxy in front and set
`MAILBOX_SERVICE_PUBLIC_URL` to the address it serves.
