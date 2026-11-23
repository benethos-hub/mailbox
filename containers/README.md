# <img src="../assets/brand/icon.svg" alt="" height="36" align="absmiddle"> Containers

> **Beta, version 0.11.0.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

The images, and the places they run in, each in a folder of its own.
Under each place, a folder per package. Each keeps its secrets in its
own `secrets/`, never versioned.

**Contents**

- [For development](#for-development)
- [The images](#the-images)
- [The agents](#the-agents)

```
containers/
  images/                        # what the CI builds and publishes
    mailbox-service/Dockerfile   # build context: the repository root
    mailbox-mcp/Dockerfile       # the MCP server over streamable HTTP
    mailbox-agents/Dockerfile    # the one image of every agent
  production/                    # in operation, the published images
    mailbox-service/             #   the service, Caddy and the MCP
                                 #   server instances, one compose project
      README.md                  #   how to set it up and run it, and
                                 #   what each file is
    mailbox-agents/              #   the agents, one service per agent,
                                 #   a compose project of its own
  development/                   # for development, built from the repository
    mailbox-service/
      compose.yaml               # the service, the MCP server with the
                                 #   profile mcp, ports on 127.0.0.1 only
    mailbox-agents/
      compose.yaml               # an agent against the live setup
  live/
    mailbox-agents/              # a mail server, a mailbox service and a
                                 #   model gateway of the agents' own,
                                 #   with a test account of invented mail
  test-mail-server/              # Stalwart as a mail server for tests
    compose.yaml                 #   ports on 127.0.0.1 only
    setup.sh                     #   makes the server anew
    README.md                    #   how to set it up and use it
```

| Folder | For | Images |
|---|---|---|
| `production/mailbox-service/` | running Mailbox, without a clone of the repository | from the GitHub container registry, the version named in `.env` |
| `development/mailbox-service/` | trying a change in a container | built from this repository |
| `test-mail-server/` | the adapters against a mail server of our own | Stalwart |
| `production/mailbox-agents/` | running the agents, without a clone of the repository | from the GitHub container registry, the version named in `.env` |
| `development/mailbox-agents/` | trying a change of the agents in a container | built from this repository |
| `live/mailbox-agents/` | the agents' test account | Stalwart, the mailbox service built from this repository (a published release with `MAILBOX_LIVE_SERVICE=published`), LiteLLM with its database, llama.cpp |

How to start and run the service and the MCP server, with `docker run`
or with compose:

- the service: [packages/mailbox-service/README.md](../packages/mailbox-service/README.md#container)
- the MCP server: [packages/mailbox-mcp/README.md](../packages/mailbox-mcp/README.md#container)

## For development

`development/mailbox-service/compose.yaml` builds both images from the
repository. The first start, in `development/mailbox-service/`:

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

The master key lives in
`development/mailbox-service/secrets/master_key`. The MCP server
starts with `docker compose --profile mcp up -d`. It needs
`MAILBOX_SERVICE_TOKEN` and `MAILBOX_MCP_BEARER_TOKEN` and does not
start without them. Compose reads these variables from the environment
or from an `.env` beside the file, not versioned:

| Variable | Default | What it is |
|---|---|---|
| `MAILBOX_SERVICE_HOST_PORT` | `8080` | the service's port on the host, on `127.0.0.1` |
| `MAILBOX_SERVICE_LOG_LEVEL`, `MAILBOX_SERVICE_SYNC_INTERVAL` | `INFO`, `300` | settings of the service |
| `MAILBOX_MCP_HOST_PORT` | `8000` | the MCP server's port on the host, on `127.0.0.1` |
| `MAILBOX_SERVICE_TOKEN` | | the API token of the user the MCP server acts as, made in the UI. The MCP server reads it under the same name. |
| `MAILBOX_MCP_BEARER_TOKEN` | | what the MCP server's own clients must send |
| `MAILBOX_MCP_ALLOWED_HOSTS` | `127.0.0.1:<port>,localhost:<port>` | the Host values its clients use |
| `MAILBOX_MCP_LOG_LEVEL` | `INFO` | the MCP server's log level |

## The images

`ghcr.io/benethos-hub/benethos-mailbox-service`,
`ghcr.io/benethos-hub/benethos-mailbox-mcp` and
`ghcr.io/benethos-hub/benethos-mailbox-agents`, for `linux/amd64` and
`linux/arm64`, built by `.github/workflows/publish.yml` with the same
version as the PyPI packages:

| Event | Tags |
|---|---|
| release `v1.2.3` | `1.2.3`, `1.2`, `latest` |
| release marked as a pre-release | its version only |
| started by hand on `main` (Actions, Publish, Run workflow) | `edge` |

- The service image holds the service and the common package, the MCP
  image the MCP server, the client and the common package, the agents'
  image the agents, the client and the common package. Each is installed
  from `uv.lock` without the development tools.
- All three build on `python:3.15-slim` and take `uv` from its image,
  each named by its tag and the digest of that tag. Dependabot raises
  them, also for a new build under the same tag.
- They run as uid 10001, the user `mailbox` in the images of the service
  and the MCP server and `agent` in the agents' image. The Dockerfiles
  name it by its id, so that a host or an orchestrator can see it is not
  root. The
  compose files of `development/` and `production/` add a read-only root
  file system, no capabilities and `no-new-privileges`, to Caddy as
  well, which keeps only `NET_BIND_SERVICE` for its ports 80 and 443.
  The test mail server runs Stalwart without these.
- Settings come from the environment only.
- The service and the MCP server have a health check: the service on
  `GET /health`, the MCP server on its port.
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

`ci.yml` builds all three on every pull request and every push to `main`,
for arm64 as well. It checks that the
compose files in `development/` and `production/` keep every port on the loopback
address, all but Caddy's 80 and 443, production with the instances of
its example override file. It also starts the
service until its health check reports healthy, and the MCP server's
image twice: once for its version, and once as a catalogue
(`MAILBOX_MCP_CATALOGUE=true`, over stdio), whose tools must be as
many as `docs/mailbox-mcp/mcp-tools.json` names. Its job `dockerfile-lint` reads every
Dockerfile with hadolint, and what that finds goes to Security, Code
scanning.

## The agents

The agents have their own folder under each place, and compose projects
of their own, so they reach the service only over REST and may run on
another machine:

| Folder | Ports | Compose project |
|---|---|---|
| `production/mailbox-agents/` | metrics on 9470 to 9474, 127.0.0.1 | `benethos-mailbox-agents` |
| `development/mailbox-agents/` | metrics on 9480 to 9482, 127.0.0.1 | `benethos-mailbox-agents-dev` |
| `live/mailbox-agents/` | 38080, 38081, 38400, 38465, 38993, 127.0.0.1 | `mailbox-agents-live` |

Each has its own volumes, so a trial in `development/` never reaches the
state of an installation in `production/`, and nothing in
`development/` reaches a real mailbox. How to set them up:
[production/mailbox-agents/README.md](production/mailbox-agents/README.md)
and [live/mailbox-agents/README.md](live/mailbox-agents/README.md).

For development, against the test account of the live setup:

```sh
sh containers/live/mailbox-agents/setup.sh    # once: the test account
cd containers/development/mailbox-agents
docker compose up -d --build                  # the agent counting
docker compose exec counting benethos-mailbox-agents report --agent counting
docker compose down -v                        # stop, and forget the volumes
```

An agent that asks a model reaches the gateway by its name on the live
network: `MAILBOX_AGENTS_GATEWAY_URL=http://gateway:4000/v1` in an `.env`
beside `development/mailbox-agents/compose.yaml`, which is not versioned.
The key and the model come from `agent.env`, and the `.env` may override
them.

The image `ghcr.io/benethos-hub/benethos-mailbox-agents` is built from
the repository root:

```sh
docker build -f containers/images/mailbox-agents/Dockerfile -t benethos-mailbox-agents:local .
docker run --rm benethos-mailbox-agents:local --version
```

It runs as uid 10001, keeps the state file in the volume `/data`, serves
metrics on 9464 and holds no secret. A container runs one agent, named in
its command: `worker --agent <name>`. Its health check is
`benethos-mailbox-agents health --agent <name>`, set per service in
compose.
