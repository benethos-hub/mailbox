# The log

What an agent writes to its log, at which level, in which shape, and what
never goes into a line. The code is `packages/mailbox-agents/src/benethos_mailbox_agents/logbook/`.
[concept/safety.md](concept/safety.md) holds the rule behind it: nothing of a
mail in a log line.

## 1. What the log is for

The log tells an operator what an agent did and what went wrong, in the
order it happened, for one process. It is read at a terminal, in a
container log or in the journal. It is not the record of what an agent
decided: that is the state file, which the command `report` reads. The
host may drop the log, the state file stays.

| Reader | Question | Level |
|---|---|---|
| The operator at night | is something broken that needs me? | `ERROR` |
| The operator in the morning | what failed or was refused, and did it heal? | `WARNING` |
| The operator who asks "what happened to message X" | what did the agent do? | `INFO` |
| The developer | how long did each step take? | `DEBUG` |

One line on stderr is not the log's. When a command ends with an error
of this package, the command line writes `benethos-mailbox-agents:` and
the error's message, and exits with code 2 for a configuration to
correct or 1 for an upstream that is away
([concept/runtime.md](concept/runtime.md), the commands). That line has no time, level or
source, and it is written also when the log was never set up, as for a
setting that cannot be read. Its message may hold more than a log line
may say of the error: a status and a code of an upstream, a name of a
setting, the text of the mailbox client about its configuration. It
holds nothing of a mail, and the service token and the gateway key are
redacted from it as from every error text. A control or direction
character in it is written as its escape, as in a log line. A log line names the same
error by its class and code only.

## 2. Levels

`MAILBOX_AGENTS_LOG_LEVEL` sets the level of the agent's own lines,
`INFO` by default. Every other logger, a library's, writes at `WARNING`
and above only. `httpx` and `httpcore` are held there whatever the level
says, since they name each request with its whole URL.

- **`ERROR`**: a pass of the loop failed with an error of the agent's
  own. The loop goes on with the next pass, but something needs a look.
- **`WARNING`**: something failed or was refused, and the agent goes on.
  An upstream away, a step of a message that failed, an answer of the
  model that failed its schema, an action the service refused, the place
  in the feed expired.
- **`INFO`**: what the agent did. It started and stopped, read the feed,
  set a message to a state, carried out or recorded an action.
- **`DEBUG`**: the timing of a pass and of a step.

## 3. The shape of a line

A line holds the time, the level, the source and the message:

```
2026-11-18T10:12:22.123+01:00 INFO     benethos_mailbox_agents.activity.actions.recorded: invoices recorded add_keyword on message m1 in stage shadow without carrying it out: invoice
```

- **The time** is ISO 8601, the local time of the machine, to the
  millisecond, with the offset.
- **The source** is the logger of the activity,
  `activity.<area>.<name>` below the package's name (section 6). On a
  terminal the line is in colour and the source stands without the
  package's name, in a column of 32 characters. Elsewhere, in a container
  log or the journal, the line is plain text with the whole name. A
  terminal gets no colour when `NO_COLOR` is set.
- **The message** is one sentence in the past tense, in this order:

```
<agent> <did what> <to which>[: <why>]
```

- **agent**: the agent's name, such as `invoices`.
- **did what**: the verb, such as started, read, set, failed, carried
  out, recorded.
- **to which**: a message by its id, never by its subject or sender. A
  step by its name, an action by its name, a count with its noun.
- **why**: the error by its class and code, such as
  `MailboxRefusedError(mailbox_refused)`, the reason an answer was
  refused, or the agent's short code for an action, such as `due`. Only
  when there is one. A code is fixed in the agent's code, never text of
  the owner's configuration: `sorting` writes `group` or `held`, never the
  name of the group, which often names a person (decided 2026-11-18).

No key-value pairs and no JSON: a person reads the line, and a search for
an id finds it.

## 4. What never goes into a line

1. **Mail content**: a subject, a text, an attachment name, a header, a
   quote the model gave as evidence.
2. **People**: the address or the name of a sender or a recipient.
3. **Secrets**: the service token, the gateway key, any value read from
   a `*_FILE` setting.
