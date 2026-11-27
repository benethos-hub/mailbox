# Architecture of Mailbox Agents

```
                 mail servers
                      ^
                      |
        +----------------------------+
        | mailbox service            |   accounts, change feed,
        | (packages/mailbox-service) |   one user per agent, audit
        +-------------^--------------+
                      | REST, benethos-mailbox-client
        +-------------+--------------+
        | mailbox-agents             |   one image,
        |   categorization  + SQLite |   one process per agent,
        |   awaiting_reply  + SQLite |   one state file per agent
        |   inquiries       + SQLite |
        |   counting        + SQLite |
        |   filing          + SQLite |
        |   forwarding      + SQLite |
        +-------------+--------------+
                      | OpenAI-compatible HTTP, one key per agent
        +-------------v--------------+
        | model gateway              |   aliases, allowlist and
        | (not part of this project) |   budget per key
        +-------------+--------------+
                      |
            model backends, local or hosted
```

How one message passes through one agent:

```
trigger          selection        decision                  effect
---------------------------------------------------------------------------
change feed  ->  code: is    ->   1. baseline (rules)   ->  shadow
tick (clock)     this mine?       2. model, one call,       suggest
                                     schema, no tools       full
                                  3. check in code:
                                     schema, evidence

             every step is recorded in the agent's state file
```

## Layers

Each layer imports only the layers below it.
`packages/mailbox-agents/tests/test_layers.py` holds the order, a row per
top-level module.

- `errors`, `records` and `logbook` import nothing of the package.
  `settings` stands on `errors`.
- `contract` and `store` stand on these. `sources` and `llm`, the two
  upstreams, stand on `errors` and `records` alone. `telemetry`, the
  spans, stands on `errors`, `records` and `settings`.
- `runtime` holds everything below it but `sources`, `telemetry` among
  it.
- `agents` see `contract`, `records`, `settings` and `errors`, never
  `sources`, `llm`, `store` or `runtime`.
- `evaluation` stands on `runtime` and `store`.
- `peers`, the entrance for peers over A2A, stands on `errors`,
  `records` and `settings`: it is handed what classifies a message.
- `cli` wires everything on top, and `__main__` calls it.

Of the other packages of the repository, the agents take the client,
in `sources/mailbox.py` alone, and `mailbox-common` with its extras
`paths` and `settings`: the lines of the log, the masking of secrets,
the digest of a secret, text, pauses, the plain text and the addresses
of a mail, settings from a file, the folders of the operating system for
settings and state files and the lock of a state file, as the service
and the MCP server have them. The
table `CONFINED` of `test_layers.py` names the modules that import each.

## The rules of the repository

The rules of the repository,
[sections 5 to 17](../mailbox-service/architecture/rules.md), hold for
the agents too, with four differences of their own design:

- **Concurrency (7.4).** The agents run on asyncio, one event loop per
  process, not on anyio
  ([their CLAUDE.md](../../packages/mailbox-agents/CLAUDE.md)).
- **The homes of a library (7.1).** The agents talk to two upstreams,
  each in a module of its own. So httpx has two homes,
  `sources/mailbox.py` and `llm/gateway.py`, and ssl three, with
  `settings/model.py`, which reads the CA of the setup. `CONFINED`
  names them.
- **Imports through `__init__.py` (5.3).** `contract`, `records`,
  `errors`, `logbook`, `settings`, `store`, `telemetry`, `peers` and `cli` offer
  their names there. `runtime`, `llm`, `sources` and `evaluation` offer none, and
  their callers import the module.
- **The architecture test (13).** It is `tests/test_layers.py`, beside
  `tests/test_code_rules.py` for the size of modules and classes (15).

The tests at the root check the agents as they check the other
packages: the boundaries (9), the module tree above (3), and the rules
for the tests (13).

## Modules

