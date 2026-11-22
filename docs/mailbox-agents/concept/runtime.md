# Concept: runtime

Part of the [concept](../CONCEPT.md).

One loop per process. Each pass first asks the mailbox service for its
version: one of another version than the agents' ends the worker
([mailbox service](mailbox-service.md#the-version-of-the-service)). Then:

1. Read the feed from the stored cursor. On the first pass, start from the
   state of now. On `410` take a new state and run `backfill` over
   `BACKFILL_DAYS`.
2. For each event the agent routes to `decide`, record the message as
   `pending`. Hand each one routed to `observe` to the agent at once. One
   deleted since closes its open item as `message_gone`.
3. For each `pending` message whose next attempt has come, at most 50 a
   pass, run the steps: fetch, `admit`, baseline, decision with its evidence
   check, effect. Each step
   writes its result before the next begins.
4. On the tick, ask the agent what is due and run the effects.
5. Store the cursor and the time of the pass, then sleep `POLL_SECONDS`.

A mailbox service that is away while the feed is read stops the pass
before the cursor moves. A mailbox service that is away while
pending messages run leaves them `pending`. A gateway that is away holds
up only the messages that ask a model: each stays `pending` with no
attempt counted, the gateway is not asked again in that pass, and the
messages that need no model run on. Either way the cursor moves, and the
next pass waits twice as long as the last, up to
`BACKOFF_CEILING_SECONDS`. A mailbox service that answers its version but
fails for one message alone would end every pass at that message. So the
worker counts the passes that end at the same message in a row, and at
`MAX_ATTEMPTS` of them the message counts an attempt, or its update is
left as a refused one is, with a line `messages.step_failed`, and the
pass goes on with the next (decided 2026-11-20). A pass that ends
otherwise starts the count again. A service away as a whole, its version
too, leaves every message as it is. A pass that fails with an error of
the agent's own, such as a key the gateway refuses, waits as after an
upstream away, logged as `worker.pass_failed` with its wait (decided
2026-11-20).

An upstream away in the middle of a message's actions may leave some of
them taken: `sorting` has moved the message out of the inbox, and setting
its keyword failed. When the worker runs that message again, it goes on to
its effect without asking `admit`, which would refuse it outside the
inbox, and the executor finds what is done there already (2026-11-20). The
worker keeps this in memory: after a restart in between, the message is
asked as any other. A state file that
cannot be read or written, one that is no SQLite file or a full disk,
or whose folder or lock cannot be made, ends the worker with a `StateFileError` and exit code 1: no pass goes on
without it (2026-11-19). A mailbox service of another version ends
it with a `ServiceVersionError` and exit code 2, as it ends `run` and
`backfill`.

Message states: `pending`, `skipped` (not admitted, marked before the
state file for an agent that declares `skip_marked`, which an update
without the keyword makes `pending` again, or gone from the
mailbox, also when it went in the middle of its actions), `decided` (recorded and not acted on, such as a label whose quote
was not found), `done` (its effect carried out, in whatever stage),
`failed` (given up after `MAX_ATTEMPTS`, or more model calls asked for
than the limit per message allows).

The steps of one message: fetch, `admit`, baseline, decision, effect.
After `admit`, a message that carries the keyword of an agent that
declares `skip_marked`, with no step of it in the state file, ends as
`skipped` ([agent contract](agent-contract.md), since 2026-11-19). The
message is fetched anew before the effect when the decision asked the
model, so the agent acts on where it lies now: another agent or a person
may move it while the model answers, and one deleted meanwhile is
skipped. The baseline is stored once per agent version and prompt
version, so `report` never shows a baseline older than the decision
beside it (since 2026-11-18). The decision, with the model
calls it made and its evidence checked, is stored once per prompt version
and model alias. A message that reached its daily limit of model calls
waits for the next day.

Rules:

- **Idempotent steps.** A step whose result is stored for the same message,
  prompt version and model is not run again. A repeated feed entry is
  harmless.
- **The cursor moves last.** A crash repeats work, it does not skip mail.
- **One writer.** A process is the only writer of its state file. It holds
  an exclusive lock on `<agent>.db.lock` beside it while the file is open,
  so `run` or `backfill` beside a running `worker` is refused. Readers
  such as `status` and `report` stay free (decided 2026-11-17).
- **A new prompt or model does not rewrite history.** `backfill` runs old
  messages again under the new version and keeps both results.

Rollout stage, per agent, in `MAILBOX_AGENTS_STAGE`:

| Stage | What the agent does |
|---|---|
| `shadow` | records what it would do, changes nothing |
| `keyword` | sets its keyword, moves nothing |
| `full` | every action it declares |

A new agent starts in `shadow`, and so does one whose prompt or model
changed until the evaluation was run again.

## Commands

| Command | What it does |
|---|---|
| `worker --agent <name>` | runs one agent pass after pass until SIGTERM or SIGINT |
| `run --agent <name>` | one pass, then the counts per state |
| `backfill --agent <name> [--days N]` | takes the messages of the last days up anew and runs them: those of the inbox and of sent mail, and those of the folders the agent wants besides, such as the folders `invoices` looks in. It runs until no message is due, and stops with exit code 1 after the first round that found the gateway away |
| `report --agent <name> [--limit N] [--state S] [--offline]` | [report](#report) |
| `eval --agent <name> --gold <file> [--reports DIR]` | [evaluation](evaluation.md) |
| `health --agent <name>` | exit 0 while the loop makes progress, [operation](operation.md) |
| `status` | the version of the mailbox service and whether it matches the agents', then for each agent whether it is ready, which setting it misses, the folders that matter to it and a folder it expects that is missing or there in another case only, in each account `ACCOUNTS` names or else in each account the user is granted, its counts and its last progress |
| `paths` | the settings file, the data folder and each state file |

`--env-file` names the settings file for every command. An error to
correct ends with exit code 2, a mailbox service of another version
among them, an upstream that is away or an unreadable state file with 1. `status` and `paths` start no agent and change
nothing. `status` names a state file it cannot read, or one of a newer
schema, and goes on with the next agent. `health` answers 1 for both.

## Report

`benethos-mailbox-agents report --agent <name>` shows what an agent decided
and did, or in `shadow` would have done: per message the subject and sender,
the decision, the evidence and the action (decided 2026-11-17). The state
file holds ids only, so subject and sender are fetched from the mailbox
service at the moment of the report and are never stored. Without it the
stage `shadow` could not be reviewed.

The report lists the newest messages first, 50 unless `--limit` says
otherwise, and with `--state` those in one state. Per message it prints
sender and subject, the decision with its source, model, fields and
details, each quote and whether it was found, the label of the baseline,
and each action with its stage and whether it was carried out or would
have been. It ends with what the agent has to say about the messages shown: for
`invoices`, the senders of invoices it marked and did not move, with how
many each sent, as candidates for a group of `sorting`. For `sorting`, per group
how many messages were moved, recorded, held or not moved, the senders in
no group that wrote most often, and the senders two groups name alike.
These counts cover the messages shown. When the state file holds more,
in `--state` if named, a line before them says how many of how many they
count and which `--limit` counts all (2026-11-22). It opens the state file
read-only, so it runs beside the agent.
`--offline` reads the state file alone, without subject and sender. What
it prints goes to stdout for the person who asked and never to the log.
