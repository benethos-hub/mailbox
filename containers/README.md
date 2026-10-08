# <img src="../assets/logo/icon-3d.svg" alt="" height="36" align="absmiddle"> Containers

> **Beta, version 0.3.1.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

The images, and the places they run in, each in a folder of its own.
Each place keeps its secrets in its own `secrets/`, never versioned.

```
containers/
  images/                        # what the CI builds and publishes
    mailbox-service/Dockerfile   # build context: the repository root
    mailbox-mcp/Dockerfile       # the MCP server over streamable HTTP
  production/                    # in operation, the published images:
    compose.yaml                 #   the service, Caddy for HTTPS (profile
                                 #   https)
    .env.example                 #   template of .env: the version, the
                                 #   profiles, the port, the domain, the
                                 #   certificate
    service.env.example          #   template of service.env: further
                                 #   settings of the service
    Caddyfile                    #   HTTPS in front, for the profile https
    mcp.yaml                     #   the template of an MCP server
                                 #   instance, run from
                                 #   compose.override.yaml (profile mcp)
    compose.override.yaml.example
                                 #   template of compose.override.yaml
    caddy.d/mcp.caddy.example    #   template of a route of Caddy to an
                                 #   instance
    setup.sh                     #   the first start
    README.md                    #   how to set it up and run it
  development/                   # for development, built from the repository
    compose.yaml                 # the service, the MCP server with the
                                 #   profile mcp, ports on 127.0.0.1 only
  test-mail-server/              # Stalwart as a mail server for tests
    compose.yaml                 #   ports on 127.0.0.1 only
    setup.sh                     #   makes the server anew
    README.md                    #   how to set it up and use it
```

| Folder | For | Images |
|---|---|---|
| `production/` | running Mailbox, without a clone of the repository | from the GitHub container registry, the version named in `.env` |
| `development/` | trying a change in a container | built from this repository |
| `test-mail-server/` | the adapters against a mail server of our own | Stalwart |

How to start and run the service and the MCP server, with `docker run`
or with compose:

- the service: [packages/mailbox-service/README.md](../packages/mailbox-service/README.md#container)
- the MCP server: [packages/mailbox-mcp/README.md](../packages/mailbox-mcp/README.md#container)

## For development

`development/compose.yaml` builds both images from the repository. The
first start, in `development/`:

```sh
docker compose build
mkdir -p secrets && chmod 700 secrets
docker run --rm benethos-mailbox-service:local keys generate > secrets/master_key
chmod 400 secrets/master_key
sudo chown 10001 secrets/master_key             # Linux: the container user reads it
docker compose run --rm mailbox-service keys init
docker compose run --rm mailbox-service users create-admin
docker compose up -d
```

The master key lives in `development/secrets/master_key`. The MCP server
starts with `docker compose --profile mcp up -d`. Compose reads these variables from
the environment or from an `.env` beside the file, not versioned:

| Variable | Default | What it is |
|---|---|---|
| `MAILBOX_SERVICE_PORT` | `8080` | the service's port on the host, on `127.0.0.1` |
| `MAILBOX_SERVICE_LOG_LEVEL`, `MAILBOX_SERVICE_SYNC_INTERVAL` | `INFO`, `300` | settings of the service |
| `MAILBOX_MCP_PORT` | `8000` | the MCP server's port on the host, on `127.0.0.1` |
| `MAILBOX_SERVICE_TOKEN` | | the API token of the user the MCP server acts as, made in the UI. The MCP server reads it under the same name. |
| `MAILBOX_MCP_BEARER_TOKEN` | | what the MCP server's own clients must send |
| `MAILBOX_MCP_ALLOWED_HOSTS` | `127.0.0.1:<port>,localhost:<port>` | the Host values its clients use |
| `MAILBOX_MCP_LOG_LEVEL` | `INFO` | the MCP server's log level |

## The images

`ghcr.io/benethos-hub/benethos-mailbox-service` and
`ghcr.io/benethos-hub/benethos-mailbox-mcp`, for `linux/amd64` and
`linux/arm64`, built by `.github/workflows/publish.yml` with the same
version as the PyPI packages:

| Event | Tags |
|---|---|
| release `v1.2.3` | `1.2.3`, `1.2`, `latest` |
| started by hand (Actions, Publish, Run workflow) | `edge` |

- The service image holds the service package, the MCP image the MCP
  server and the client, each installed from `uv.lock` without the
  development tools.
- They run as user `mailbox` (uid 10001). The compose files of
  `development/` and `production/` add a read-only root file system, no capabilities
  and `no-new-privileges`, to Caddy as well, which keeps only
  `NET_BIND_SERVICE` for its ports 80 and 443. The test mail server runs
  Stalwart without these.
- Settings come from the environment only.
- Both have a health check: the service on `GET /health`, the MCP server
  on its port.
- The compose files of `development/` and `production/` cap the log Docker
  keeps of each container at 5 files of 10 MB, the oldest dropped first
  (`x-logging`, and in `mcp.yaml` on the service itself). The test mail
  server keeps Docker's default. To keep more,
  raise `max-size` or `max-file`. To keep the log elsewhere, replace the
  driver, for example with `journald`, and read it with `journalctl
  CONTAINER_NAME=<name>`.

Built from the repository root:

```sh
docker build -f containers/images/mailbox-service/Dockerfile -t benethos-mailbox-service:local .
docker build -f containers/images/mailbox-mcp/Dockerfile -t benethos-mailbox-mcp:local .
```

The build of the service warns `SecretsUsedInArgOrEnv` for
`MAILBOX_SERVICE_KEY_PROVIDER` and `MAILBOX_SERVICE_KEY_FILE`. Docker's
check reads the names of variables alone, and both contain `KEY`. They
hold no secret: one says that the master key is a file, the other where
the file is mounted. The key itself never enters the image, it is
mounted as a secret when the container starts. The warning is left as
it is.

`ci.yml` builds both on every pull request and every push to `main`,
for arm64 as well. It checks that the
compose files in `development/` and `production/` keep every port on the loopback
address, all but Caddy's 80 and 443, production with the instances of
its example override file. It also starts the
service until its health check reports healthy, and the MCP server's
image once, for its version.