```
packages/mailbox-agents/src/benethos_mailbox_agents/
  cli/            # the console script: worker, run, backfill, report, eval,
                  # check, status, paths, health, and the wiring of one
                  # session
  __main__.py     # enables `python -m benethos_mailbox_agents`
  errors/         # the error hierarchy, one module per error, its texts
                  #   masked with redact of mailbox-common
  settings/       # settings resolution, secrets from files, and where the
                  # settings file and the state files are
  logbook/        # every line on stderr as an activity of its catalogue,
                  # and what a line may never carry (docs/mailbox-agents/LOGGING.md)
  contract/       # Agent (ABC) and its two kinds Classifier and Actor,
                  # actions.py the actions, how each is taken back and
                  # what each stage carries out, Trigger, Limits,
                  # Requires, the
                  # Context an agent is handed with its protocols Model,
                  # Reader and Items, the registry of agents, prompt loading,
                  # and what two kinds of agent share: Placed, the path of
                  # a folder, the keywords a list waits for
  records/        # the models passed between layers: MessageRef, Decision,
                  # Evidence, StepResult, OpenItem, Classified and
                  # NotClassified, and what an agent sees of
                  # a mailbox: Event, MailMessage, Address, Attachment,
                  # FolderRef, Thread
  sources/
    mailbox.py    # the only module importing benethos_mailbox_client
    versions.py   # which versions of the service the agents take
    answers.py    # an answer made sound, a record of what the API describes
  llm/
    gateway.py    # the only module that talks to the model gateway
    evidence.py   # whether a quote is in the mail the model was given
  telemetry/
    spans.py      # the spans as the rest sees them, off by default
    otlp.py       # the only module importing opentelemetry: OTLP over
                  # HTTP when an endpoint is set
  peers/
    a2a.py        # the only module importing a2a-sdk, Starlette and
                  # uvicorn: the entrance over A2A, served when a port
                  # is set
  store/          # SQLite, one file per agent: store.py opens and
                  # migrates it, rows.py is what its parts stand on,
                  # messages.py, steps.py, actions.py, items.py and
                  # calls.py are a part each, migrations/ the schema's
                  # steps, versions/ a module per step
  runtime/        # worker loop, feed reader, tick, step runner, the model
                  # calls of one message, open items over the state file,
                  # the read-only mailbox, action executor, the mailbox
                  # it writes to (writer.py), what becomes of an action
                  # (outcomes.py), the draft of a forward (drafts.py),
                  # readiness, health, metrics, a classification for a
                  # peer
  evaluation/     # the gold format, the run, scoring per label and per
                  # field, the report
  agents/         # one package per agent. agent.py holds its one
                  # Agent subclass, no side effects at import. An agent
                  # that asks a model has schema.py, what it must answer,
                  # and prompts/, its system prompts as Markdown, each
                  # with a version
    counting/     # agent.py alone: it only counts
    inquiries/    # schema.py, prompts/, baseline.py the question by
                  # rules, patterns.py the domains and phrases it knows
    awaiting_reply/  # schema.py, prompts/, text.py what its rules read
                  # in a mail
    categorization/  # groups.py the list of groups, by senders and
                  # topics, dimensions.py and lists.py the list of the
                  # chain, choice.py the base of a recognizer,
                  # recognizers.py and actions.py its registers,
                  # invoice.py and invoice_rules.py the recognizer
                  # invoice, alone.py a part scored alone, plan.py one
                  # message through the chain, summary.py its report,
                  # schema.py, prompts/ the choice by a topic and the
                  # recognizer invoice
    filing/       # rules.py the list of keywords and folders, agent.py
                  # the actor that files by it
    forwarding/   # rules.py the list of keywords and addresses,
                  # agent.py the actor that drafts a forward by it
packages/mailbox-agents/tests/  # offline: REST and gateway through
                                # httpx.MockTransport
live/mailbox-agents/    # run by hand, outside testpaths, against the test
                        # account of containers/live/mailbox-agents/:
                        # agents_smoke.py read-only, categorization.py,
                        # chain.py the instances, filing.py and
                        # forwarding.py the actors, peers.py
                        # the entrance over A2A, gold.py the gold files from its
                        # labels, agents_common/ what they share
containers/
  images/mailbox-agents/Dockerfile
  production/mailbox-agents/   # the published image, one service per
                        # agent, each behind a profile of its name, its
                        # example lists copies of config/, held equal by
                        # packages/mailbox-agents/tests/test_examples.py
  development/mailbox-agents/  # built from the checkout, against the
                        # test account of live/mailbox-agents/
  live/mailbox-agents/  # a mail server, a mailbox service and a model
                        # gateway of their own, with a test account of
                        # invented mail
config/benethos-mailbox-agents/  # .env.example and the example lists
                        # *.example.json versioned, .env local
docs/mailbox-agents/    # CONCEPT.md, the overview, and concept/, a file
                        # per topic and per agent, ARCHITECTURE.md and
                        # LOGGING.md
data/benethos-mailbox-agents/
                        # the state files and the gold set, never
                        # versioned
reports/mailbox-agents/ # evaluation reports, numbers only, versioned
assets/mailbox-agents/  # brand/icon.svg and architecture/architecture.html,
                        # the diagram of the README, and the PNGs
                        # build.py renders from them
```

## Design decisions

- **A model that reads foreign text has no tools.** Mail is written by
  strangers. The step that reads it returns a value in a fixed schema and
  nothing else, so an instruction hidden in a mail can at worst produce a
  wrong value. Acting on the value is code.
- **One process per agent, one image for all.** `worker --agent inquiries`
  runs one agent. Each has its own credentials, its own state file, its own
  health and its own restart. They share code and nothing else.
- **The mailbox service and the gateway each sit behind one module.**
  `sources/mailbox.py` and `llm/gateway.py` are the only places that know
  them. The order of the layers below holds it.
- **Agents are self-contained.** Prompt, schema and baseline belong to one
  agent and are never shared. What several agents need lives in `runtime/`,
  or in `contract/` and `records/` where an agent needs it.
- **State stays where it is authoritative.** Mail stays in the mailbox. The
  state file holds ids, decisions and what was done, not copies of mail.
- **A backend that is away is a normal condition.** A model may run on a
  machine that is switched off. A message then waits and is taken up again,
  and nothing is lost or decided without the model.
- **asyncio throughout** (decided 2026-11-17). The async class of the
  mailbox client, an async httpx client for the gateway, one event loop per
  process. Calls to SQLite are short and serialized.
- **A state file can be read by another process.** It runs in WAL mode and
  its schema is part of the concept ([state](concept/state.md)), so a
  later overview of what every agent did ([roadmap](../roadmap/agents.md)) reads the
  files without the agents knowing of it. Another process of the same
  user, that is: the command line sets the umask to 077, so a state file
  is readable by its owner only (decided 2026-11-17).
