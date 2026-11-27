# Working guidelines for the agents

The rules that hold for `mailbox-agents` alone. The rules for the whole
repository, the golden rules among them, are in the
[CLAUDE.md of the root](../../CLAUDE.md): read it first. What the
agents are and do:
[docs/mailbox-agents/CONCEPT.md](../../docs/mailbox-agents/CONCEPT.md),
and [concept/](../../docs/mailbox-agents/concept/) for each topic and
each agent.

## The rules of the agents

1. **Shadow first.** An agent reads mail and moves it. A new agent, and
   one whose prompt or model changed, starts in the stage `shadow`. A
   change of stage on a real mailbox is the owner's decision, never a
   default. The live checks bring their own mail server with an account
   made for them and filled with invented mail.
2. **Nothing of a mail in a log line.** A line names ids, states, counts
   and durations. Never a subject, a sender, a text or an attachment
   name. The service token and the gateway key are never stored in a
   state file either.
3. **One module per upstream.** `sources/mailbox.py` is the only module
   that imports `benethos_mailbox_client`, `llm/gateway.py` the only one
   that talks to the model gateway. The cockpit reaches the mailbox
   service only through a reader the command line hands it, and the
   state files only through the store. `tests/test_layers.py` holds the
   import order: a new top-level module or subpackage needs a row there.
4. **A model that reads mail has no tools.** It returns a value in a
   fixed schema. Acting on the value is code, and the code checks the
   evidence first
   ([safety.md](../../docs/mailbox-agents/concept/safety.md)).

## Verifying

- `uv run pytest -q packages/mailbox-agents/tests` from the root runs the
  suite of the agents alone. The mailbox service and the gateway are
  mocked with `httpx.MockTransport`.
- **The gates do not cover the upstreams changing.** Verify a new
  assumption about the mailbox service or the gateway with a live check
  before building on it, and mark it **(to verify)** in its file under
  `docs/mailbox-agents/concept/` until then.
- **The agents take the service of their own version.** Before 1.0 the
  same minor version, from 1.0 the same major and no older minor
  (`matches` in `sources/versions.py`,
  [mailbox-service.md](../../docs/mailbox-agents/concept/mailbox-service.md)).
  The client is pinned to the agents' version.
- A live check is a manual run, never a gate:
  [containers/live/mailbox-agents/README.md](../../containers/live/mailbox-agents/README.md)
  says how to start the setup of its own, and
  `live/mailbox-agents/agents_smoke.py` checks the package against it,
  read-only.
- An evaluation run is manual too, against a gold set under `data/`, or the one
  `live/mailbox-agents/gold.py` writes for the test account. Its
  report goes into `reports/mailbox-agents/`, where `eval` puts it
  without `--reports`, and holds numbers only.

## Conventions

- **asyncio throughout.** One event loop per process, an async httpx
  client for the gateway, the async class of the mailbox client.
- **Agents are self-contained.** Prompt, schema and baseline belong to
  one agent and are never shared. What several agents need lives in
  `runtime/`, or in `contract/` and `records/` where an agent needs it.
- **A prompt has a version.** Changing a prompt changes its version, and
  the step runner treats it as new work.
- **A migration of the state file is never changed once released.** A
  change of the schema is a new migration: a class `VNNNN<Subject>` of
  `Migration` in a module `vNNNN_<subject>.py` in
  `store/migrations/versions/` with the next number, added to
  `MIGRATIONS` in `store/migrations/__init__.py`. Its docstring says what
  it does and why. Each statement stands alone, a step in Python is the
  method `before`. A release freezes its new migrations: the fingerprint
  of each goes into `RELEASED` in `tests/store/test_store.py`.
- **The concept moves with the code.** `docs/mailbox-agents/CONCEPT.md`
  is the overview, and `docs/mailbox-agents/concept/` holds one file per
  topic and one per agent. A change that departs from them changes them
  in the same commit.
- **A document is named for its subject.** One that stands directly in
  `docs/mailbox-agents/` is written in capitals. A part in `concept/` is
  named in lowercase with hyphens, an agent's as `agent-<name>.md` with
  the `_` of its name as a hyphen. It starts with the name of its
  document, as in `# Concept: runtime`, and a line that leads back to the
  overview. The overview lists every part in a table
  (`tests/test_docs.py`).
