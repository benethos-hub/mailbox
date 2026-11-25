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
  version, stage and instance, `mailbox_agents_messages` per state,
  `mailbox_agents_oldest_pending_age_seconds`,
  `mailbox_agents_last_pass_timestamp_seconds`,
  `mailbox_agents_step_failures_total` by kind, for every step whose
  failure the log names, an update that cannot be observed and a message
  the service no longer hands out among them (2026-11-23),
  `mailbox_agents_answers_refused_total` by reason (schema, request,
  evidence), `mailbox_agents_model_calls_total`,
  `mailbox_agents_model_tokens_total` by direction,
  `mailbox_agents_model_call_seconds` and `mailbox_agents_actions_total` by
  action and whether it was carried out. A port another process holds
  ends `worker` with exit code 2, naming `METRICS_PORT`.
- **Peers over A2A:** off unless `A2A_PORT` is set, then served beside
  the metrics in the process of the worker and stopped with it, only
  with `A2A_TOKEN` ([peers over A2A](a2a.md)). A port another process
  holds ends `worker` with exit code 2, naming `A2A_PORT`.
- **Spans:** over OpenTelemetry, off unless `OTLP_ENDPOINT` is set
  (decided 2026-11-25). Then each process exports over OTLP and HTTP to
  `<endpoint>/v1/traces`, so the target is a setting and any that takes
  OTLP works: a collector, Tempo in Grafana, Langfuse, which takes OTLP at
  `/api/public/otel`. `OTLP_HEADERS_FILE` names a file of headers, one
  `name=value` per line, such as `Authorization=Basic ...` for the key of
  Langfuse: its values are secrets, masked in every error text and never
  logged. The endpoint is https, or http to this machine, or anywhere
  with `OTLP_ALLOW_HTTP`, as the headers may hold a key. `CA_FILE` holds
  for it as for the upstreams. One trace per message and process: a span
  `message` with the agent and its instance, the account and message ids, the attempt and
  the state the message is left in, below it `decision` with its source,
  its model calls and why it was refused, below that a span per part the
  agent names, for `categorization` a `dimension` with its name, how its category
  was found, the category as `label-<n>` by its place in the list and
  whether its quote was found, and a span `action` per action with its
  name, its code, the stage, whether it was held and what became of it.
  No span holds anything of a mail, a quote among it, nor the name of a
  category, a keyword or a folder of a list, which are the owner's text
  and often name a person. Several agents on one message meet by the
  message id, not by a trace handed on. A target such as Langfuse that
  shows a prompt and an answer gets neither: the spans do not carry them.
- **Cost:** read at the gateway, per key.
- **Logs:** stderr, through `logbook/` only. [docs/mailbox-agents/LOGGING.md](../LOGGING.md)
  holds the levels, the shape of a line, what never goes into one and the
  catalogue of every activity. A line is one sentence, such as
  `invoices set message m1 to done`, after an ISO time with the offset,
  the level and the source `activity.<area>.<name>`.
