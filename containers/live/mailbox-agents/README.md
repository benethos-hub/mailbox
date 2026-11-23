# <img src="../../../assets/mailbox-agents/brand/icon.svg" alt="" height="36" align="absmiddle"> The live setup of the agents

A mail server, a mailbox service and a model gateway of their own, for the
live checks in `live/mailbox-agents/`. Nothing here reaches a real mailbox:
[Stalwart](https://stalw.art) holds one account made for the agents,
`agents@agents.test`, filled with invented mail, and the mailbox service is
built from this checkout, the version of the agents beside it. The
gateway is [LiteLLM](https://docs.litellm.ai) in front of Claude and of
local models under [llama.cpp](https://github.com/ggml-org/llama.cpp). It
is a manual aid, never part of `uv run pytest`.

**Contents**

- [Set it up](#set-it-up)
  - [Which model the agents use](#which-model-the-agents-use)
- [Local models](#local-models)
  - [Comparing models](#comparing-models)
  - [What a model costs](#what-a-model-costs)
- [Ports](#ports)
- [Use it](#use-it)
- [Take it down](#take-it-down)

## Set it up

Needs Docker with compose, `openssl`, `curl` and `python3`, on Linux, macOS
or in WSL. From the repository:

```
sh containers/live/mailbox-agents/setup.sh
```

The mailbox service is built from the checkout, since the agents take
the service of their own minor version only, and on a branch before a
release no published image has it. To pull a published release
instead:

```
MAILBOX_LIVE_SERVICE=published MAILBOX_VERSION=0.11.0 sh containers/live/mailbox-agents/setup.sh
```

The script makes everything anew each time. It removes the volumes of an
earlier run, then, not in this order:

- makes a test CA and a certificate for `mail.agents.test`,
- starts Stalwart in its bootstrap mode, sets host name and domain
  without ACME and DKIM, restarts it out of that mode, installs the
  certificate and creates the account,
- appends the invented mail of `mail.py` over IMAP: invoices with and
  without a PDF, a receipt that carries its invoice, near misses (a
  reminder, a quotation, an order confirmation, a payment receipt), a
  project inquiry, a newsletter, sent mail that waits for a reply and some
  that does not, a reply and an automatic answer,
- makes the mailbox service's keys and administrator, signs in to its UI
  once for the first token, connects the account, and creates the user
  `agents` with `mail.read` and `mail.write` on it and that user's token,
- starts the gateway with a master key of its own, and a local model when
  the agents are to use one (below),
- makes a key of the gateway for the agents that reaches the three
  `mail-classifier` aliases only, with a budget of 5 USD, so the lock of
  the gateway that the safety concept counts on is used here too. The
  master key stays in `secrets/gateway.env`.

### Which model the agents use

| Situation | Model | Alias in `agent.env` |
|---|---|---|
| a Claude API key is there | Claude Haiku 5.5 | `mail-classifier` |
| no key, or `MAILBOX_LIVE_LOCAL=gpu`, and NVIDIA's CDI spec on the host | local, on the graphics card | `mail-classifier-gpu` |
| no key and no CDI spec, or `MAILBOX_LIVE_LOCAL=cpu` | local, on the CPU | `mail-classifier-cpu` |

The Claude API key goes into `secrets/anthropic_api_key` or the variable
`ANTHROPIC_API_KEY`. The script keeps the file across runs.

What it makes stays in `secrets/` beside it, never versioned:

| File | Holds |
|---|---|
| `agent.env` | the settings the agents and `live/mailbox-agents/agents_smoke.py` read |
| `service-token` | the token of the user `agents` |
| `service-admin`, `stalwart-admin` | the administrators' passwords |
| `gateway.env` | the gateway's master key, the address of its database, and the Claude API key if any |
| `gateway-db.env` | the password of the gateway's database |
| `anthropic_api_key` | the Claude API key, when given |
| `master_key` | the service's master key, a test key readable by all |
| `tls/` | the test CA, and the mail server's certificate and key |

The script writes them readable by their owner only, except the CA
certificate and the service's master key, which a container reads as
another user. On a Windows drive mounted under WSL, the file system
keeps no Unix rights, and every file shows as readable by all.
Keep the checkout on the Linux file system where that matters.

## Local models

Two llama.cpp services serve the local models, each as a router that loads
one model at a time on its first request:

| Service | Profile | Image | Models in |
|---|---|---|---|
| `llama-gpu` | `gpu` | `server-cuda` | `llama/presets-gpu.ini` |
| `llama-cpu` | `cpu` | `server` | `llama/presets-cpu.ini` |

A preset section names a model and its options, the options of
`llama-server` without their dashes. The gateway reaches each model as
`gpu/<name>` or `cpu/<name>` (`litellm.yaml`). Neither service has a port
or a way out of the network `models`, which they share with the gateway
alone.

The files are fetched by a script into `models/`, which is not versioned
and survives a new setup. Each comes from a fixed revision of its
repository and is checked against the sha256 the script names:

```
sh containers/live/mailbox-agents/fetch-models.sh list        # the models it knows
sh containers/live/mailbox-agents/fetch-models.sh qwen3.5-9b  # one of them
sh containers/live/mailbox-agents/fetch-models.sh all
```

The graphics card needs the NVIDIA Container Toolkit on the host and its
CDI spec, which the service asks for as the device `nvidia.com/gpu=all`.
On Debian or Ubuntu, or in a WSL distribution of them, a script installs
both, as root and with the driver in place:

```
sudo sh containers/live/mailbox-agents/nvidia-toolkit.sh
```

It restarts neither Docker nor a container: Docker reads the spec when it
creates one. The service names the device rather than `gpus: all`, which
a Docker without the toolkit's runtime setting cannot resolve.

Start a service by hand with its profile:

```
docker compose -f containers/live/mailbox-agents/compose.yaml --profile gpu up -d llama-gpu
```

### Comparing models

`live/mailbox-agents/gold.py` writes the labels of the invented mail as gold files, and
`eval` runs an agent against them with any alias of the gateway. The key
of `agent.env` reaches the `mail-classifier` aliases only, so another
alias needs the master key of `secrets/gateway.env`:

```
uv run python live/mailbox-agents/gold.py
export MAILBOX_AGENTS_GATEWAY_KEY=$(sed -n 's/^LITELLM_MASTER_KEY=//p' \
    containers/live/mailbox-agents/secrets/gateway.env)
MAILBOX_AGENTS_MODEL=claude/haiku-5-5 uv run benethos-mailbox-agents \
    --env-file containers/live/mailbox-agents/secrets/agent.env \
    eval --agent invoices --gold containers/live/mailbox-agents/secrets/gold-invoices.jsonl \
    --reports containers/live/mailbox-agents/secrets/reports
```

A report to keep goes into the repository with
`--reports reports/mailbox-agents`. It holds numbers only.

Measured on 2026-11-20 with llama.cpp build 12464 behind LiteLLM 1.110.2,
an RTX 4070 with 12 GB and a 12th generation Core i9 with 24 threads, and
Claude through the Claude API, its seconds including the way over the
internet. Each agent ran with the prompt it had then: `invoices`
version 5 with its prompt `v4`, `inquiries` with `v3`, `awaiting_reply`
with `v1`. The versions of 0.11.0 ask with the same words, and their
runs of 2026-11-23 through `mail-classifier` are in
`reports/mailbox-agents/`. The labels agreed with the gold set, out of the 12 invented
messages for `invoices` and `inquiries` and 3 for `awaiting_reply`. An
answer the evidence check refused counts as not agreed. The fields are
the near miss `invoices` names for a message that is no invoice, such as
a reminder or a payment receipt: the right values against all it should
have filled or did fill. Every model named the 4 right ones, the rest is
a near miss named where the gold set has none. The seconds are per
message, the first message of a run waiting for a local model to load.
The aliases of the agents, `mail-classifier`, `mail-classifier-gpu` and
`mail-classifier-cpu`, gave the same labels and fields as their models,
with the agents' own key. Their seconds are in the reports under
`reports/mailbox-agents/invoices/`.

| Model | Size | invoices | inquiries | awaiting_reply | Fields | Seconds, invoices / inquiries |
|---|---|---|---|---|---|---|
| `cpu/qwen3-4b-2507` | 2.5 GB | 12 | 12 | 3 | 4 of 8 | 4.0 / 7.6 |
| `cpu/qwen3.5-4b` | 2.7 GB | 12 | 12 | 3 | 4 of 6 | 4.0 / 10.3 |
| `cpu/gemma-4-e4b` | 5.0 GB | 12 | 12 | 3 | 4 of 6 | 5.4 / 11.2 |
| `cpu/qwen3.6-35b-a3b` | 22.1 GB | 12 | 11 | 3 | 4 of 5 | 9.6 / 10.6 |
| `gpu/ministral-3-8b` | 5.2 GB | 9 | 2 | 3 | 4 of 5 | 2.7 / 2.1 |
| `gpu/qwen3.5-9b` | 5.7 GB | 12 | 12 | 3 | 4 of 6 | 3.1 / 2.4 |
| `gpu/gemma-4-12b` | 7.0 GB | 12 | 12 | 3 | 4 of 5 | 4.0 / 3.5 |
| `gpu/qwen3.6-35b-a3b` | 22.1 GB | 12 | 12 | 3 | 4 of 5 | 9.5 / 3.7 |
| `claude/haiku-5-5` | hosted | 12 | 12 | 3 | 4 of 5 | 1.4 / 1.8 |
| `claude/opus-5-5` | hosted | 12 | 12 | 3 | 4 of 4 | 1.9 / 2.3 |

What decided, measured on 2026-11-17 and 2026-11-18 with 11 messages and
prompt `v1` of `invoices`. The run of 2026-11-20 bears the choices out.
Two things differed in it: the 35B model's quote the mail does not hold
came on the CPU only, and Haiku named one near miss that Opus left
empty.

- `ministral-3-8b` words its quotes anew, so the evidence check refuses
  nine answers of `inquiries` out of eleven.
- `gemma-4-e4b` named a supplier where the gold set had none, with
  prompt `v1` of `invoices`, which still filed mail by its supplier.
- On the card, `qwen3.5-9b` agrees on every label, and llama.cpp worked
  2.4 s on an inquiry with it, for about half the electricity of the
  largest model, `qwen3.6-35b-a3b`. That one took 4.1 s and fills the card,
  `--fit` keeps the rest of its experts in main memory. With the prompt
  `v3` of `inquiries` it gave one quote the mail does not hold, on the
  card and on the CPU alike, and the evidence check refused that answer.
  So `mail-classifier-gpu` is `qwen3.5-9b` since 2026-11-18. It was the
  35B model before `v3`.
- On the CPU, `qwen3.5-4b` agrees on every label of `inquiries` and
  `invoices`, in an eighth of the 35B model's memory. The 35B model stays
  at hand as `cpu/qwen3.6-35b-a3b`, for a server with 32 GB or more.
- Haiku and Opus agree on every label and field. Haiku answers as fast
  and costs a fortieth of Opus. So `mail-classifier` is Haiku.

### What a model costs

The gateway counts what each call cost, by the price per token set for
its alias in `litellm.yaml`, and its web interface shows the sum per key
and per model. For Claude the price is the list price of the Claude API
on 2026-11-18. For a local model it is an estimate of the electricity the
call burns, without the hardware:

- the time llama.cpp spent reading and writing tokens in the runs of
  `inquiries` above, from its own timing lines,
- times the power: on the card what `nvidia-smi` read each second while
  the card worked, plus 100 W for the rest of the machine, and 220 W for
  the CPU at full load where it computes, the CPU models and the 35B
  model's experts,
- at $0.40 a kWh, about 0.35 euro.

A local model reads its system prompt from the cache of llama.cpp after
the first message, so most of what it is counted as reading costs next to
nothing. The tokens of Claude and of a local model are not the same
size: Claude counted about 3,800 tokens for an inquiry, the local models
about 570.

| Model | Dollars per million tokens in | Dollars per million tokens out | Dollars per 1,000 inquiries |
|---|---|---|---|
| `cpu/qwen3-4b-2507` | 0.042 | 1.30 | 0.19 |
| `cpu/qwen3.5-4b` | 0.044 | 1.40 | 0.27 |
| `cpu/gemma-4-e4b` | 0.029 | 1.50 | 0.30 |
| `cpu/qwen3.6-35b-a3b` | 0.057 | 1.40 | 0.26 |
| `gpu/ministral-3-8b` | 0.002 | 0.39 | 0.06 |
| `gpu/qwen3.5-9b` | 0.007 | 0.40 | 0.07 |
| `gpu/gemma-4-12b` | 0.010 | 0.50 | 0.10 |
| `gpu/qwen3.6-35b-a3b` | 0.036 | 0.64 | 0.13 |
| `claude/haiku-5-5` | 0.10 | 0.50 | 0.50 |
| `claude/opus-5-5` | 4.00 | 20.00 | 18.64 |

A dozen invented messages show a model that fails outright, not which of
the good ones is best. That takes the evaluation on real mail of
[docs/mailbox-agents/concept/evaluation.md](../../../docs/mailbox-agents/concept/evaluation.md).

## Ports

On `127.0.0.1` only:

| Port | What |
|---|---|
| 38081 | the mailbox service, its API and UI |
| 38080 | Stalwart's HTTP: JMAP and its management |
| 38993 | Stalwart's IMAP over TLS |
| 38465 | Stalwart's SMTP submission over TLS |
| 38400 | the model gateway, with the master key in `secrets/gateway.env`, and its web interface at `/ui/`: the user `admin`, the master key its password |

The gateway keeps its keys and what each spent in a database of its
own, `gateway-db`, which the web interface needs to sign in. It keeps no
prompt and no answer.

## Use it

```
uv run python live/mailbox-agents/agents_smoke.py
uv run python live/mailbox-agents/sorting.py
uv run python live/mailbox-agents/invoices.py
uv run benethos-mailbox-agents --env-file containers/live/mailbox-agents/secrets/agent.env status
uv run benethos-mailbox-agents --env-file containers/live/mailbox-agents/secrets/agent.env run --agent counting
```

`agent.env` sets the stage `shadow`. An agent that may change a message
does so only in this account. The scripts in `live/mailbox-agents/` read
`agent.env` alone, or the file `--env-file` names, not the variables of
the shell, stop with exit code 2 when the
mailbox service is not the one of this setup, on this machine at port
38081, and print the account first. A mailbox service on this machine
at another port, such as its default 8080, may be a real one.

`live/mailbox-agents/sorting.py` writes to the account: it runs `sorting` with
`sorting.json` beside this file in `shadow`, then in `full`, and puts every
message back where it was, as the inbox was before the checks, also after
a check that failed or a run cut short. The folders it made, `Providers` and two below
it, stay, as no agent may delete a folder. `setup.sh` makes the account
anew without them. `live/mailbox-agents/invoices.py` runs `invoices` in `shadow` beside
`sorting` in `full`, in both orders, and puts the mail back. Then two
checks of version 5, each with a new state file: an invoice moved by hand
into the inbox folder `Invoices/Telco`, and an invoice marked beforehand.
Every message goes back without either keyword. It asks the model of
`agent.env`, one call per message and run.

## Take it down

```
docker compose -f containers/live/mailbox-agents/compose.yaml --profile gpu --profile cpu down --volumes
```
