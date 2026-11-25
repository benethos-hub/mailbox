# Concept: the agent `categorization`

Part of the [concept](../CONCEPT.md).

> **Status: version 3 built (2026-11-25): a list may name dimensions run
> one after another, and what follows from each category, see
> [the chain of categorization](categorization-chain.md). Run in `shadow` and in `full`
> on the test account. Version 2, its choice by a topic, was measured
> there on 2026-11-24 against the invented mail of the live setup
> (`reports/mailbox-agents/categorization/`). Version 1, by the sender alone, ran in `shadow` and in
> `full` on the test account, and on a real mailbox on 2026-11-22,
> read-only and in `shadow`, and changed nothing. Versions 2 and 3 have
> not run on a real mailbox. A run on the owner's account is the owner's decision,
> in `shadow` first.** Its purpose: the mail of providers such as a shop,
> a hoster or a bank goes into a folder of its own, and one folder may
> take several, such as all banks. With a topic, mail of a project, a
> customer or a kind, such as applications, finds its folder by what it
> says.

**Its name.** Until 2026-11-25 the agent was named `sorting`, and on
that day it was decided to name it `categorization`. Its state file,
setting, default keyword, metrics and reports took the new name. It
does not start beside a state file of the former name, `sorting.db`, and
`status` names one: the cursor and every decision are in it, so the
owner renames it. Mail it marked with `agent-sorted` keeps that keyword.
An owner who keeps marking with it sets `MAILBOX_AGENTS_KEYWORD`.

**Question:** does this message in the inbox belong to a listed group, by
its sender or by what it says, and which folder is the group's? With a
list of dimensions: which category of each dimension does it belong to,
and what follows from it ([the chain](categorization-chain.md))?

This file describes a list of `groups`, which the chain reads as one
dimension called `group`, each group a category that moves to its
folder. What a list of dimensions adds, a keyword per category, a move
below another, a priority, a stage per entry, mail that arrives in a
folder, stands in [the chain of categorization](categorization-chain.md).

| | |
|---|---|
| Triggers | `message.created` in the inbox, and `backfill` for older mail |
| Baseline | the sender rules of the list |
| Model | one call for a message no sender rule settles, when a group has a topic: the group or `none`, one quote |
| Actions | `move_to_folder`, `create_folder`, and `add_keyword` with the move and for a keyword of the list |
| Keyword | `agent-categorized`, set with each move, see section 3 |

## 1. Two stages, two agents (decided 2026-11-18)

`categorization` moves by the sender, or by the topic of a group, from the inbox
into the group's folder. Whether a message is an invoice is asked
afterwards, by [invoices](agent-invoices.md), which moves it on within the
folder it lies in. No agent does both. `invoices` stays an agent of its
own: a topic chooses a folder, it does not tell an invoice from a
reminder.

