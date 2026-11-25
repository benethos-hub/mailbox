# Concept of Mailbox Agents

> **Status: alpha, 2026-11-23. The runtime and the agents `counting`, `invoices`,
> `awaiting_reply`, `inquiries` and `sorting` are built and run against a
> test account of invented mail. On a real mailbox, read-only and in
> `shadow`: `invoices` version 3 on 2026-11-18, `sorting` and `invoices`
> on 2026-11-22, and `invoices`, `inquiries` and `awaiting_reply` in the
> versions of 0.11.0 on 2026-11-23. None changed anything, and none acts
> on a real mailbox yet.** A statement about another system that nobody has checked
> yet is marked **(to verify)**, and a choice that is still open is listed
> in [the agents' roadmap](../roadmap/agents.md#open-questions) rather than written as fact.

This file is the overview: what the project is, what is in scope, its
names and the decisions that matter most. Each topic has a file of its
own in [concept/](concept/), and so has each agent. They move with the
code.

## The topics

| Topic | In short |
|---|---|
| [The mailbox service](concept/mailbox-service.md) | The upstream: rights, the change feed, what the service exposes and what is still to verify. |
| [The model gateway](concept/model-gateway.md) | The OpenAI-compatible gateway, structured output, local and hosted models. |
| [The agent contract](concept/agent-contract.md) | `Agent`, its triggers, actions and limits, the context it is handed. |
| [Runtime](concept/runtime.md) | The worker loop, the steps of a message, stages, the commands and `report`. |
| [State](concept/state.md) | The SQLite state file, its tables and migrations. |
| [Safety](concept/safety.md) | Untrusted mail, evidence, sender rules, reversibility, secrets. |
| [Evaluation](concept/evaluation.md) | Gold sets, scoring, reports of numbers only. |
| [Configuration](concept/configuration.md) | Every setting. |
| [Operation](concept/operation.md) | Containers, health, metrics, cost, logs. |
| [Testing](concept/testing.md) | The offline suite and the live checks. |

## The agents

| Agent | Question | Status | Its file |
|---|---|---|---|
| `counting` | none: counts what arrives and is sent, changes nothing | built | [agent-counting.md](concept/agent-counting.md) |
| `invoices` | is this an invoice? It moves one into the subfolder of the folder it lies in | built, version 6, prompt `v5` | [agent-invoices.md](concept/agent-invoices.md) |
| `awaiting_reply` | does this sent message wait for an answer? | built, version 2, prompt `v2` | [agent-awaiting-reply.md](concept/agent-awaiting-reply.md) |
| `inquiries` | is this a project inquiry, and what does it say? | built, version 2, prompt `v4` | [agent-inquiries.md](concept/agent-inquiries.md) |
| `sorting` | which category of its list does the message belong to, in each dimension of the list, and what follows from it? | built, version 3: dimensions run in order, the sender rules in code, a model only for a message they do not settle and only where a category has a topic (2026-11-24), what follows from a category named in its list (2026-11-25). `invoices` then files an invoice within the folder `sorting` put it in | [agent-sorting.md](concept/agent-sorting.md) |

## Beside the concept

| Document | What it holds |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The layers, the modules and the design decisions behind them. |
| [LOGGING.md](LOGGING.md) | What an agent writes to its log, and the catalogue of every line. |
| [RELEASING.md](../RELEASING.md) | The steps of a release, in order. |
| [Roadmap of the agents](../roadmap/agents.md) | What is built, what comes next and the open questions. |

## Purpose

A set of small agents that work on a mailbox continuously: each one looks at
mail as it arrives or leaves, decides one narrow question about it, and takes
one reversible action. The first ones sort invoices, track sent mail that
is still waiting for a reply, recognise project inquiries and file the mail
of listed senders into folders.

The agents reach mail only through the REST API of a mailbox service, with
its Python client `benethos-mailbox-client`. They reach a language model only
through an OpenAI-compatible gateway. Everything else is deterministic code
in this repository.

The project exists for two reasons. Mail that holds customer correspondence
should be processed by code its owner can read, on a machine its owner runs.
And a claim about how well an agent works should be a number measured
against labelled mail, not an impression.

## Scope

**In scope:** reading the change feed of the mailbox service, selecting the
messages an agent cares about, classifying a message with rules and with one
model call, extracting fields from it, setting and removing a keyword, moving
a message to a folder, keeping per-agent state in SQLite, measuring every
agent against a labelled set of mail, and exposing health and metrics.

**Out of scope (non-goals):**

- Sending mail, and deleting mail, to the trash or for good.
- A model that chooses tools. No step in this project hands tools to a
  model. Work of that kind belongs to a separate agent server, which a
  later step may call over HTTP ([roadmap](../roadmap/agents.md#next)).
- An agent framework. One call with a schema needs none
  ([model gateway](concept/model-gateway.md)).
- Talking IMAP, SMTP or a provider API. The mailbox service does that.
- Parsing MIME or decoding character sets. The mailbox service does that
  too. A mail with an HTML body alone reaches an agent with the text a
  reader sees of it, as the mail page and the MCP server show it
  ([mailbox service](concept/mailbox-service.md)).
- A conversation or session store. Every model call is a single turn
  ([state](concept/state.md)).
- A user interface. The mailbox is the interface: a keyword or a folder is
  what a person sees, and taking a keyword off is how a person answers.

**Deliberately gated rather than excluded:** writing a reply as a draft. It
needs a right the first agents do not get, and it comes after the agents
that only read and sort have been measured.

## Naming

The name is plural (decided 2026-11-18): the project holds several agents
on one runtime, and each process runs one of them.

| Where | Name |
|---|---|
| Display name, in the README and the brand | Mailbox Agents |
| Repository | `benethos-hub/mailbox`, folder `packages/mailbox-agents` |
| PyPI distribution | `benethos-mailbox-agents` |
| Import package | `benethos_mailbox_agents` |
| Console script | `benethos-mailbox-agents` |
| Container image | `ghcr.io/benethos-hub/benethos-mailbox-agents` |
| Settings prefix | `MAILBOX_AGENTS_` |
| Agent names | a lowercase letter, then lowercase letters, digits and `_`: `invoices`, `awaiting_reply`, `inquiries` |

## What matters most

- **Shadow first.** A new agent, and one whose prompt or model changed,
  starts in the stage `shadow`: it records what it would do and changes
  nothing. `keyword` sets keywords, `full` also moves. A change of stage on
  a real mailbox is the owner's decision ([runtime](concept/runtime.md)).
- **A model that reads mail has no tools.** It answers in a fixed schema,
  code acts on the answer ([agent contract](concept/agent-contract.md)).
- **A value needs evidence.** Every label and field carries a quote that
  code finds in the mail, word for word, before anything is done with it
  ([safety](concept/safety.md)).
- **The sender is not proof.** Only a rule naming an address or a pattern
  moves a message. A domain rule and a model's choice mark only, with one
  exception since 2026-11-18: `invoices` moves a message its model takes
  for an invoice, into the subfolder of a folder it looks in, and out of
  the inbox only into the inbox folder the owner set. The model names no
  folder ([invoices](concept/agent-invoices.md)). A second since
  2026-11-24: `sorting` acts on the group its model chose by the group's
  topic where the owner set `"by_topic": "act"` for it, with a quote
  found in the mail. The model names a group of the list, never a
  folder, and a held group stays held
  ([sorting](concept/agent-sorting.md)).
- **Reversible only.** Every action records what was there before.
- **Nothing of a mail in a log line, secrets never travel**
  ([safety](concept/safety.md), [LOGGING.md](LOGGING.md)).
- **Measured, not believed.** Every agent is scored against labelled mail
  beside its rules without a model ([evaluation](concept/evaluation.md)).
