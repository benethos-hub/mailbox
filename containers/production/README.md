# Mailbox in operation

The published images from the GitHub container registry, run with
compose. Nothing is built, and no clone of the repository is needed:
this folder is enough.

| File | What it is |
|---|---|
| `compose.yaml` | the service, the MCP server (profile `mcp`) and Caddy (profile `https`) |
| `.env.example` | template of `.env`: the version, the profiles, the ports, the domain, the tokens of the MCP server |
| `service.env.example` | template of `service.env`: further settings of the service |
| `Caddyfile` | HTTPS in front, for the profile `https` |
| `setup.sh` | the first start in one run |
| `secrets/master_key` | made at the first start, never versioned |

Needs Docker with compose 2.24 or newer (`docker compose version`).

## Get the folder

Into an empty folder, from the repository at `main`, or at a release tag
from the first release that has this folder:

```sh
mkdir mailbox && cd mailbox
for file in compose.yaml Caddyfile .env.example service.env.example setup.sh README.md; do
  curl -fsSLO "https://raw.githubusercontent.com/benethos-hub/mailbox/main/containers/production/$file"
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
IMAGE=ghcr.io/benethos-hub/benethos-mailbox-service:0.2.0

mkdir -p secrets && chmod 700 secrets
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

## The MCP server

The MCP server acts as a user of the service, with that user's API
token:

1. In the UI, make a user for it with the rights it should have, and a
   token on that user's page.
2. In `.env`: the token as `MAILBOX_MCP_API_TOKEN`, a long random value
   as `MAILBOX_MCP_BEARER_TOKEN` (`openssl rand -base64 32`), and `mcp`
   in `COMPOSE_PROFILES`.
3. `docker compose up -d`

It listens on `http://127.0.0.1:8000/mcp`, and its clients send
`Authorization: Bearer <MAILBOX_MCP_BEARER_TOKEN>`. More in
[packages/mailbox-mcp/README.md](../../packages/mailbox-mcp/README.md).

## HTTPS

Beyond your own machine, the service needs HTTPS in front. Two ways:

**Caddy, the profile `https`.** Set `MAILBOX_DOMAIN` in `.env` to a name
whose DNS names this host, add `https` to `COMPOSE_PROFILES`, and let the
ports 80 and 443 reach the host. Then `docker compose up -d`. Caddy gets
the certificate from Let's Encrypt and renews it. The service is at
`https://<domain>/ui`, the MCP server at `https://<domain>/mcp`. Caddy
alone listens on every address, the service and the MCP server stay on
`127.0.0.1`.

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
[packages/mailbox-service/README.md](../../packages/mailbox-service/README.md#settings).
After a change: `docker compose up -d`.

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
dropped first.

## From the compose file before

Until this folder, `containers/compose.yaml` ran the service, with the
image named in `MAILBOX_SERVICE_IMAGE`. This compose file has the same
project name, `benethos-mailbox`, and the same volume, so the data
stays. Copy the old `secrets/master_key` into `secrets/` here, keep its
owner, and start with `docker compose up -d`. Without the master key the
credentials in the database cannot be read.
