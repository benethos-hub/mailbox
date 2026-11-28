# Concept: runtime

Part of the [concept](../CONCEPT.md).

One loop per process. Each pass first asks the mailbox service for its
version: one of another version than the agents' ends the worker
([mailbox service](mailbox-service.md#the-version-of-the-service)). Then:

1. Read the feed from the stored cursor. On the first pass, start from the
   state of now. On `410` take a new state and run `backfill` over
   `BACKFILL_DAYS`. The backfill takes up new messages, and `skipped` ones
   anew, as the gap may have given one a keyword an actor waits for. Each
   open item is then observed as if it were updated: a change in the gap,
   such as a marked invoice moved into a folder, is not lost.
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
too, leaves every message as it is. A service that cannot reach its
database answers `503` everywhere, `/health` included, and is away as a
whole: the pass ends at the question for its version **(to verify)**. A pass that fails with an error of
the agent's own, such as a key the gateway refuses, waits as after an
upstream away, logged as `worker.pass_failed` with its wait (decided
2026-11-20).

An upstream away in the middle of a message's actions may leave some of
them taken: `categorization` has moved the message out of the inbox, and setting
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

A database of the state on a PostgreSQL server that is away is waited
for as an upstream: the call fails at once with a
`StateUnavailableError`, of the family `UnavailableError`, the pass ends
without deciding or changing anything more, and the loop waits as after
an upstream away, logged as `worker.upstream_away`. While it waits it
writes no progress, so the health check fails. The storage of
mailbox-common tries the server again after a pause of one second,
doubled after each failed attempt up to thirty, on a new session that
takes the lock of the writer again. A lock held by another session
counts as the server still away for a minute since it went, as the old
session of the worker may still hold it until the server ends it
(2026-11-28). When another agent still holds that lock after the
minute, the worker ends with a `StateFileError`, as for a state file
that fails (2026-11-27).

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
- **The profile at the start.** `worker`, `run` and `backfill` write the
  profile of the agent into its state file when they open it: the stage,
  the accounts, the keyword, the poll and gateway seconds, the model
  alias and the versions ([state](state.md)). A reader from outside, such
  as the cockpit, holds none of these settings. `eval` and the live
  checks write none.
- **A new prompt or model does not rewrite history.** `backfill` runs old
  messages again under the new version and keeps both results.

Rollout stage, per agent, in `MAILBOX_AGENTS_STAGE`:

| Stage | What the agent does |
|---|---|
| `shadow` | records what it would do, changes nothing |
| `suggest` | sets its keyword, drafts a forward, moves nothing |
| `full` | every action it declares |

The middle stage is called `suggest` (decided 2026-11-27): in it an
agent leaves something the owner sees and takes back in one step, and
moves or sends nothing. Its word before was `keyword`, which is still
taken and read as `suggest`, and a state file is migrated to the new
word ([state](state.md)).

A new agent starts in `shadow`, and so does one whose prompt or model
changed until the evaluation was run again.

## Commands

| Command | What it does |
|---|---|
| `worker --agent <name>` | runs one agent pass after pass until SIGTERM or SIGINT |
| `run --agent <name>` | one pass, then the counts per state |
| `backfill --agent <name> [--days N]` | takes the messages of the last days up anew and runs them: those of the inbox and of sent mail, and those of the folders the agent wants besides, such as the folders an instance of `categorization` with `"on": {"arrival": "folders"}` takes up. A message the agent only observes when it arrives is taken up when it carries a keyword the agent waits for already, as an update would take it up. It runs until no message is due, and stops with exit code 1 after the first round that found the gateway away |
| `report --agent <name> [--limit N] [--state S] [--offline]` | [report](#report) |
| `eval --agent <name> --gold <file> [--recognizer R] [--reports DIR]` | [evaluation](evaluation.md), with `--recognizer` one part of the agent scored alone |
| `check --agent <name> INSTANCE=FILE...` | reads the configuration of several instances together and names each circle of lists that set each other off, exit code 1 when there is one, else 0 |
| `health --agent <name>` | exit 0 while the loop makes progress, [operation](operation.md) |
| `status` | the version of the mailbox service and whether it matches the agents', then for each agent whether it is ready, which setting it misses, the folders that matter to it and a folder it expects that is missing or there in another case only, in each account `ACCOUNTS` names or else in each account the user is granted, where its state lies, its counts and its last progress. With `STORAGE=postgres` it reads the database once, says where it lies first, and shows the counts under the agent whose profile it holds |
| `cockpit` | the read-only pages of what every agent did, until SIGINT or SIGTERM, only with its secret ([cockpit](cockpit.md)) |
| `paths` | the settings file, the data folder and each state file, and a state file at the place before ([configuration](configuration.md#where-the-settings-and-the-state-files-are)). With `STORAGE=postgres` the database of the state in place of the files: its name, host, port and schema, never a password |
| `storage provision --agent <name> [--apply --admin-url URL --admin-password-file FILE]` | prints what an administrator of the PostgreSQL server runs once for the database of the agent and instance: a role that signs in, without its password, a database it owns, closed to every other role, and once per server the role `agents_read`, without sign-in, with the role `agents_cockpit` as its member. Role and database are those of `DATABASE_URL`, or else `agent_<agent>` and `agent_<agent>_<instance>`, the dashes of the instance as underscores (2026-11-27). A name longer than the 63 characters of PostgreSQL is refused, never shortened. With `--apply` it runs that itself, as the administrator the two options name for this call alone, and sets the password the file `DATABASE_PASSWORD_FILE` holds: the agent then starts on it. A role or a database of the names that exists already stops it |
| `storage move --agent <name> [--check]` | copies the state file of the agent and instance into the database `DATABASE_URL` names, in the schema of its role, made where it is missing, and compares every table on both sides by its rows and their sum. The database must hold no table yet, and neither side may be in use by a running agent: stop it first. The file stays as it was. `STORAGE=postgres` then starts the agent on the database. With `--check` it only holds every value of the file to its column, writes nothing and needs no server |

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
have been. It ends with what the agent has to say about the messages shown. For `categorization`, per
dimension and category what became of its mail
([the chain](categorization-chain.md#7-report)), the senders in
no group that wrote most often, and the senders two groups name alike.
These counts cover the messages shown. When the state file holds more,
in `--state` if named, a line before them says how many of how many they
count and which `--limit` counts all (2026-11-22). It opens the state file
read-only, or with `STORAGE=postgres` the database of the state, so it
runs beside the agent. Without a state there it stops with exit code 2.
`--offline` reads the state alone, without subject and sender. What
it prints goes to stdout for the person who asked and never to the log.
