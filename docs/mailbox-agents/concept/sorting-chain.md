# Concept: the chain of `sorting`

Part of the [concept](../CONCEPT.md).

> **Status: built in `sorting` version 3 (2026-11-25), with instances that
> hand a message on by keywords, checked on the test account of the live
> setup. Not run on a real mailbox.** A list of
> `groups` alone, the form before, works as it did and keeps its version.

The agent [sorting](agent-sorting.md) sorts a message in steps. Each step,
a dimension, puts it into one of its categories, such as the partner of a
mail and then its kind. What follows from a category is named beside it:
a keyword, a move into a folder, a folder below the one it goes to. So the
list says which mail is what, and apart from that what is done with it
(decided 2026-11-25).

## 1. Recognizers and actions

The chain has two kinds of parts. A **recognizer** reads a message and
answers a category, or `none`. It may ask the model and changes nothing.
An **action** turns a category into requests for the runtime. It reads no
mail and asks no model. It sees the decision and where the message lies,
its folders and its keywords, never its subject, its sender or its text.
So no part that asks a model writes, and no part that writes reads what a
mail says. The executor of the runtime stays the lock on what is done
([agent contract](agent-contract.md)).

| Recognizer | Reads | Asks the model |
|---|---|---|
| `sender` | the sender rules of the categories, as in [sorting](agent-sorting.md#sender-rules) | no |
| `keyword` | the keywords a message carries: the category whose `keywords` it all carries, the one that names most when several do | no |
| `topic` | the topics of the categories the sender rules leave open | once per dimension |

| Action | Value | Primitives | On a choice of the model |
|---|---|---|---|
| `move` | a folder, `/` between the names | `create_folder`, `move_to_folder` | only with `"by_topic": "act"`, else recorded |
| `move_below` | a folder below the one the message goes to | `create_folder`, `move_to_folder` | as `move` |
| `keyword` | a keyword `agent-` and lower case letters, digits and dashes | `add_keyword` | yes |

### Adding one in code

Both kinds are registers in the agent's package (decided 2026-11-25).
Another recognizer is a subclass of `Recognizer` in
`agents/sorting/recognizers.py` with a `name`, a `version`,
`asks_model(dimension)`, `applies(dimension)`, and `baseline` or
`decide`, which answer a `Choice`: the category or `none`, the details to
record, the quote when the model chose. It goes into `RECOGNIZERS`, and a
category names it in `recognize`. Its version becomes part of the version
of the decision, so a new one is new work. Another action is a subclass of
`ChainAction` in `agents/sorting/actions.py` with a `name`, a pydantic
model `params` of its value, the `primitives` it asks for, `by_model`, and
`requests(params, placed, held=..., why=...)`. It goes into `ACTIONS`, and
an entry of `then` names it. A primitive the contract does not have yet
goes into the [agent contract](agent-contract.md) first, with how it is
taken back.

Recognizers and actions from other packages, through entry points, are
not part of it: the registers are cut so they can be added later without
a change to the rest (decided 2026-11-25).

## 2. The list

```json
{
  "on": {"arrival": "inbox"},
  "dimensions": [
    {"name": "partner", "categories": [
      {"name": "Bank", "senders": ["*@bank.example"],
       "then": [{"move": "Providers/Bank"}, {"keyword": "agent-partner-bank"}]},
      {"name": "Hosting", "senders": ["*@hosting.example"],
       "then": [{"move": "Providers/Hosting"}]}
    ]},
    {"name": "kind", "when": {"partner": ["Bank", "Hosting"]}, "categories": [
      {"name": "Invoice", "topic": "Invoices of a provider for a service the owner pays",
       "by_topic": "act",
       "then": [{"move_below": "Invoices"}, {"keyword": "agent-invoice"}]},
      {"name": "Notice", "topic": "Notices of a provider about a change of its terms",
       "then": [{"keyword": "agent-notice", "stage": "keyword"}]}
    ]}
  ]
}
```

| Field | Meaning | Rule |
|---|---|---|
| `on.arrival` | which mail the list takes up: `inbox`, or `folders` for mail that arrives in a folder without a role as well (section 5) | `inbox` when left out, none when `on` names `keywords` alone |
| `on.keywords` | the keywords the list waits for, a `*` at the end for every keyword it starts (section 8) | none of the keywords the list sets itself |
| `mark_done` | the agent's keyword after every decision, `none` included (section 8) | `false` when left out |
| `dimensions` | the dimensions in the order they run | 1 to 4. Their recognizers ask the model twice at most, each once per message |
| `name` of a dimension | what the decision and `report` call it | lower case letters, digits and `_`, a letter first, unique |
| `when` | the categories of earlier dimensions it runs after, `none` among them | each name an earlier dimension, each category one of it |
| `categories` | its categories | one at least |
| a category | `name`, `senders`, `topic`, `by_topic`, `hold` as a group of [sorting](agent-sorting.md#2-the-list), and `keywords`, `recognize`, `priority`, `then` | it names senders, a topic, keywords or a recognizer. Its name is unique in its dimension |
| `keywords` of a category | the keywords a message carries, all of them, for the recognizer `keyword` | lower case letters, digits and dashes |
| `recognize` | a recognizer of section 1 | one of the register |
| `priority` | how its move ranks against the moves of other dimensions (section 3) | a whole number, 0 when left out |
| `then` | what follows from it, each entry one action with its value, and a `stage` | one `move` and one `move_below` at most |
| `stage` of an entry | the stage it runs in at most: `shadow`, `keyword`, `full` (section 4) | the stage of the agent when left out |

A list of `groups` alone is read as one dimension called `group`, each
group a category whose `then` moves to its folder. It keeps the digest and
the version it had, so nothing it decided is taken up again (decided
2026-11-25). A list names `groups` or `dimensions`, never both.

A wrong list stops the start, and the message names the dimension and the
category, never a rule, a topic or a keyword. Two categories that write
the folder of a move, or one above it, in two cases are refused, as for
groups.

## 3. One message through the chain

The dimensions run in order. A dimension whose `when` does not hold for
the categories found before it does not run. In a dimension the
recognizers without a model run first, in the order of the register, and
the first that settles it decides. The recognizers with a model run only
when none did, in `decide` and not in `baseline`.

**The decision.** The category of the first dimension is the label, as
`report` and the evaluation read it. The category of every later one is a
field under the dimension's name. Each carries its evidence: a quote of
the model is looked up by the check of the runtime, a category found by
code carries none. So a later field whose quote is not found is dropped
alone, and a label whose quote is not found makes the whole decision
refused ([safety](safety.md)). The details of the first dimension stand
under their keys as before, those of a later one under
`<dimension>.<key>`, such as `kind.match`.

**What follows.** When the agent acts, the categories are looked up again
in the list as it is then: by the sender for a category a sender rule
chose, by its name for one the model chose. A dimension whose field the
check dropped, or whose `when` no longer holds, has none. The requests go
to the executor in this order:

1. the keywords and other actions of `then`, of every category found,
2. the folders and the move,
3. the agent's own keyword, which says the message was moved.

The keywords come first because the executor records only what follows a
move recorded only, and takes nothing after a refused one: so a keyword of
the list stands without a move, and the agent's own never does.

**One move at most (decided 2026-11-25).** Of several categories with a
`move`, the one of the highest `priority` wins, at a tie the one of the
earlier dimension. When the winner is held, by `hold`, by `by_topic` or by
the stage of its entry, the move is recorded and no other takes its
place. The dimensions that lost are named in the detail
`moves.displaced` and in `report`. A `move_below` goes below the
winner's folder, `Providers/Bank` and `Invoices` give
`Providers/Bank/Invoices`, made from the top when missing. Of several the
one of the highest priority counts. When either the move or the
`move_below` is held, the move is held.

## 4. The stage of an entry

An entry of `then` may name a stage. It only lowers what the stage of the
agent allows, it never raises it: below the stage an action needs, the
action is recorded only (decided 2026-11-25).

| Agent | Entry | A keyword | A move |
|---|---|---|---|
| `full` | none | set | made |
| `full` | `"stage": "keyword"` | set | recorded |
| `full` | `"stage": "shadow"` | recorded | recorded |
| `keyword` | any | set, unless `shadow` | recorded |
| `shadow` | any | recorded | recorded |

## 5. Mail that arrives in a folder

`"on": {"arrival": "folders"}` takes up a new message in a folder without
a role as well, such as one a rule of the mail server files into, and
`backfill` reads those folders (decided 2026-11-25). Such a message is not
moved out of its folder. A `move_below` goes below it, and only the
folders of the `move_below` are made. A move by hand still sets nothing
off: the agent is asked on `message.created` alone, and a move keeps the
message's id ([mailbox service](mailbox-service.md)). The trash, junk and
spam and the folders below them are never touched.

## 6. The owner's choice

What kept a message moved by hand where the owner put it before the chain
keeps it there now: the runtime moves a message at most once for an
agent, `admit` refuses a message that carries the agent's keyword, and a
move by hand comes as `message.updated`, which the agent does not ask for
([sorting](agent-sorting.md#3-what-happens-to-a-message)). A changed
list, a new `move_below` among it, does not move such a message again,
and no folder is made for a move that is not taken.

## 7. Report

`report` names each dimension and, per category, what became of its
mail: moved, recorded, recorded by topic, held, not moved, displaced by
priority, keyword set, keyword recorded, or only sorted for a category
with nothing in `then`. A list of groups keeps its heading `groups:`. The
senders in no category of the first dimension are the candidates for the
list, as before.

## 8. Instances that hand a message on

Several processes of `sorting` may run on one account, each an instance
with a list, a state file, a stage and metrics of its own,
`MAILBOX_AGENTS_INSTANCE` ([configuration](configuration.md)). One hands a
message on to the next by keywords, which a person sees in a mail client
and may correct (decided 2026-11-25). The example of the live setup,
`containers/live/mailbox-agents/chain/`:

| Instance | Waits for | Decides | Sets |
|---|---|---|---|
| `partner` | the arrival in the inbox | the partner by the sender | `agent-partner-<partner>`, and its sign |
| `beleg` | the arrival, and `agent-partner-*` | the partner by its keyword, the kind by its topic | `agent-invoice`, and its sign |
| `ablage` | `agent-sorted-beleg`, the sign of `beleg` | the partner and the kind by their keywords, no model | the move to `Providers/<partner>/Rechnungen`, and its own keyword |

- **Waiting for a keyword.** A list with `on.keywords` is asked about
  `message.updated` too. A message that carries a keyword it waits for is
  decided again, whoever set the keyword, the agent's own keyword on it
  or not, never one in the trash, junk or spam. What code decides is
  worked out anew, so a keyword a person corrected counts. What the
  model answered is taken as stored, with no new call: a dimension the
  model did not answer before stays without a category. The executor
  takes only what is not there yet, and a message moved once is not
  moved again: the owner's choice stands. Without `on.keywords`, an
  update is left as before.
- **The sign.** `"mark_done": true` sets the agent's keyword after every
  decision, `none` included, before a move, so it stands also where the
  move is recorded only. An instance's keyword is the agent's with
  `-<instance>` after it, `agent-sorted-beleg`. A later instance waits for
  it, so `ablage` moves once, after `beleg` decided, below the folder of
  the partner. Without `mark_done` the keyword comes with a move alone.
- **`shadow` sets no keyword.** An instance others wait for runs in
  `keyword` at least, or the next never starts. In `keyword` its moves
  are recorded, its keywords set.
- **No circle.** A list never waits for a keyword it sets itself, and an
  instance does not start when its list waits for its own keyword. Across
  instances the command `check --agent sorting partner=partner.json
  beleg=beleg.json ablage=ablage.json` names each circle of lists that
  set each other off, with exit code 1.
- **The feed.** A keyword set or taken off comes as one
  `message.updated` of the same id, measured through the mailbox service
  at Stalwart ([mailbox service](mailbox-service.md)). One set or taken
  off in a mail client over IMAP comes the same way, measured there too.
- **An account without keywords**, Gmail and POP3 in the mailbox
  service, gets no keyword: the service refuses it and the runtime logs
  the refusal **(to verify)**. There one instance with `when` is the
  way.

### The recognizer `invoice` and the way out for `invoices`

The recognizer `invoice` asks the question of the agent `invoices` with a
copy of its prompt `v5`, its schema and its rules. `eval --agent sorting
--recognizer invoice` scores it alone in the space of `invoices`, so the
gold set of `invoices` serves unchanged. On the gold set of the test
account, through the same model alias, it reached the numbers of
`invoices` on 2026-11-25
(`reports/mailbox-agents/sorting/2026-11-25-v3-invoice-v5-mail-classifier.json`
beside `reports/mailbox-agents/invoices/2026-11-23-v6-v5-mail-classifier.json`).
`invoices` goes only after a run in `shadow` on the owner's mailbox fits
as well (decided 2026-11-25). `live/mailbox-agents/chain.py` runs the
three example instances on the test account ([testing](testing.md)).

## 9. Not part of it

- Forwarding a message: an action without a way back, for the
  [agent contract](agent-contract.md) first, with the mailbox service's
  outbox.
- Labels on Gmail in place of keywords.
- A threshold on how sure a recognizer is. The field `confidence` of a
  `Choice` is there and stays empty, until a gold set is large enough to
  measure it.
