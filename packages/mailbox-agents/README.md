# <img src="https://raw.githubusercontent.com/benethos-hub/mailbox/main/assets/mailbox-agents/brand/icon.svg" alt="" height="36" align="absmiddle"> Mailbox Agents

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/benethos-hub/mailbox/badges/coverage.json&logo=githubactions&logoColor=white)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/benethos-hub/mailbox?logo=opensourceinitiative&logoColor=white)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-agents?logo=python&logoColor=white)](https://pypi.org/project/benethos-mailbox-agents/)

[![PyPI benethos-mailbox-service](https://img.shields.io/pypi/v/benethos-mailbox-service?label=PyPI%20benethos-mailbox-service&logo=pypi&logoColor=white)](https://pypi.org/project/benethos-mailbox-service/)
[![Container benethos-mailbox-service](https://img.shields.io/badge/ghcr.io-benethos--mailbox--service-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-service)

[![PyPI benethos-mailbox-agents](https://img.shields.io/pypi/v/benethos-mailbox-agents?label=PyPI%20benethos-mailbox-agents&logo=pypi&logoColor=white)](https://pypi.org/project/benethos-mailbox-agents/)
[![Container benethos-mailbox-agents](https://img.shields.io/badge/ghcr.io-benethos--mailbox--agents-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-agents)

[![PyPI benethos-mailbox-mcp](https://img.shields.io/pypi/v/benethos-mailbox-mcp?label=PyPI%20benethos-mailbox-mcp&logo=pypi&logoColor=white)](https://pypi.org/project/benethos-mailbox-mcp/)
[![Container benethos-mailbox-mcp](https://img.shields.io/badge/ghcr.io-benethos--mailbox--mcp-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-mcp)

[![PyPI benethos-mailbox-client](https://img.shields.io/pypi/v/benethos-mailbox-client?label=PyPI%20benethos-mailbox-client&logo=pypi&logoColor=white)](https://pypi.org/project/benethos-mailbox-client/)

[![PyPI benethos-mailbox-common](https://img.shields.io/pypi/v/benethos-mailbox-common?label=PyPI%20benethos-mailbox-common&logo=pypi&logoColor=white)](https://pypi.org/project/benethos-mailbox-common/)

[![Sponsor](https://raw.githubusercontent.com/benethos-hub/.github/main/profile/badges/sponsor.svg)](https://github.com/sponsors/BeneODev)
[![PayPal](https://raw.githubusercontent.com/benethos-hub/.github/main/profile/badges/paypal.svg)](https://paypal.me/BeneODev)

[![benethos-mailbox-mcp on Glama](https://glama.ai/mcp/servers/benethos-hub/mailbox/badges/card.svg)](https://glama.ai/mcp/servers/benethos-hub/mailbox)

> **Alpha, version 0.11.1.** Built, and run on a test account of
> invented mail. On a real mailbox, read-only and in the stage `shadow`:
> `invoices` version 3 on 2026-11-18, `sorting` and `invoices` on
> 2026-11-22, and `invoices`, `inquiries` and `awaiting_reply` in the
> versions of 0.11.0 on 2026-11-23. None changed anything. Names, settings and
> the state file may still change from one version to the next. The
> design is written down in
> [docs/mailbox-agents/CONCEPT.md](https://github.com/benethos-hub/mailbox/blob/main/docs/mailbox-agents/CONCEPT.md).
> Do not point it at a mailbox you care about.

The AI agents of Mailbox, on PyPI as `benethos-mailbox-agents`. They
work on a mailbox continuously. Each one looks at mail as it arrives or
leaves, decides one narrow question about it and takes one
reversible action: a keyword, or a move to a folder. The first ones sort
invoices, track sent mail that still waits for a reply, recognise project
inquiries and file the mail of listed senders into folders.

Mailbox is self-hosted and has five packages. The agents do not work
alone. They need the service, which runs on your own machine or server
and holds the connections to your mail accounts, and a model gateway.
**Install the service first:** [Install](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-service/README.md#install)
and [First start](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-service/README.md#first-start)
in its README. Up to 0.2.0 the agents were a repository of their own,
[benethos-hub/mailbox-agents](https://github.com/benethos-hub/mailbox-agents),
which keeps their history and their changelog up to that release.

<picture>
  <source srcset="https://raw.githubusercontent.com/benethos-hub/mailbox/main/assets/mailbox-agents/architecture/architecture-dark.png" media="(prefers-color-scheme: dark)">
  <img src="https://raw.githubusercontent.com/benethos-hub/mailbox/main/assets/mailbox-agents/architecture/architecture.png" alt="The mailbox service hands the change feed and a message to Mailbox Agents and takes a keyword or a move back. Each agent takes a message through four steps: trigger, selection, decision and effect. For a decision it asks a model once through an OpenAI-compatible gateway, without tools. The mailbox service stands on the mail accounts, the gateway on local or hosted model backends.">
</picture>

A message comes to an agent through the change feed of the service. The
agent asks a model through the gateway, and hands a keyword or a move
back to the service.

| Package | Its part | How you get it |
|---|---|---|
| [`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service) | It holds the connections to your mail accounts and their credentials, encrypted. It offers one REST API for every provider and decides what a token may do. It has to be running. | [Getting started](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-service/README.md#getting-started), before the agents |
| **`mailbox-agents`** | This package. Small AI agents that sort and mark mail. | [Install](#install) |
| [`mailbox-client`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-client) | The Python client of the REST API. The agents make every request with it. | installed with the agents |
| [`mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp) | The MCP server. It turns the REST API into tools for an AI assistant. The agents do not use it. | not needed here |
| [`mailbox-common`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-common) | What the service, the MCP server and the agents share. | installed with this package |

> **The agents take only a service of their own version:** before 1.0
> the same minor version, from 1.0 the same major version and a minor
> version no older than theirs. An agent stops at any other. The agents
> 0.2.0, released before they joined this repository, take the service
> 0.8 and 0.9 only.

What the project is for: [the repository's README](https://github.com/benethos-hub/mailbox#readme).

**Contents**

- [How it works](#how-it-works)
- [Install](#install)
- [Development](#development)
- [Licence](#licence)

## How it works

- Mail is reached only through the REST API of the service, with its
  Python client `benethos-mailbox-client`.
- A language model is reached only through an OpenAI-compatible gateway,
  with one call per message, a JSON schema for the answer and no tools.
- Everything else is deterministic code: which messages an agent looks at,
  what a rule says, whether a quote from the model is really in the mail,
  and which action follows.
- Every agent runs in a process of its own, with its own credentials and
  its own SQLite state file. The state file holds ids and decisions, never
  the text of a mail.
- A new agent starts in the stage `shadow`, where it only records what it
  would do. The stages `keyword` and `full` follow after it was measured
  against labelled mail.

## Install

The package is `benethos-mailbox-agents` on PyPI, for Python 3.11 or
newer:

```
uvx benethos-mailbox-agents --version
```

In operation each agent runs as a container of the image
`ghcr.io/benethos-hub/benethos-mailbox-agents`.
[containers/production](https://github.com/benethos-hub/mailbox/blob/main/containers/production/mailbox-agents/README.md)
holds the compose file and says how to set it up. Every setting is listed
in
[docs/mailbox-agents/concept/configuration.md](https://github.com/benethos-hub/mailbox/blob/main/docs/mailbox-agents/concept/configuration.md).

## Development

Needs [uv](https://docs.astral.sh/uv/) and a clone of the repository, from
whose root the commands run.

```
uv sync
uv run benethos-mailbox-agents --version
uv run pytest -q packages/mailbox-agents/tests
```

The suite is offline. The live checks run against a mail server and a
mailbox service of their own with invented mail, see
[containers/live](https://github.com/benethos-hub/mailbox/blob/main/containers/live/mailbox-agents/README.md).

## Licence

MIT, see [LICENSE](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-agents/LICENSE).
