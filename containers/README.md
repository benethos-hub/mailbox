# Containers

> **Alpha, version 0.2.0.** Usable with real accounts for testing. The
> API and the configuration may still change. Stored data is carried
> forward by migrations.

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
    mcp.yaml                     #   the template of an MCP server
                                 #   instance, run from
                                 #   compose.override.yaml (profile mcp)
    caddy.d/                     #   the routes of Caddy to instances
    setup.sh                     # the first start, see its README.md
  dev/                           # for development, built from the repository
    compose.yaml                 # the service, the MCP server with the
                                 #   profile mcp, ports on 127.0.0.1 only
  test-mail-server/              # Stalwart as a mail server for tests,
                                 #   set up by setup.sh, see its README.md
```

| Folder | For | Images |
|---|---|---|
| `production/` | running Mailbox, without a clone of the repository | from the GitHub container registry, the version named in `.env` |
| `dev/` | trying a change in a container | built from this repository |
| `test-mail-server/` | the adapters against a mail server of our own | Stalwart |

How to start and run the service and the MCP server, with `docker run`
or with compose:

- the service: [packages/mailbox-service/README.md](../packages/mailbox-service/README.md#container)
- the MCP server: [packages/mailbox-mcp/README.md](../packages/mailbox-mcp/README.md#container)

## The images

`ghcr.io/benethos-hub/benethos-mailbox-service` and
`ghcr.io/benethos-hub/benethos-mailbox-mcp`, for `linux/amd64` and
`linux/arm64`, built by `.github/workflows/publish.yml` with the same
version as the PyPI packages:

| Event | Tags |
|---|---|
| release `v1.2.3` | `1.2.3`, `1.2`, `latest` |
| started by hand (Actions, Publish, Run workflow) | `edge` |

- Only the one package goes into each image, installed from `uv.lock`
  without the development tools.
- They run as user `mailbox` (uid 10001). The compose files add a
  read-only root file system, no capabilities and `no-new-privileges`.
- Settings come from the environment only.
- Both have a health check: the service on `GET /health`, the MCP server
  on its port.
- The compose files cap the log Docker keeps of each container at 5
  files of 10 MB, the oldest dropped first (`x-logging`). To keep more,
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
compose files in `dev/` and `production/` keep every port on the loopback
address, all but Caddy's 80 and 443, production with the instances of
its example override file. It also starts the
service until its health check reports healthy.
