# Concept: configuration

Part of the [concept](../CONCEPT.md).

All settings carry the prefix `MAILBOX_AGENTS_` and come from the environment
or from one `.env` file, read with pydantic-settings (decided 2026-11-17)
through `FileSettings` of `mailbox-common`, as the service and the MCP
server read theirs.
A process runs one agent, so one environment describes one agent. A secret
may be given as a file with the suffix `_FILE`. An empty line, such as
`MAILBOX_AGENTS_CATEGORIZATION_FILE=`, counts as not set for a secret, a file,
`KEYWORD`, `INSTANCE`, `OTLP_ENDPOINT` and `A2A_URL`.

| Setting | Meaning |
|---|---|
| `SERVICE_URL`, `SERVICE_TOKEN` | the mailbox service and this agent's token |
| `SERVICE_ALLOW_HTTP` | allow http to another machine, as between two containers, `false` when unset |
| `GATEWAY_URL`, `GATEWAY_KEY` | the model gateway and this agent's key, required of an agent that asks a model, `categorization` only when a recognizer of its list asks one, a topic or `invoice` (2026-11-25). The URL carries no user or password (2026-11-23) |
| `GATEWAY_ALLOW_HTTP` | allow http to another machine for the gateway, as between two containers, `false` when unset. https or http to this machine otherwise |
| `GATEWAY_TIMEOUT_SECONDS` | how long one model call may take, `120` when unset |
| `MODEL` | the alias the gateway resolves |
| `CA_FILE` | a file of PEM certificates of the authorities https to the service and the gateway trusts, in place of the public roots, for an upstream with a certificate of an own CA (2026-11-19). Read at the start: a missing file or one without a certificate stops it. Unset: the roots of certifi. `SSL_CERT_FILE` and the proxy variables are never read |
| `ACCOUNTS` | the accounts to work on, comma separated, all the user may read when unset |
| `STAGE` | `shadow`, `suggest` or `full`, `shadow` when unset. `keyword`, the word of `suggest` before 2026-11-27, is read as `suggest` |
| `KEYWORD` | the keyword the agent sets, the agent's own default when unset. Lower case letters, digits and dashes, such as `agent-invoice` (2026-11-19). It belongs in the env file of one agent: an agent whose keyword is another agent's default does not start, and `status` warns when it is set |
| `INSTANCE` | one of several processes of one agent, each with a list of its own, such as `partner` for `categorization` (2026-11-25). Its state file is `<agent>-<instance>.db`, its default keyword the agent's with `-<instance>` after it, its log lines, `status` and `report` name it `<agent>/<instance>`, its metrics name it in `mailbox_agents_info`. Lower case letters, digits and dashes, a letter first, at most 40. Unset: the agent alone, as before |
| `POLL_SECONDS`, `TICK_SECONDS` | how often the feed is read and the clock asked, `60` and `900` when unset |
| `MAX_ATTEMPTS` | failed attempts before a message is `failed`, a refused answer or a step the service refused among them, and the passes in a row that end at one message ([runtime](runtime.md)), `5` when unset |
| `BACKOFF_CEILING_SECONDS` | the longest wait between two attempts, `3600` when unset |
| `BACKFILL_DAYS` | the days the command `backfill` takes up without `--days`, and the window taken up after an expired feed state, `7` when unset |
| `DATA_DIR` | where the state files live, one `<agent>.db` per agent. Unset: the data folder of where the settings come from, below |
| `PROMPT_RETENTION_DAYS` | [state](state.md), `0` when unset |
| `METRICS_PORT` | [operation](operation.md), `0` serves no endpoint |
| `OTLP_ENDPOINT` | where spans go over OTLP and HTTP, `<endpoint>/v1/traces` ([operation](operation.md)). Unset: no spans leave the process |
| `OTLP_HEADERS_FILE` | a file of headers for it, one `name=value` per line, such as a key. Never logged |
| `OTLP_ALLOW_HTTP` | http to another machine as well, `false` when unset |
| `A2A_PORT`, `A2A_HOST`, `A2A_URL`, `A2A_TOKEN`, `A2A_TOKEN_FILE` | the entrance for peers over A2A, off unless a port is set, and then only with a token ([peers over A2A](a2a.md)) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR`, `INFO` when unset |

`SERVICE_TOKEN_FILE`, `GATEWAY_KEY_FILE` and `A2A_TOKEN_FILE` name the
file a secret is read from. A secret given directly wins over its file. The file is read as
UTF-8, a mark of UTF-8 at its start left out. A secret is printable ASCII,
as a header of HTTP carries it, and any other stops the start, naming the
setting and never the value.

Settings of one agent, such as
`REPLY_DAYS`, `INQUIRIES_PATTERNS_FILE` and `CATEGORIZATION_FILE`, are named in
the agent's file, `agent-<name>.md` beside this one.

## Where the settings and the state files are

As the service finds its own (2026-11-22), first found first:

| Where | The settings file | The state files when `DATA_DIR` is unset |
|---|---|---|
| named on purpose, by `--env-file` or `MAILBOX_AGENTS_ENV_FILE` | that file, which must exist | `data/benethos-mailbox-agents` beside it |
| the layout of this repository, `config/benethos-mailbox-agents` or `data/benethos-mailbox-agents` in the working directory | `config/benethos-mailbox-agents/.env`, read when it exists | `data/benethos-mailbox-agents` |
| else, installed alone | `.env` in the config folder of the operating system | the data folder of the operating system |

Outside the layout of the repository a relative path in the settings,
`DATA_DIR`, `CATEGORIZATION_FILE`, `INQUIRIES_PATTERNS_FILE`, `CA_FILE` and the
`_FILE` of a secret, counts from the folder of the settings file. In it,
it counts from the working directory. A container sets `DATA_DIR` to
`/data`. `paths` names what applies.

Before, the state files lay in `data/` below the working directory. When
one is still there and none at the new place, a command that writes the
state file does not start and names both, so the cursor and the
decisions in it are not left behind: move it, or set `DATA_DIR` to its
folder. `paths` and `status` name it too.
