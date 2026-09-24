# Containers

One folder per image, and a compose file for running them.

```
containers/
  compose.yaml                   # the service, published on 127.0.0.1 only
  benethos-mailbox-api/
    Dockerfile                   # build context: the repository root
  secrets/                       # local, not versioned: master_key
```

The image of `benethos-mailbox-api` is built for `linux/amd64` and
`linux/arm64` by the GitHub workflow `.github/workflows/container.yml` and
pushed to the GitHub container registry as
`ghcr.io/<owner>/benethos-mailbox-api`:

| Event | Tags |
|---|---|
| tag `v1.2.3` | `1.2.3`, `1.2`, `latest` |
| push to `main` | `main`, `sha-<commit>` |
| pull request | built, not pushed |

The MCP server has no image: a client starts it over stdio.

## In the container

- Runs as user `mailbox` (uid 10001), read-only root file system, no
  capabilities.
- Configuration from the environment only (`MAILBOX_API_*`, see
  `config/benethos-mailbox-api/.env.example`). The image sets
  `MAILBOX_API_HOST=0.0.0.0`, `MAILBOX_API_DATA_DIR=/data`,
  `MAILBOX_API_KEY_PROVIDER=file` and
  `MAILBOX_API_KEY_FILE=/run/secrets/master_key`.
- The database lives in the volume `data` at `/data`.
- The master key is the secret `master_key`. It holds the recovery key in
  text form, so the file and the recovery key are the same thing: keep a
  copy apart from the host.
- Health check on `GET /health`.

## First start

Run from this folder. `MAILBOX_API_IMAGE` picks a released image; without
it, `docker compose build` builds one from the repository.

```sh
export MAILBOX_API_IMAGE=ghcr.io/<owner>/benethos-mailbox-api:<version>

# 1. A new master key, written to the secret file on the host.
mkdir -p secrets
docker run --rm "$MAILBOX_API_IMAGE" keys generate > secrets/master_key
chmod 400 secrets/master_key
# Linux: the container user must be able to read it.
sudo chown 10001 secrets/master_key

# 2. The data key in the database, wrapped by the master key.
docker compose run --rm mailbox-api keys init

# 3. The first user with every right; the token is printed once.
docker compose run --rm mailbox-api users create-admin

# 4. Start.
docker compose up -d
curl http://127.0.0.1:8080/health
```

`keys init` prints the recovery key; it is the content of
`secrets/master_key`.

## Operation

```sh
docker compose logs -f mailbox-api
docker compose pull && docker compose up -d        # update
docker compose exec mailbox-api \
    benethos-mailbox-api backup /data/backup.mbx   # encrypted backup
docker compose cp mailbox-api:/data/backup.mbx .
```

Restore into a stopped service:

```sh
docker compose stop mailbox-api
docker compose cp backup.mbx mailbox-api:/data/backup.mbx
docker compose run --rm mailbox-api restore /data/backup.mbx
docker compose up -d
```
