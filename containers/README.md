# Containers

> **Pre-alpha, version 0.1.0.** Not ready for production use: the API,
> the stored data and the configuration may change without notice.

One folder per image, and a compose file for running them.

```
containers/
  compose.yaml                   # the service, and the MCP server with the
                                 #   profile mcp, ports on 127.0.0.1 only
  benethos-mailbox-service/
    Dockerfile                   # build context: the repository root
  benethos-mailbox-mcp/
    Dockerfile                   # the MCP server over streamable HTTP
  secrets/                       # local, not versioned: master_key
```

How to start and run them, with `docker run` or with compose:

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
- They run as user `mailbox` (uid 10001). The compose file adds a
  read-only root file system, no capabilities and `no-new-privileges`.
- Settings come from the environment only.
- Both have a health check: the service on `GET /health`, the MCP server
  on its port.

Built from the repository root:

```sh
docker build -f containers/benethos-mailbox-service/Dockerfile -t benethos-mailbox-service:local .
docker build -f containers/benethos-mailbox-mcp/Dockerfile -t benethos-mailbox-mcp:local .
```

`ci.yml` builds both on every push, for arm64 as well. It checks that the
compose file keeps every port on the loopback address. It also starts the
service until its health check reports healthy.
