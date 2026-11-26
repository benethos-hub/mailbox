# <img src="../../../assets/brand/icon.svg" alt="" height="36" align="absmiddle"> Mailbox in operation

> **Beta, version 0.11.1.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

The published images from the GitHub container registry, run with
compose. Nothing is built, and no clone of the repository is needed:
this folder is enough.

**Contents**

- [Get the folder](#get-the-folder)
- [The first start](#the-first-start)
- [Clients](#clients)
- [MCP server instances](#mcp-server-instances)
- [HTTPS](#https)
- [Settings](#settings)
- [Operation](#operation)
- [PostgreSQL](#postgresql)
  - [In this compose file](#in-this-compose-file)
  - [A server of your own](#a-server-of-your-own)
  - [Move to PostgreSQL](#move-to-postgresql)
  - [Backup and restore on PostgreSQL](#backup-and-restore-on-postgresql)
  - [Set a schema aside](#set-a-schema-aside)
  - [What the role sees](#what-the-role-sees)
- [Monitoring with Prometheus](#monitoring-with-prometheus)

| File | What it is |
|---|---|
| `compose.yaml` | the service, Caddy for HTTPS (profile `https`) and PostgreSQL as the database (profile `postgres`) |
| `.env.example` | template of `.env`: the version, the profiles, the port, the domain, the certificate |
| `service.env.example` | template of `service.env`: further settings of the service |
| `Caddyfile` | HTTPS in front, for the profile `https` |
| `mcp.yaml` | the template of an MCP server instance |
| `compose.override.yaml.example` | template of `compose.override.yaml`: MCP server instances, profile `mcp` |
| `caddy.d/mcp.caddy.example` | template of a route in Caddy to an instance |
| `caddy.d/metrics.caddy.example` | keeps `/v1/metrics` from the outside at Caddy |
| `setup.sh` | the first start in one run |
| `secrets/` | made at the first start, never versioned: `master_key`, `database_password` and `database_admin_password` with the profile `postgres`, `mcp/` the tokens of the instances, `tls/` a certificate of your own |

Needs Docker with compose 2.24 or newer (`docker compose version`).

## Get the folder

Into an empty folder, from the repository. The files at a release tag
fit that version, so put `v0.11.1` in place of `main` in the address
below for 0.11.1. `main` holds the newest. Up to 0.9.0 the folder was
`containers/production/`, without `mailbox-service/`:

```sh
mkdir -p mailbox/caddy.d && cd mailbox
for file in compose.yaml Caddyfile .env.example service.env.example setup.sh README.md \
    mcp.yaml compose.override.yaml.example caddy.d/mcp.caddy.example \
    caddy.d/metrics.caddy.example; do
  curl -fsSL -o "$file" "https://raw.githubusercontent.com/benethos-hub/mailbox/main/containers/production/mailbox-service/$file"
done
```

## The first start

```sh
sh setup.sh
```

It writes `.env` from `.env.example` if there is none, makes the master
key, creates the keys in the database and the first user `admin`, then
starts what `COMPOSE_PROFILES` names. It prints the recovery key and the
administrator's one-time password once: keep the recovery key apart from
the host. A second run changes nothing that exists.

The same by hand, from this folder:

```sh
cp .env.example .env && chmod 600 .env          # then edit it
IMAGE=ghcr.io/benethos-hub/benethos-mailbox-service:0.11.1

mkdir -p caddy.d secrets/mcp secrets/tls && chmod 700 secrets secrets/mcp
docker run --rm "$IMAGE" keys generate > secrets/master_key
chmod 400 secrets/master_key
sudo chown 10001 secrets/master_key             # Linux: the container user reads it

docker compose run --rm mailbox-service keys init
docker compose run --rm mailbox-service users create-admin
docker compose up -d
curl http://127.0.0.1:8080/health
```

Then sign in at `http://127.0.0.1:8080/ui` as `admin` with the one-time
password. The UI asks for a password of your own.

`secrets/master_key` holds the recovery key. Whoever has it and a backup
has the credentials. Keep a copy apart from the host
(`sudo cat secrets/master_key`).

## Clients

An MCP client reaches mail through the MCP server. It acts as one user,
with that user's API token, so each client has an MCP server of its own
(CONCEPT 8.1). Two ways:

- **The client starts it**, over stdio: Claude Desktop, Claude Code, an
  agent wherever it runs. Nothing runs here for it. This is the usual
  way.
- **An instance beside the service**, over HTTP, for a client that
  connects to a URL. See [MCP server instances](#mcp-server-instances).

Either way, first in the UI: a user with the rights the client should
have, and a token on that user's page.

The client starts the MCP server with the service's address and that
token, at the same version as the service, the `MAILBOX_VERSION` of
`.env`:

```json
{
  "mcpServers": {
    "mailbox": {
      "command": "uvx",
      "args": ["benethos-mailbox-mcp==<MAILBOX_VERSION>"],
      "env": {
        "MAILBOX_SERVICE_URL": "https://mail.example.org",
        "MAILBOX_SERVICE_TOKEN": "<the user's token>"
      }
    }
  }
}
```

The MCP server and the service must have the same version to work
together. The tool `server_status` with `details` shows whether they
match.

The address is `https://<MAILBOX_DOMAIN>` with the profile `https`, or
that of your own proxy. Without either, the service answers on this host
alone, at `http://127.0.0.1:8080`. More, for Claude Desktop, Claude Code
and over HTTP:
[packages/mailbox-mcp/README.md](../../../packages/mailbox-mcp/README.md).

## MCP server instances

An instance is an MCP server in a container beside the service, over
streamable HTTP. Each acts as one user with that user's token, and
admits its clients with a bearer token of its own. There may be as many
as there are clients or purposes. They start with the profile `mcp`,
never without it.

`mcp.yaml` is the template: the image at `MAILBOX_VERSION`, the same
hardening as the service, and the service's address in the compose
network. `compose.override.yaml` holds the instances, one block each.
Compose reads it with `compose.yaml` by itself.

Once, from this folder:

```sh
cp compose.override.yaml.example compose.override.yaml
```

Then the example's two instances: `mcp-assistant` for a client on this
host, `mcp-agent` for clients elsewhere through Caddy. Keep, rename or
remove them. The block `mcp-agent` reads `MAILBOX_DOMAIN`: while `.env`
names no domain, remove it, or every `docker compose` command stops
with `set MAILBOX_DOMAIN in .env`. For each instance:

1. In the UI, a user with the rights of the instance, and a token.
2. Its two tokens as files in `secrets/mcp/<name>/`, which only the
   container user reads:

   ```sh
   umask 077
   mkdir -p secrets/mcp/agent
   printf '%s\n' '<token of the user>' > secrets/mcp/agent/service_token
   openssl rand -hex 32 > secrets/mcp/agent/bearer_token
   sudo chown -R 10001 secrets/mcp/agent   # Linux: the container user reads them
   ```

   The clients send the bearer token: `sudo cat secrets/mcp/agent/bearer_token`.
   Up to 0.10.0 the example read both tokens from `secrets/mcp/<name>.env`
   through `env_file`. A block that still does keeps working.

3. Its block in `compose.override.yaml`, with a name of its own, its two
   secrets and their entries under `secrets:`. For a client on this host, a port on `127.0.0.1` and that
   port in `MAILBOX_MCP_ALLOWED_HOSTS`. For clients elsewhere, no port
   but a route in Caddy (step 4).
4. Only for clients elsewhere, with the profile `https`: a route in
   `caddy.d/<name>.caddy`, from `caddy.d/mcp.caddy.example`. Its path is
   the instance's `MAILBOX_MCP_PATH`, here `/mcp/agent`, and
   `MAILBOX_MCP_ALLOWED_HOSTS` is `MAILBOX_DOMAIN`.
5. `mcp` in `COMPOSE_PROFILES` in `.env`, then:

   ```sh
   docker compose up -d
   docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile   # after step 4
   ```

The client then connects with the bearer token, to
`http://127.0.0.1:8101/mcp` on this host, or to
`https://<MAILBOX_DOMAIN>/mcp/agent` from elsewhere. For Claude Code:

```sh
claude mcp add --transport http mailbox https://mail.example.org/mcp/agent \
  --header "Authorization: Bearer <bearer token>"
```

To remove an instance: delete its block, its secrets and its route,
run `docker compose up -d --remove-orphans` and reload Caddy. Revoke its
token in the UI.

An update of `MAILBOX_VERSION` updates the instances with the service.

**On another host.** An instance needs no service beside it. There,
`mcp.yaml` and a `compose.yaml` of its own with the instances, each
naming the service's address:

```yaml
services:
  mcp-agent:
    extends:
      file: mcp.yaml
      service: mailbox-mcp
    secrets: [agent_service_token, agent_bearer_token]
    ports:
      - "127.0.0.1:8101:8000"
    environment:
      MAILBOX_SERVICE_URL: https://mail.example.org
      MAILBOX_SERVICE_TOKEN_FILE: /run/secrets/agent_service_token
      MAILBOX_MCP_BEARER_TOKEN_FILE: /run/secrets/agent_bearer_token
      MAILBOX_MCP_ALLOWED_HOSTS: 127.0.0.1:8101,localhost:8101

secrets:
  agent_service_token:
    file: ./secrets/mcp/agent/service_token
  agent_bearer_token:
    file: ./secrets/mcp/agent/bearer_token
```

With an `.env` naming `MAILBOX_VERSION`. The service must be reachable
over HTTPS from there, and clients from elsewhere need a TLS proxy on
that host.

## HTTPS

Beyond your own machine, the service needs HTTPS in front. Two ways:

**Caddy, the profile `https`.** Set `MAILBOX_DOMAIN` in `.env`, add
`https` to `COMPOSE_PROFILES`, and choose in `MAILBOX_TLS` where the
certificate comes from. Then `docker compose up -d`. The service is at
`https://<domain>/ui`, and clients reach it at `https://<domain>`. Caddy
alone listens on every address, on 80 and 443, the service stays on
`127.0.0.1`.

| `MAILBOX_TLS` | Certificate | Needs |
|---|---|---|
| `acme` (default) | from Let's Encrypt, renewed by Caddy | DNS of the domain names this host, ports 80 and 443 reach it from the internet |
| `internal` | from the CA of Caddy | clients trust its root certificate: `docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt` |
| `files` | your own, e.g. from a company CA | `secrets/tls/server.pem` (with its chain) and `secrets/tls/server.key` |

In a company network without access from the internet, `acme` gets no
certificate. Take `internal`, or `files` with a certificate of the
company CA, which its clients trust already. A value other than these
three stops Caddy with `File to import not found: tls-<value>`.

For `files`, Caddy runs as root with no capability but
`NET_BIND_SERVICE`. It reads the key only if root owns it, and
`secrets/tls` only if the folder is open to it. A run of `setup.sh`
after the files are copied in sees to both, or by hand:

```sh
chmod 755 secrets/tls && chmod 600 secrets/tls/server.key
docker run --rm -v "$PWD/secrets/tls:/certs" caddy:2 chown 0 /certs/server.key
```

`secrets/` itself stays `700`. After a new certificate,
`docker compose restart caddy`.

**A proxy of your own** on the host. It passes the requests to
`http://127.0.0.1:8080`. In `.env`:

```
MAILBOX_SERVICE_PUBLIC_URL=https://mail.example.org
MAILBOX_SERVICE_FORWARDED_ALLOW_IPS=172.30.80.1
```

The second line makes the service believe the `X-Forwarded-*` headers of
requests from the host, through the gateway of the compose network. The
service counts its request limits per client address from them.

## Settings

The compose variables go into `.env`, see `.env.example`. Every other
setting of the service, `MAILBOX_SERVICE_*`, goes into `service.env`
(template `service.env.example`). The list:
[packages/mailbox-service/README.md](../../../packages/mailbox-service/README.md#settings).
After a change: `docker compose up -d`.

`MAILBOX_SERVICE_HOST_PORT` in `.env` is the service's port on the host.
`MAILBOX_SERVICE_PORT` is the port the service listens on in its
container, which the compose file and Caddy expect at 8080: leave it
out of `service.env`. Up to 0.10.0 the port on the host was
`MAILBOX_SERVICE_PORT` in `.env`. The compose file still reads that
name when the new one is not set, for one release.

## Operation

```sh
docker compose ps
docker compose logs -f mailbox-service

# update: set MAILBOX_VERSION in .env to the new version, then
docker compose pull && docker compose up -d

# backup, while the service runs
docker compose exec mailbox-service benethos-mailbox-service backup /data/backup.mbx
docker compose cp mailbox-service:/data/backup.mbx .

# restore, into a stopped service
docker compose stop mailbox-service
docker compose cp backup.mbx mailbox-service:/data/backup.mbx
docker compose run --rm mailbox-service restore /data/backup.mbx
docker compose up -d
```

Docker keeps at most 5 log files of 10 MB per container, the oldest
dropped first. Should the sync or the delivery of webhooks end with an
error, the service stops with it, and `restart: unless-stopped` starts
it anew. For a log collector, `MAILBOX_SERVICE_LOG_FORMAT=json` in
`service.env` writes each line as one JSON object.

## PostgreSQL

SQLite in the volume `data` is the default and needs nothing. PostgreSQL
19 or newer holds the records instead, in the container of the profile
`postgres` or on a server of your own. The service keeps one connection
of its own for as long as it runs, and holds a lock on it that keeps a
second service off the same schema. A pooler that shares connections
per transaction does not keep that lock: connect the service directly.
The driver comes with the image, and with it libpq and OpenSSL: their
fixes arrive with a new version of the service, not with the host.

### In this compose file

Before the first start, put `postgres` into `COMPOSE_PROFILES` of
`.env` and the four lines of `service.env.example` that name the
database into `service.env`. `setup.sh` then makes the passwords in
`secrets/`, starts PostgreSQL and makes the role `mailbox` with the
schema `mailbox` of its own, without further rights and with at most
five connections. The database has no port on the host and its network
no way out, so TLS is off there, and the start of the service says so.
An installation that runs on SQLite already moves its records over as
below.

### A server of your own

Make a role for the service and a schema of the same name it owns,
as an administrator of the server:

```sql
CREATE ROLE mailbox LOGIN PASSWORD '...' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 5;
CREATE SCHEMA mailbox AUTHORIZATION mailbox;
```

`MAILBOX_SERVICE_DATABASE_URL` names it without the password,
`postgresql://mailbox@db.example.org:5432/<database>`, and the password
goes into the file `MAILBOX_SERVICE_DATABASE_PASSWORD_FILE` names. The
service verifies the certificate of a server that is not on the same
host, against the certificates of the system or the file
`MAILBOX_SERVICE_DATABASE_CA_FILE` names.

### Move to PostgreSQL

1. Take a backup, as under [Operation](#operation).
2. Stop the service: `docker compose stop mailbox-service`.
3. Set up the database, in this compose file or on a server of your
   own, and put the lines that name it into `service.env`, but leave
   `MAILBOX_SERVICE_STORAGE` as it is.
4. Check the records: `docker compose run --rm mailbox-service storage
   move --to postgres --check`. A value an older version wrote that does
   not fit its column is named with its table and column. Nothing is
   written.
5. Move them: `docker compose run --rm mailbox-service storage move --to
   postgres`. It copies every record into the empty schema and compares
   each table. The file `mailbox.db` stays as it is.
6. Set `MAILBOX_SERVICE_STORAGE=postgres` in `service.env`, then
   `docker compose up -d`.

`--to sqlite` moves them back, into a `mailbox.db` that is not there
yet. A move that does not finish leaves a mark, and the service does not
open that database: set the schema aside and move again.

### Backup and restore on PostgreSQL

`backup` works as under [Operation](#operation) and writes format 3,
read from one moment while the service runs. `restore` goes into an
empty schema only, after the service is stopped. A backup made on
SQLite in format 1 or 2 goes there in two steps: `restore` with
`MAILBOX_SERVICE_STORAGE=sqlite`, then the move above.

### Set a schema aside

A restore or a move goes into an empty schema. The service never drops
a schema, and its role cannot make a new one. An administrator of the
server renames the old one and gives the role a new, empty one. In this
compose file:

```sh
docker compose stop mailbox-service
docker compose exec postgres psql -U postgres -d mailbox \
  -c "ALTER SCHEMA mailbox RENAME TO mailbox_before" \
  -c "CREATE SCHEMA mailbox AUTHORIZATION mailbox"
```

Drop `mailbox_before` once the service runs on the new one and a new
backup is taken: `DROP SCHEMA mailbox_before CASCADE`.

### What the role sees

The role reads no row outside its schema and cannot end the session of
another role. It sees the names of the tables of other schemas and of
the roles, and that other sessions exist, never the text of their
queries. It could drop its own schema. On a server shared with others,
that is what each of them sees of the service (measured on PostgreSQL
19, 2026-11-26).

## Monitoring with Prometheus

The service hands its figures to Prometheus at `GET /v1/metrics`: the
sync worker, every account by its id, provider and status, and the
webhooks. Never an address or the text of an error. What each figure
means: [CONCEPT 6.1](../../../docs/mailbox-service/concept/api-mail.md#61-accounts).

The route is on unless `MAILBOX_SERVICE_METRICS=false` in `service.env`
switches it off, then it answers `404`. Without a token with the right
`metrics` it answers nothing either way.

1. In the UI, a role `monitor` that holds only the right of the service
   `metrics`, a user `monitor` with that role, and a token on that
   user's page. The token reads the figures and nothing else.
2. The token into a file Prometheus reads, readable by it alone, and the
   scrape. `compose.yaml` publishes the service on `127.0.0.1:8080` of
   the host, so Prometheus on the same host asks it past Caddy:

   ```yaml
   scrape_configs:
     - job_name: mailbox
       metrics_path: /v1/metrics
       authorization:
         credentials_file: /etc/prometheus/mailbox.token
       static_configs:
         - targets: ["127.0.0.1:8080"]
   ```

3. With the profile `https`, keep the path from the outside:
   `caddy.d/metrics.caddy.example` to `caddy.d/metrics.caddy`, then
   `docker compose up -d`. The token protects the figures either way.

Five alerts to start from come with the service, for `rule_files` of
Prometheus. The service prints them, so they match the figures of its
version:

```sh
docker compose exec -T mailbox-service benethos-mailbox-service alert-rules > mailbox.rules.yml
```

Prometheus loads the file through `rule_files: [mailbox.rules.yml]`.
Print it again after an update of the service.

- `MailboxAccountNeedsALook`: an account needs a look when it is not
  connected, the service cannot use it, its last pass failed, or a send
  of its outbox in the last 24 hours has an unknown outcome. The 15
  minutes let a short outage of a mail server pass.
- `MailboxSyncStalls`: a round goes over the accounts one after
  another and takes longer with an account that does not answer. Raise
  the factor 3 in the file where rounds are slow. After a restart the series is missing until the first round
  ends, so the alert stays quiet then. An alert on `absent()` of it
  would fire after every restart.
- `MailboxWebhookFails`: a webhook fails when its last post did. The
  next post that succeeds clears it.
- `MailboxSendUnknown`: a send of an outbox in the last 24 hours whose
  outcome cannot be told. The service does not send it again, and its
  draft stays: a person looks whether it arrived. It clears after 24
  hours.
- `MailboxNotAnswering`: no figures for five minutes. The service is
  gone, or it cannot reach its database, which the check of the token
  of `GET /v1/metrics` needs. `mailbox_storage_outages_total` counts the
  times the database went away since the start.

The figures live in memory and start again after a restart. Each
scrape counts against the token's limit like any request and writes a
line to the access log. A wrong token counts as a failed sign-in of its
address: ten in 15 minutes lock the address for 15 minutes
([LIMITS.md](../../../docs/mailbox-service/LIMITS.md)).
