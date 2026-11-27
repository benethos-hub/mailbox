# Concept: testing

Part of the [concept](../CONCEPT.md).

- The suite is offline. The mailbox service and the gateway are mocked with
  `httpx.MockTransport`. No test reaches a network, and none skips itself
  when a credential is missing.
- The checks and the CI are those of the whole repository
  ([CLAUDE.md](../../../CLAUDE.md#verifying)). The job `lowest-agents`
  runs these tests against the lowest versions `pyproject.toml` allows.
- A test holds the layer order of [architecture](../ARCHITECTURE.md), and
  others hold the tables of [configuration](configuration.md),
  [state](state.md) and [agent contract](agent-contract.md) to the code
  where they can be compared.
- Async tests run with pytest-asyncio.
- Live checks are scripts in `live/mailbox-agents/`, run by hand against a test account.
  `containers/live/mailbox-agents/` holds it (decided 2026-11-17): a mail server of our
  own, Stalwart, in a local container, with an account made for the agents
  and filled with invented mail, and the mailbox service in front of it,
  built from the checkout (since 2026-11-22, the version of the agents
  beside it). `setup.sh` makes it in one run, and
  `live/mailbox-agents/agents_smoke.py` reads it through the package without writing to it.
  `live/mailbox-agents/categorization.py` runs `categorization` on it in `shadow` and in `full`, makes
  its folders, moves the mail and puts it back.
  `live/mailbox-agents/chain.py` runs three instances of `categorization` that
  hand a message on by keywords through the feed, a partner keyword set
  by hand among it, and puts every message back without their keywords.
  `live/mailbox-agents/filing.py` runs the actor `filing` in `shadow` and
  in `full` on keywords it sets as a person would, a message put back by
  hand among it, and puts every message back.
  `live/mailbox-agents/forwarding.py` makes a user with `mail.read` and
  `drafts` through the administration of the service, runs the actor
  `forwarding` under it in `shadow` and in `suggest`, and deletes its
  drafts, the user and its token again. It sends nothing.
  `live/mailbox-agents/peers.py` asks the entrance for peers over A2A,
  directly and through LiteLLM, and changes no mail.
  The model gateway belongs to it (decided 2026-11-17): LiteLLM with Claude
  through the owner's API key, and local models under llama.cpp, one
  service on the graphics card and one on the CPU. `live/mailbox-agents/gold.py` turns
  the labels of the invented mail into gold files, so `eval` can compare
  models on them.
- A live check reads its settings from its file alone, through
  `live/mailbox-agents/agents_common/settings.py` (decided 2026-11-18). A `MAILBOX_AGENTS_` variable
  exported in the shell, of a real deployment say, is not read. A mailbox
  service that is not on this machine, `127.0.0.1`, `localhost` or `::1`,
  at the port 38081 of `containers/live/mailbox-agents`, stops the check with exit code
  2: a real service on this machine at its default port would pass the
  host alone (decided 2026-11-20). The check prints the account and the
  service before it reads or writes.
