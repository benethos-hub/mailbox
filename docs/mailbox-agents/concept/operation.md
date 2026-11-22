# Concept: operation

Part of the [concept](../CONCEPT.md).

- **Release:** `publish.yml` publishes a GitHub release to PyPI as
  `benethos-mailbox-agents` and to ghcr.io as the image of the same name,
  for amd64 and arm64, once the CI of its commit on `main` is green. The
  tag is `v` and the version of `pyproject.toml`. A manual run is the
  trial: it checks the package without uploading and pushes the image as
  `edge`. [RELEASING.md](../../RELEASING.md) has the steps. The agents
  take the mailbox service of their own version
  ([mailbox service](mailbox-service.md#the-version-of-the-service)).
- **Container:** non-root (uid 10001), read-only root file system, no
  capabilities, `no-new-privileges`, one volume for the state file, the
  token and the key mounted as files and named in `*_FILE` settings, at
  most five log files of 10 MB. One Compose service per agent from the same
  image, each behind a profile of its own name, `restart: unless-stopped`,
  its health check `health --agent <name>`. The image is named by
  `MAILBOX_VERSION`, best as the version with the digest of the
  release, `<version>@sha256:<digest>`: a tag on ghcr.io can be moved, a
  digest cannot (2026-11-19). The live setup pins the images it pulls from other projects so.
- **Health:** `health --agent <name>` exits 0 while the loop's last sign
  of progress, written to the state file after each message and at the end
  of each pass, is younger than three poll intervals plus one model call
  (`3 * POLL_SECONDS + GATEWAY_TIMEOUT_SECONDS`), and 1 otherwise. It reads
  the state file beside the running agent. A process that is alive and
  stuck is unhealthy. One whose gateway is away is not, its loop goes on.
- **Metrics:** an HTTP endpoint in the Prometheus text format on
  `METRICS_PORT`, served with the `prometheus-client` package (decided
  2026-11-17), one registry per process: `mailbox_agents_info` with agent,
  version and stage, `mailbox_agents_messages` per state,
  `mailbox_agents_oldest_pending_age_seconds`,
  `mailbox_agents_last_pass_timestamp_seconds`,
  `mailbox_agents_step_failures_total` by kind,
  `mailbox_agents_answers_refused_total` by reason (schema, request,
  evidence), `mailbox_agents_model_calls_total`,
  `mailbox_agents_model_tokens_total` by direction,
  `mailbox_agents_model_call_seconds` and `mailbox_agents_actions_total` by
  action and whether it was carried out. A port another process holds
  ends `worker` with exit code 2, naming `METRICS_PORT`.
- **Cost:** read at the gateway, per key.
- **Logs:** stderr, through `logbook/` only. [docs/mailbox-agents/LOGGING.md](../LOGGING.md)
  holds the levels, the shape of a line, what never goes into one and the
  catalogue of every activity. A line is one sentence, such as
  `invoices set message m1 to done`, after an ISO time with the offset,
  the level and the source `activity.<area>.<name>`.