Each agent works without the other. `categorization` knows nothing of invoices.
`invoices` knows nothing of groups: it is told at its start which folders
it looks in ([invoices](agent-invoices.md#settings)).

The two never compete for a message:

| Agent | Moves a message that lies in | To |
|---|---|---|
| `categorization` | the inbox | the folder of the sender's group |
| `invoices` | a folder it was told to look in, other than the inbox, and the inbox folder, an end station where nothing moves | the subfolder below that folder |
| `invoices`, with an inbox folder set | the inbox | the inbox folder |

So no rule about who runs first and no waiting time is needed, and both run
on one account, as long as `invoices` has no inbox folder. With one set, an
invoice `invoices` takes up first goes into that folder, and `categorization`
leaves it there.

```
Inbox
Bank/
CloudHost/
  Rechnungen/
Telco/
  Rechnungen/
```

## 2. The list

A JSON file named in `MAILBOX_AGENTS_CATEGORIZATION_FILE`, not versioned. An example
of it is versioned as `config/benethos-mailbox-agents/categorization.example.json`.

```json
{
  "groups": [
    {"name": "Bank", "folder": "Bank",
     "senders": ["*@bank-one.example", "service@bank-two.example"],
     "hold": true},
    {"name": "CloudHost", "folder": "CloudHost",
     "senders": ["*@cloudhost.example"]},
    {"name": "Project Alpha", "folder": "Projects/Alpha",
     "senders": ["*@client.example"],
     "topic": "Mail about the project Alpha: the offer, the weekly status, the acceptance",
     "by_topic": "act"},
    {"name": "Applications", "folder": "Applications",
     "topic": "Applications and CVs of people who want to work with the owner"}
  ]
}
```

| Field | Meaning | Rule |
|---|---|---|
| `name` | what `report` and the decision call the group | unique, case aside, no space at its ends, not `none` in any case. For a group with a topic one line, without control characters |
| `folder` | where its mail goes, `/` between the names | unique, case aside. No name empty, `.` or `..`, nor with a space at its ends. A folder above it that another group's path shares is written alike in both |
| `senders` | who belongs to it | optional. A rule belongs to one group, or to several that each have a topic |
| `topic` | one line on the mail that belongs to the group, which the model is given (2026-11-24) | optional. 1 to 300 characters, no space at its ends, no line break, no control character. At most 50 groups have one |
| `by_topic` | how far a choice by the topic goes: `record` or `act` (2026-11-24) | only with a topic. `record` when left out |
| `hold` | section 5 | optional, `false` when left out |

A group names senders, a topic or both.

The folder is chosen freely (decided 2026-11-18): one folder for several
senders, such as all banks in `Bank`, one per sender, or a folder below
another.

**A list that could never work is refused (decided 2026-11-18).** Two
groups that write one folder in two cases, `Bank` beside `bank/Sub`, would
never get the second, as the runtime makes no folder whose name exists in
another case. A group named `none` would share the label of a message in
no group, and `report` would leave it out. A domain with an empty name,
such as `*@.shop.example`, `*@shop..example` or `a@b.example.`, matches no
sender. A group with neither senders nor a topic, `by_topic` without a
topic, one rule in two groups when one of them has no topic, and more than
50 groups with a topic are refused as well (2026-11-24). Each is named by
its group, and a rule by its place too. A message never quotes a topic.

### Sender rules

| Kind | Written | Covers |
|---|---|---|
| address | `service@bank-two.example` | that address |
| pattern | `*@cloudhost.example`, `mailbox*@telco.example` | every address of that domain the `*` fits. `*` stands before the `@` |
| pattern for subdomains | `*@*.shop.example` | every address of every subdomain of `shop.example`, not of `shop.example` itself |
| domain | `cloudhost.example` | refused, see below |

- Case is ignored.
- An address longer than 320 characters, more than the mail standards
  allow, matches no rule (2026-11-20). A pattern is matched in time
  linear in the length of the address, so the limit only bounds that
  time.
- The most specific rule wins: an address before a pattern before a
  pattern for subdomains.
- Two groups whose rules of the same kind both match leave the sender
  unmatched. Nothing is guessed. A pattern with letters before the `*` is
  of the same kind as one without: `mailbox*@telco.example` in one group
  and `*@telco.example` in another leave every sender the first covers
  unmatched, always.
- A pattern covers one domain. The subdomains are a rule of their own,
  `*@*.domain` for all of them (decided 2026-11-18). Such a rule is no less
  trusted than `*@domain`, since the sender is not authenticated anyway,
  only broader.
- The domain after `*.` has two names at least: `*@*.example` is refused
  as too broad. Whether two names are a registered domain, such as
  `co.uk`, is not checked.

### A topic (decided 2026-11-24)

A topic is one sentence of the owner on the mail that belongs to the
group, such as `Mail about the project Alpha: the offer, the weekly
status, the acceptance`. It is part of the prompt: the fixed text of the
prompt is versioned in the agent (`prompts/system.v1.md`), and under it
stand the name and the topic of each group to choose from. So the
sentence is configuration, and how well the agent chooses depends on how
it is written. The repository measures the fixed text on invented mail
(section 9). How a list of the owner works, the owner measures, in
`shadow` first.

- One line, at most 300 characters, and at most 50 groups have one, as
  every topic to choose from goes into each call.
- The name and the topic of each group to choose from go to the model
  with every call. With a hosted model they leave the machine: write
  nothing into them that should not.
- A changed topic changes the list, and with it the version of every
  decision (section 3): the messages are decided anew. For the group it
  means `record` again, as a changed sentence is a changed prompt, and
  setting `by_topic` back to `act` is the owner's step.

### Senders and topic together (decided 2026-11-24)

The sender rules come first, in code. The model is asked only where they
do not settle it.

| The sender matches | Who decides |
|---|---|
| a rule of one group | the code: that group, no call, whether the group has a topic or not |
| rules of several groups alike, each with a topic | the model, among these groups |
| rules of several groups alike, one without a topic | nobody: no group, as with version 1, no call |
| no rule | the model, among every group with a topic. No group has one: no group, no call |

**A domain rule is refused (decided 2026-11-18).** `categorization` sets no keyword a domain could mark with, so such a rule would
do nothing. The message says to
write `*@domain` or `*@*.domain`.

### When the list is read

- Once, at the start of the agent. A wrong list stops the start and
  `status` names what is wrong. A wrong rule is named by its group and
  its place in the group's list, `group 'Bank', sender 2`, never by
  itself, as a rule often names a person (decided 2026-11-18).
- A changed list takes effect at the next start. It is new work: the
  decision is stored under a version made from the list, see section 3.
- `categorization` reads and matches it with code of its own, which no other
  agent shares.

## 3. What happens to a message

| The message | What happens | State |
|---|---|---|
| is not in the inbox | nothing | `skipped` |
| is in the inbox and carries the agent's keyword: a person put it back | nothing | `skipped` |
| is in the inbox, no rule matches its sender | nothing. `report` counts the sender | `done`, label `none` |
| is in the inbox, rules of two groups match alike | nothing. `report` names it as ambiguous | `done`, label `none` |
| is in the inbox, one group matches, the folder exists | a move to the folder | `done`, label the group |
| the same, the folder is missing | `create_folder`, then the move | `done`, label the group |
| the same, the group is held | the move is recorded, not made | `done`, label the group |
| is in the inbox, the model chooses a group with `"by_topic": "act"` and its quote is found | as for one group by its sender: folder, move, keyword | `done`, label the group |
| the same, the group records its topic, `record` or no `by_topic` | the folder, the move and the keyword are recorded, not made | `done`, label the group |
| the same, the group is held | recorded, not made | `done`, label the group |
| is in the inbox, the model chooses a group and its quote is not found in the mail | nothing | `decided`, the decision refused for its evidence |
| is in the inbox, the model answers `none` | nothing. `report` counts the sender when no rule matched it | `done`, label `none` |
| is in the inbox, a call is due and the gateway is away | nothing yet. A message a sender rule settles goes on | `pending` |
| is in the trash, junk or spam | nothing, as it is not in the inbox. The runtime would refuse a move of it anyway | `skipped` |

A message already in another folder is the owner's choice and stays.

**The keyword (decided 2026-11-18).** With each move the agent sets its
keyword, `agent-categorized` by default, so a message it sorted is known as such
to a person in a mail client and to a state file made anew. A message in
the inbox that carries it was put back by a person and is left alone.
Besides, the runtime moves a message at most once for an agent ([agent
contract](agent-contract.md)). The keyword is its own and no other agent
sets it. A list of dimensions may name keywords of its own, which the
runtime sets as well and refuses any other (decided 2026-11-25,
[the chain](categorization-chain.md)). The agent's keyword is its own, so a move by `categorization` and a move by `invoices` stay told apart.
The keyword is asked for after the move in every stage. The runtime takes
nothing after a refused move and records only what follows a move recorded
only, by the stage or for a held group, so it never stands without the move
(decided 2026-11-18). Below `full` and for a held group the state file
holds it as recorded and not set. The name has no `$` in front, as IMAP
registers such keywords with meanings (`$Junk`, `$label1`), and it carries
the prefix `agent-` of the [agent contract](agent-contract.md), which no
mail client or other tool is known to use. `MAILBOX_AGENTS_KEYWORD` names
another.

### By stage

| Stage | Folder creation | Move | Keyword |
|---|---|---|---|
| `shadow` | recorded | recorded | recorded |
| `keyword` | recorded | recorded | recorded. It goes with the move, so the stage acts like `shadow` |
| `full` | made | made, but for a held group and for a group chosen by its topic that does not act on it | set, but for a held group and for a group chosen by its topic that does not act on it |

`by_topic` adds to the stage, it does not replace it: below `full`
nothing is made, whatever a group says. In `full` a group chosen by its
topic is acted on only with `"by_topic": "act"`, and only when it is not
held.

Below `full` a folder recorded as to be made counts as there for the
folder and the move below it in the same effect, so both are recorded.

### What is stored

- The decision by a sender rule: the label is the name of the group or
  `none`, its source is `baseline`, its details say whether one group,
  none or two alike matched, the kind of rule, and whether the group is
  held. No quote and no sender is stored. It is stored under an empty
  model alias when no group has a topic.
- The decision by the model: its source is `model`, the label the name
  of the group or `none`, the quote its evidence, as the
  [state](state.md) keeps quotes. Its details say `match` `topic` or
  `none`, `among` `senders` or `all`, for a group its `by_topic`, and
  whether it is held. `none` carries no quote.
- **The version of the decision is the prompt and the list (decided
  2026-11-18, the prompt since 2026-11-24).** It is `v1-list-` and the
  first 12 hex digits of the SHA-256 of the list as read, in JSON with
  sorted keys. A group without a topic is read without `topic` and
  `by_topic`, so a list of version 1 keeps its digest. A changed list, a
  sender, a folder, `hold`, a topic or `by_topic`, gives a new version,
  and a message taken up again, as by `backfill`, is decided anew under
  it. So the label, the details and `report` follow the
  list the message was acted on with, and a message decided `none` before
  a sender was added counts as moved once it is. The rules of the
  baseline run anew under the new version too, so `report` shows the
  baseline of the same list as the decision.
- The group is looked up again when the agent acts, against the list as it
  is then: by the sender, so a sender added to the list reaches older
  mail through `backfill`, or by its name, for a group the model chose.

## 4. The action `create_folder` (decided 2026-11-18)

Given a list, the agent may make the folders of the list itself.

| | |
|---|---|
| What | makes one folder that is missing. A folder below a missing one is made after it, each as an action of its own |
| Which | only a folder the agent was configured with: for `categorization` a folder of the list or one above it, for `invoices` the subfolder its pattern gives below a folder it looks in, and each folder between the two |
| Never | the trash, junk or spam, nor below them. Nor a folder that exists, under any case |
| When | in the stage `full`, right before the first move that needs it |
| Recorded | like every action: the path, the stage, whether it was made |
| Taken back | not by an agent: deleting a folder needs a right no agent has. An empty folder is removed by the owner |

It is the one action without a reverse of its own. It is accepted because
it changes no message.

How the runtime knows which folders an agent may make: the agent answers
for each path, with `may_create`, whether its configuration names it, and
the executor refuses any other. A method rather than a set of paths,
because `invoices` knows its subfolders only from the folder a message
lies in.

The [agent contract](agent-contract.md), [safety](safety.md) and
[mailbox service](mailbox-service.md) describe the action, the folders
an agent declares, and folder creation in `sources/mailbox.py`.

## 5. The sender is not proof

From is not authenticated. An exact address is forged as easily as a
pattern: the kinds of rule differ in how much they cover, not in how far
they can be trusted. A folder named after a bank makes a forged mail look
genuine.

What would settle it is the result of the receiving server's check of the
sender (SPF, DKIM, DMARC), which the server writes into the message. The
agents read no header of a message: `get_message` names none, and they do
not fetch the raw source. Since 0.8.0 the mailbox service names that result for each message as
`sender_check`, and `unknown` for an account without the name of its
receiving server set (measured 2026-11-19 on the test account). The agents
do not read it yet.

Until they do **a group can be held (decided 2026-11-18)**: `"hold": true`
records its moves as `shadow` does, whatever the stage of the agent, and
`report` shows them. It is meant for a group whose folder would lend trust.
Left out, a group is not held.

What is planned on top of it: a switch for a group that moves only mail
whose sender was verified ([roadmap](../../roadmap/agents.md#next)).

**What the model chooses is not proof either (2026-11-24).** As a rule an
agent only marks on the choice of a model ([safety](safety.md)). `categorization`
is the second exception, after `invoices`: it acts on the model's choice
where the owner set `"by_topic": "act"` for the group. The model names
a group of the list, never a folder, and only a group among those to
choose from. Its quote must be found in the mail, not in the topics. A
held group stays held. The risk that remains: a message that only names
a project, such as a stranger's offer that mentions it, lands in the
project's folder when its group acts.

## 6. Settings

| Setting | Meaning |
|---|---|
| `MAILBOX_AGENTS_CATEGORIZATION_FILE` | the list of section 2. Required |
| `MAILBOX_AGENTS_GATEWAY_URL`, `MAILBOX_AGENTS_GATEWAY_KEY`, `MAILBOX_AGENTS_MODEL` | required once a group of the list has a topic, else not read (2026-11-24) |

The stage, the accounts and the rest are the settings of every agent
([configuration](configuration.md)).

## 7. Which mail (decided 2026-11-18)

New mail as it arrives, and older mail only through `backfill --days N`, in
`shadow` first.

## 8. Report

- Per group: how many messages were moved, recorded, recorded by topic,
  when the model chose a group that does not act on it, held, or not
  moved, when the move was refused.
- The senders in no group that wrote most often, as candidates for the
  list. A sender the list names in several groups with a topic, whose
  message the model left in `none`, is no candidate.
- The messages left alone because two groups matched.

## 9. Evaluation

The sender rules are code, and the tests on invented mail cover them.
The choice by a topic is measured as the other agents are: a gold set
whose label is the name of the group or `none`, in the existing gold
format, the model and the rules side by side, the existing scoring. The
rules alone, the baseline, are the sender rules, so the report shows what
the topics add. The report names `none` and nothing else: each group
becomes `label-<n>` there, as a group's name is the owner's own text and
a report is versioned (decided 2026-11-19). The repository measures the
fixed text of the prompt on the invented mail of the test account
([testing](testing.md)). A list of the owner is measured on the owner's
mailbox, in `shadow`.

## 10. Tests, all on invented mail

1. Each row of the table in section 3.
2. Each row of the stage table.
3. Address before pattern, two groups alike, case ignored.
4. A wrong list: each rule of section 2 broken once, a domain rule among
   them.
5. `create_folder`: a folder of the list is made, a folder outside it is
   refused, one below the trash is refused, a folder that exists is not
   made again, a nested folder is made from the top.
6. A sender added to the list reaches a message decided before.
7. No model call is made and no call is counted for a list without a
   topic, nor for a sender one rule settles.
8. A held group in `full` moves nothing.
9. A topic: each rule of section 2 broken once, and the groups to choose
   from in each row of the table "Senders and topic together".
10. A group chosen by its topic: moved with `act` in `full`, recorded in
    `shadow`, recorded with `record` or without `by_topic`, recorded when
    held.
11. A quote not in the mail, or only in a topic, is not acted on. `none`
    needs no quote and does nothing.
12. The schema sent names only the groups to choose from and `none`, the
    prompt a line for each of them and no other.
13. A gateway that is away leaves the message that needs it `pending`,
    and a message a sender rule settles goes on in the same pass.
14. No log line names a group or a topic.

On the live setup, `live/mailbox-agents/categorization.py` runs the agent in `shadow` and in
`full` on the test account: folders made, mail moved and put back
([testing](testing.md)). What the agent relies on of the mailbox service,
a move that keeps the message's id and a folder made at the top or below
another, was measured there first
([mailbox service](mailbox-service.md)).

## 11. What was decided against

- **Categories inside `categorization` as on 2026-11-18, one agent that sorts
  and recognises invoices.** Replaced on 2026-11-25 by the chain:
  dimensions with categories, each with its recognizer, and the actions
  beside them ([the chain](categorization-chain.md)). `invoices` stays until a
  recognizer of invoices in the chain reaches its numbers on the gold set
  and a run in `shadow` on the owner's mailbox fits. The reasons of
  2026-11-18 and 2026-11-24 follow. Two agents it stayed then, for three
  reasons: an agent has one stage, a gateway that is away would hold back
  mail that needs no model, and a category is a prompt, rules and a gold
  set, not configuration. On 2026-11-24 it was decided that `categorization`
  assigns by what a message says too, through a topic per group, and
  `invoices` stays an agent of its own. The three reasons are answered
  so: how far a choice by the topic goes stands at the group, `record`
  by default, beside the one stage of the agent. A message a sender rule
  settles needs no call and goes on while the gateway is away. And with
  the fixed text of the prompt versioned in the agent, the sentence is
  configuration, measured per list.
- **Rules by words in the subject or the text, without a model.** A list
  of words is a weaker topic, and a stranger writes them as easily.
- **A group that forwards a message, or hands it to another agent
  without a folder.** Not built (2026-11-24). The list keeps apart which
  mail belongs to a group, by `senders` and `topic`, and what the group
  sets off, today its folder, so either can be added. A hand-over works
  today through the folder another agent looks in, as with `invoices`.
  One without a move would need a keyword per group or the mailbox
  service. A forward is an action that cannot be taken back: it would
  come into the [agent contract](agent-contract.md) first, with a fixed
  recipient from the list and never from the model.
- **`invoices` and `categorization` side by side with a waiting time.** A message
  whose model call waits for a gateway that is away would be moved by
  `categorization` in the meantime, and `invoices` would then skip it.
- **A keyword per group.** The runtime let an agent set one keyword, its
  own, and it stayed so on 2026-11-24. Replaced on 2026-11-25: a category
  of a list of dimensions names its keywords, only those of the list,
  each `agent-` in front ([the chain](categorization-chain.md)).
- **A gold item that names a folder.** The folder follows from the group
  and the list, and the gold format has no place for it.
- **One list for both agents.** `invoices` must work without `categorization`
  (decided 2026-11-18), so it takes folders, not groups.