4. **The message of an error.** It may quote what an upstream answered,
   which may be a piece of a mail. A line names the error by its class
   and its `code`.
5. **What a library logs below `WARNING`**, such as the URL of each
   request.

Allowed on purpose: the agent's name, ids of messages and accounts,
states, stages, names of steps and actions, counts, durations, ports,
versions, the notes of a migration.

Every line, a traceback included, passes `errors.redact` before it is
written. That is the second line of defence, not the first: a line is
written as if there were no redaction.

## 5. Rules for writing a line

1. **Every line is an activity.** A module that has something to say
   builds the activity of the catalogue and hands it to
   `logbook.record`. No module outside `logbook/` imports `logging`, and
   `packages/mailbox-agents/tests/test_layers.py` checks it.
2. **An activity is a frozen dataclass** in the module of its area under
   `logbook/catalogue/`. Its fields are typed and hold what a line may
   carry: ids, states, counts, durations, codes, an error. No field holds
   a type that carries a mail or a secret, and no field is named for one.
   A test walks the catalogue and checks both.
3. **The line is built only when it is written.** `record` asks the
   logger first, so a `DEBUG` line costs nothing at `INFO`.
4. **An activity is one line.** `record` writes each control character
   and each line and paragraph separator of the message as its escape,
   such as `\n` or `\u2028`, so no value from an upstream starts a line of its own.
   So it does with each mark that sets the direction of text, U+061C,
   U+200E, U+200F, U+202A to U+202E and U+2066 to U+2069, so no value
   turns the text after it around. `report` writes what it shows the same
   way.
5. **After the fact.** A line says what happened, so it is written once
   the state file holds it. A refusal is written where it is refused.
6. **Every new activity gets a row** in the table of section 6 and a line
   in a test. The suite fails while the table and the catalogue differ.

## 6. The catalogue

Each activity has a name, set in its class, not taken from the class's
name, so a class renamed in the code keeps its name in the log and in an
operator's filters. It writes under the logger
`benethos_mailbox_agents.activity.<area>.<name>`.

- **The area is the module** of the catalogue: `process`, `worker`,
  `feed`, `messages`, `actions`.
- **A name says what happened**, in the past tense or as a state,
  lowercase with underscores, unique within its area. The area is not
  repeated: `activity.messages.state_set`, not
  `activity.messages.message_state_set`.
- **Short enough for a column**: `activity.<area>.<name>` has 32
  characters at most.
- **Each has its own logger.** A level set on one name silences it alone,
  and a filter on `activity.messages` finds the whole area.

| Name | Level | What |
|---|---|---|
| `process.started` | INFO | the worker started, with the agent's version and stage |
| `process.stopped` | INFO | the worker stopped, and why |
| `process.migrated` | INFO | the state file was made or migrated, with the notes of its steps |
| `process.metrics_serving` | INFO | the metrics are served on a port |
| `worker.pass_done` | DEBUG | a pass ended, with its duration and the messages pending |
| `worker.pass_failed` | ERROR | a pass failed with an error of the agent's own, and the loop waits as after an upstream away |
| `worker.upstream_away` | WARNING | the mailbox service or the gateway is away, and the loop waits |
| `worker.tick_done` | INFO | a tick ended, with the actions it asked for |
| `feed.read` | INFO | the changes read from the feed, and how many the agent selected |
| `feed.expired` | WARNING | the place in the feed expired, the feed starts anew |
| `feed.backfilled` | INFO | messages of the last days taken up as if new |
| `messages.state_set` | INFO | a message was left in a state |
| `messages.step_done` | DEBUG | a step of a message ended, with its duration |
| `messages.step_failed` | WARNING | a step of a message failed |
| `messages.answer_refused` | WARNING | the model's answer failed its schema, or the gateway refused the request |
| `messages.quote_missing` | INFO | a quote the model gave for a field is not in the mail |
| `actions.done` | INFO | an action was carried out on a message |
| `actions.recorded` | INFO | an action was recorded and not carried out: the stage did not allow it, the agent held it, or a folder or move before it was recorded only |
| `actions.kept` | INFO | a move of a message the agent moved once before was not taken: the folder the owner chose since stands |
| `actions.refused` | WARNING | the executor or the mailbox service refused an action |
