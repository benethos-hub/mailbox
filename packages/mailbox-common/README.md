# <img src="https://raw.githubusercontent.com/benethos-hub/mailbox/main/assets/brand/icon.svg" alt="" height="36" align="absmiddle"> Mailbox Common

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/benethos-hub/mailbox/badges/coverage.json&logo=githubactions&logoColor=white)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/benethos-hub/mailbox?logo=opensourceinitiative&logoColor=white)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-common?logo=python&logoColor=white)](https://pypi.org/project/benethos-mailbox-common/)

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

> **Beta, version 0.11.1.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

What
[`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service),
[`mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp)
and
[`mailbox-agents`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-agents)
of [Mailbox](https://github.com/benethos-hub/mailbox) need alike, held
once, on PyPI as `benethos-mailbox-common`. The MCP server and the
agents cannot see the service, so what they all use lives here.

Mailbox is self-hosted and has five packages. This one is installed
with the service, the MCP server and the agents and is not meant to be
used on its own. To use Mailbox, start with the service:
[Install](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-service/README.md#install).

| Package | Its part | How you get it |
|---|---|---|
| [`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service) | It holds the connections to your mail accounts and their credentials, encrypted. It offers one REST API for every provider and decides what a token may do. | [Getting started](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-service/README.md#getting-started) |
| [`mailbox-client`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-client) | The Python client of the REST API. It does not use this package. | from PyPI: [Install](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-client/README.md#install) |
| [`mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp) | The MCP server. It turns the REST API into tools for an AI assistant, on top of the client. | after the service: [Getting started](https://github.com/benethos-hub/mailbox/blob/main/packages/mailbox-mcp/README.md#getting-started) |
| **`mailbox-common`** | This package. What the service, the MCP server and the agents share. | installed with each of them |
| [`mailbox-agents`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-agents) | Small AI agents that sort and mark mail, on top of the client. | installs this package |

What the project is for: [the repository's README](https://github.com/benethos-hub/mailbox#readme).

**Contents**

- [What it holds](#what-it-holds)
- [Install](#install)
- [Versions](#versions)
- [Licence](#licence)

## What it holds

Five groups, one per concern. A group stands alone: a module imports
only inside its group.

| Group | What it holds | Needs |
|---|---|---|
| `mail` | Mail itself, nothing of Mailbox. The visible text of an HTML body, as the mail page of the service shows it and the model of the MCP server reads it. Addresses in a readable form. The marks a person sees on a message, and their words. | the standard library |
| `log` | The line of a log: its format, its levels and its time, plain, in colour on a terminal or as JSON. Secrets are noted once and masked in every text. | the standard library |
| `paths` | Where a program keeps its files: the folders of the operating system for settings and data, and an exclusive lock on a file. | the extra `paths`, which brings platformdirs |
| `settings` | A program's settings, from the command line, the environment, a settings file and the defaults. | the extra `settings`, which brings pydantic-settings |
| `values` | Values written one way: JSON compact to send and canonical to hash, sizes, a pause that doubles up to a ceiling, ids, tokens and digests, and text on one line. | the standard library |

So the service, the MCP server and the agents turn an HTML mail into
the same text, write the same log line and mask the same secrets.

It sees neither the service, nor the MCP server, nor the client, nor
the agents.

## Install

There is nothing to install. The service, the MCP server and the
agents bring it, with the extras they need.

On its own it needs the standard library alone. An extra is named
after its group, `postgres` brings the driver of PostgreSQL for the
group `storage`, and `all` brings every extra:

```sh
uv add "benethos-mailbox-common[all]"      # or: pip install "benethos-mailbox-common[all]"
```

A module of a group that misses its extra says which one.

## Versions

It is built for the packages of this repository. Its modules, groups
and extras may change between versions without notice. It carries the
version of the other packages, and the service, the MCP server and the
agents pin it to their own. Its public interface is recorded in
[`docs/mailbox-common/common-interface.json`](https://github.com/benethos-hub/mailbox/blob/main/docs/mailbox-common/common-interface.json),
which a test holds to the code.

## Licence

MIT, see [LICENSE](https://github.com/benethos-hub/mailbox/blob/main/LICENSE).
