# Concept: the agent `invoices`

Part of the [concept](../CONCEPT.md).

> **Status: version 5, prompt `v4`. Evaluated on the invented mail of the
> test account and run there in `shadow` beside
> [sorting](agent-sorting.md). Not run on a real mailbox in this version.
> A run on the owner's account is the owner's decision, in `shadow`
> first.**

**Question:** is this message an invoice?

| | |
|---|---|
| Triggers | `message.created` in the inbox or in a folder it looks in, and `message.updated` for a message with an open item |
| Baseline | a PDF or XML attachment, invoice words in subject and attachment names, phrases of a notice that an invoice waits at the supplier, near-miss words in the subject, a receipt that carries its invoice taken as one, and a credit note. The sender plays no part |
| Model | label `invoice` or `other`, for `other` the near miss it is: reminder, quotation, order confirmation, payment receipt, none. One quote |
| Actions | `add_keyword`, `move_to_folder`, and `create_folder` for the subfolder only |

**What counts (decided 2026-11-17).** An invoice is a message that carries
an invoice a supplier sent, or that tells one is ready to be fetched. The
second kind matters: many suppliers send a notice and no file. A receipt
that carries the invoice for its payment is an invoice too, whatever it
calls itself. Only a confirmation of a payment with no invoice is the near
miss `payment_receipt` (decided 2026-11-18: the owner's receipts of a
subscription carry the invoice, and prompt `v1` left them out). A credit
note (German `Gutschrift`) counts as an invoice too: it books like one with
the opposite sign (decided 2026-11-18 for now, prompt `v3`).

**The folder says whose invoice it is (decided 2026-11-18).** `invoices`
asks one question: is this message an invoice? It no longer asks from which
supplier. It moves an invoice into a subfolder of the folder it lies in.
Who put the message there does not matter: [sorting](agent-sorting.md), a rule of
the mail server or the owner by hand. Filing by provider comes first, the
subfolder for invoices in a second run.

**It works without `sorting` (decided 2026-11-18).** So the folders it
looks in are a setting, and it knows nothing of groups or sender rules.

## Settings

| Setting | Meaning | Unset |
|---|---|---|
| `MAILBOX_AGENTS_INVOICES_FOLDERS` | the folders it looks in, separated by commas. `Parent/*` stands for every folder directly below `Parent`, `*` for every folder at the top without a role | the inbox alone |
| `MAILBOX_AGENTS_INVOICES_SUBFOLDER` | where an invoice goes, as a pattern that starts with `{folder}/`, the folder the message lies in, such as `{folder}/Rechnungen` | an invoice is marked and stays |
| `MAILBOX_AGENTS_INVOICES_INBOX_FOLDER` | a folder for an invoice found in the inbox. It must be there and it is not made. It is an end station: looked in when `MAILBOX_AGENTS_INVOICES_FOLDERS` takes it in, and nothing moves on from it | it is marked and stays in the inbox |

The inbox is always looked in. A folder is named by its path, case
counting. A message in the subfolder of a folder looked in, or in a
folder between the two, is not looked at, so an invoice is not asked
about twice. Another folder below one looked in is looked in when the
settings take it in, as `Providers,Providers/*` takes in
`Providers/CloudHost`. The
subfolder of a folder it looks in and the folders between the two are
never looked in, even where the settings would take them in:
`Invoices,Invoices/*` takes in `Invoices/Rechnungen`. An invoice put there
is not filed again, and no empty subfolder is made below it.

**The inbox folder is an end station (decided 2026-11-19).** It is a
folder like any other, but nothing moves on from it:

| Folder | Looked in | An invoice there |
|---|---|---|
| the inbox | always | the keyword and an open item, and a move to the inbox folder when one is set other than the inbox itself. Set to the inbox, it moves nothing, and `status` says so (2026-11-19) |
| a folder the settings take in | when `MAILBOX_AGENTS_INVOICES_FOLDERS` takes it in | the keyword and a move to the subfolder |
| the inbox folder | when `MAILBOX_AGENTS_INVOICES_FOLDERS` takes it in, as `*` takes in one at the top or `Invoices/*` takes in `Invoices/Telco` | the keyword, and it stays. No subfolder is made below it |
| a subfolder, such as `Invoices/Hosting/Rechnungen` | never | |

It is looked in because an inbox folder that is also a folder of a group
of `sorting`, or one the settings take in, would otherwise leave an
invoice put there by `sorting` or by hand neither marked nor filed,
silently. Such an invoice is asked about and marked. An invoice the owner
puts into the end station by hand costs a model call.
One the agent moved there itself is known to its state file and costs
none. The test of the subfolder comes first: an inbox folder where the
pattern of the subfolder points, such as `Invoices/Rechnungen` beside
`Invoices` and `{folder}/Rechnungen`, is a subfolder and not looked in.

**`*` takes in the owner's own folders (decided 2026-11-18).** It covers
every folder at the top that has no role, the owner's own among them, so
the folders of [sorting](agent-sorting.md) may lie at the top. The inbox, sent
mail, drafts, the trash, junk, the archive and a folder of all mail have a
role and are not taken in. A folder named by its path is looked in whatever
its role, but the trash, junk and spam. The runtime makes a subfolder only
below a folder that exists and that the agent looks in, judged with its
role, so `*` makes none below sent mail, drafts or the inbox.

`Parent/*` and `*` are matched against the path of the folder a message
lies in, not resolved once at the start, so a folder `sorting` makes later
is looked in at once. At the start the settings are checked: a wrong one
stops it. `status` looks up in the mailbox service the folders that should
be there, those named, the parents of `Parent/*` and the inbox folder, and
names each one missing in each account the settings name, or without
`MAILBOX_AGENTS_ACCOUNTS` in each account the user is granted, as
`get_me` answers them (since 2026-11-18). A missing one does
not stop the start, as `sorting` may make it later. One whose name is
there in another case only is named as such: the runtime neither moves
into it nor makes it.

`status` also lists, per account, the folders that matter (since
2026-11-19): the inbox, each folder it looks in with where an invoice
there goes, the inbox folder as an end station or as not looked in, and
each subfolder there is, which it does not look in. So an inbox folder
the settings do not take in, where an invoice put by hand stays unmarked,
shows before it is missed. Folder names are no content of a mail, and
`status` prints to standard output, not to the log.

```
invoices 5: ready
  folders in acc_1:
    INBOX: looked in, an invoice moves to Invoices/Telco
    Invoices/Hosting: looked in, an invoice moves to Invoices/Hosting/Rechnungen
    Invoices/Hosting/Rechnungen: subfolder, not looked in
    Invoices/Telco: end station, looked in, an invoice is marked and stays
```

`backfill` takes up the messages of the last days in the inbox and in every
folder it looks in, account by account, each folder by its id.

## What happens to a message

| The message | What happens |
|---|---|
| lies in no folder it looks in | nothing, `skipped` |
| carries the keyword, and the state file holds no step of it | nothing, `skipped`, before the rules and the model |
| is no invoice | nothing |
| is an invoice in a folder it looks in | the keyword, and a move to the subfolder, made when missing, each folder of the path as an action of its own |
| is an invoice in a folder it looks in, no subfolder pattern set | the keyword. It stays |
| is an invoice in the inbox folder, which it looks in | the keyword. It stays, and nothing is made below it |
| is an invoice in the inbox | the keyword and an open item, and it stays. With an inbox folder set, which must be there, the keyword, a move into that folder and an open item too, which closes once the message lies there: as `filed` when the agent looks in the inbox folder, as `moved_elsewhere` when it does not. While the move is not taken, the folder missing or the stage below `full`, the item stays open, so a later move into a folder it looks in still files the invoice |
| was marked in the inbox and now lies in a folder it looks in | a move to the subfolder, no model call. The open item closes as `filed` |
| was marked in the inbox and now lies in a folder it does not look in | nothing. The open item closes as `moved_elsewhere` |
| has an item closed as `filed` and still lies in a folder it looks in | a move to the subfolder again, as for an open item |
| was marked in the inbox and is deleted since, its update answered `404` | nothing. The open item closes as `message_gone` |

The item closes before the runtime takes the actions. A mailbox service
that is away in between leaves the cursor where it was, and the same
update comes again: so an item closed as `filed` whose message still
lies in a folder the agent looks in is filed again, and what is already
there is not done twice.

Where the message lies is looked up again when the agent acts. In
`shadow` the keyword, the folders and the move are recorded, in `keyword`
the keyword is set and the rest recorded. The runtime moves a message at
most once for the agent, so an invoice the owner takes out of its
subfolder stays where the owner put it.

**Marked mail the state file does not know is skipped (decided
2026-11-19).** The runtime's record of a move lives in the state file. A
state file made anew, or a message that comes back under another id,
would let a filed invoice the owner pulled out of its subfolder be asked
about and moved again. So `invoices` declares `skip_marked`
([agent contract](agent-contract.md)): a message that carries its
keyword and that its state file does not know ends as `skipped`, before
the rules and the model. It costs this: a marked message unknown to the
state file that lies in a folder it looks in stays there, marked and not
filed, as whether it was handed over or pulled back cannot be told from
the message. Nothing moving is the safe side, as mail moved by hand never
wanders back (decided 2026-11-18). To have such a message looked at
again, take the keyword off: the update the service reports then takes
it up again, in the same pass or the next (2026-11-19). A message the state file knows goes on:
`backfill`, which takes up again the messages decided before, still
reaches the marked messages after a change of stage or prompt, and an invoice marked in the inbox and moved later is filed over
its open item and the update, as before. A move by a mail client keeps the
message's id at the service ([mailbox service](mailbox-service.md),
measured 2026-11-19), so the open item follows it.

**An invoice in the inbox is marked only, unless the owner sets a folder
(decided 2026-11-18).** A forged invoice is the commonest bait, and a
folder the model fills on its own judgement would make one look checked.

**No answer of the model chooses a folder.** The schema holds a label, a
near miss and a quote, nothing else: an answer with another field is
refused. The folder follows from where the message lies and the settings.

The prompt is `prompts/system.v4.md`, version `v4`. It names no supplier.
The model is given the sender, the subject, the names and types of the
attachments and the first 6000 characters of the text. A stranger chooses
all of them, so each is cut (2026-11-19): the sender's name and the
subject at 300 characters, the attachments to the first 20 whose line
stays within 1000 characters. The sender's address is cut at 320
characters (2026-11-20), as much as the mail standards allow. The
evidence check looks a quote up in the same cut text.

Recognising an electronic invoice by its embedded data needs the attachment
read and is not part of this version.

## Beside `sorting`

Without an inbox folder, whichever agent comes first, the end is the same:

- `invoices` first: the message is marked in the inbox and gets an open
  item. `sorting` moves it. The move reaches `invoices` as an update of the
  message, it finds the open item, sees the message in a folder it looks in
  and moves it on.
- `sorting` first: `invoices` finds the message in the folder it looks in
  and moves it on after its decision.

With an inbox folder set, an invoice `invoices` takes up first goes into
that folder, and `sorting` leaves it there. Its item closes and the
invoice stays there, as nothing moves on from the end station. While that
move is not taken, the folder missing or the stage below `full`, the item
stays open and the invoice goes the way of `invoices` first above: once
`sorting` moves it into a folder the agent looks in, it is filed there.
`sorting` first ends as without an inbox folder. An invoice `sorting` puts
into the inbox folder itself, before `invoices` takes it up, is marked
there and stays when the settings take that folder in. When they do not,
it is neither marked nor filed.

The open item and the look at an updated message are what
[awaiting reply](agent-awaiting-reply.md) uses already. An open item of an
invoice has no deadline: its due date lies in the year 9999, and the agent
has no tick. Every update of a message is fetched and looked at, as for
`awaiting_reply`, and one without an open item ends there.

## What changed from version 4

| Part | Version 4 | Version 5 |
|---|---|---|
| The inbox folder | never looked in | an end station: looked in when `MAILBOX_AGENTS_INVOICES_FOLDERS` takes it in, an invoice there is marked and stays |
| An invoice moved from the inbox into the inbox folder | its item closes as `moved_elsewhere` | its item closes as `filed` where the agent looks in that folder |
| Marked mail the state file does not know | asked about, and moved when the state file has no record of a move | `skipped` before the rules and the model |
| Prompt | `v4` | `v4`, unchanged |

The agent version is 5, and it starts in `shadow` (decided 2026-11-19).

## Checked live, version 5

`live/mailbox-agents/invoices.py` ran on the test account on 2026-11-19 with version 5,
`invoices` in `shadow` and the model of the live setup, and all its checks
passed. The two orders beside `sorting` ended as with version 4. Then:

- The end station: an invoice of the inbox moved by hand into
  `Invoices/Telco`, the inbox folder, which `Invoices/*` takes in. A
  `backfill` with a new state file decided it an invoice and recorded the
  keyword alone, no folder and no move below it. The folder line of
  `status` read `Invoices/Telco: end station, looked in, an invoice is
  marked and stays`.
- Marked mail under a state file made anew: an invoice of the inbox given
  the keyword `agent-invoice` beforehand ended as `skipped`, with no step
  and no model call, and the other three invoices were decided.

Each check put the mail back, compared by Message-ID. Against the mailbox
service 0.7.5 two of the four messages `sorting` had moved were named
under another id after they were moved back, in each of four runs.
Against 0.8.0, on the same day, none was
([mailbox service](mailbox-service.md)).

## Measured, version 5

On the 12 invented messages of the test account, 2026-11-20, the reports
`2026-11-20-v5-v4-*` in `reports/mailbox-agents/invoices/`. The prompt is `v4` as in
version 4. The twelfth message, a receipt that carries its invoice, came
after the measurement of version 4. Numbers on invented mail say that the
agent works as built, not how well it sorts real mail.

| Model | Right | Invoices found | Near miss invented | Tokens in per message |
|---|---|---|---|---|
| `mail-classifier` (Claude Haiku 5.5) | 12 of 12 | 4 of 4 | 1 | 1082 |
| `mail-classifier-gpu` (local) | 12 of 12 | 4 of 4 | 2 | 496 |
| `mail-classifier-cpu` (local) | 12 of 12 | 4 of 4 | 2 | 496 |
| the rules alone | 11 of 12 | 4 of 4, and one more | | |

The other models of the gateway are in the table of
[containers/live/mailbox-agents/README.md](../../../containers/live/mailbox-agents/README.md).

## What changed from version 3

| Part | Version 3 | Version 4 |
|---|---|---|
| Question | an invoice, and from which listed supplier | an invoice |
| Triggers | `message.created` | `message.created`, and `message.updated` for a message with an open item |
| `admit` | in the inbox | in the inbox or in a folder it looks in |
| Model answer | label, near miss, supplier, two quotes | label, near miss, one quote |
| Prompt | `v3`, names the suppliers | `v4`, names none |
| Baseline | uses the supplier list | the invoice rules alone |
| Where an invoice goes | the folder of its supplier under one parent, by a sender rule of the list | the subfolder of the folder it lies in |
| Actions | `add_keyword`, `move_to_folder` | the same and `create_folder`, for the subfolder only |
| `report` | senders of invoices without a supplier | senders of invoices marked and not moved, as candidates for a group of `sorting` |
| Evaluation | label, and the supplier by its source | label alone |

The senders `report` lists count an invoice marked in the end station
too, although it is where it belongs: the report knows what was decided
and done for a message, not the folder it lay in, so it cannot tell such
an invoice from one left in the inbox (2026-11-19).

Version 3 decided the supplier by a sender rule of a list, and the model
could name one of the list with a quote that names it (decided 2026-11-17).
Only an address or a pattern rule moved. That list and its rules are now
the business of [sorting](agent-sorting.md), which moves by the sender before
`invoices` asks its question.

The existing gold set still serves: its labels stay. The invented gold sets
dropped their supplier field. In a gold file that still names one, the
supplier counts as missing, as the agent no longer answers it: drop the
field. The settings of version 3, `MAILBOX_AGENTS_INVOICES_FOLDER` and
`MAILBOX_AGENTS_INVOICES_SUPPLIERS_FILE`, went with the supplier list. A
`.env` that still names them starts, as an unknown setting is ignored.

## Measured, version 4

On the 11 invented messages of the test account, 2026-11-18, the reports
in `reports/mailbox-agents/invoices/`. Numbers on invented mail say that the agent works
as built, not how well it sorts real mail.

| Model | Right | Invoices found | Near miss invented | Tokens in per message |
|---|---|---|---|---|
| `mail-classifier` (Claude Haiku 5.5) | 11 of 11 | 3 of 3 | 1 | 1081 |
| `mail-classifier-gpu` (local) | 11 of 11 | 3 of 3 | 2 | 495 |
| the rules alone | 10 of 11 | 3 of 3, and one more | | |

`live/mailbox-agents/invoices.py` ran `invoices` in `shadow` with `Providers/*` and
`{folder}/Rechnungen` beside `sorting` in `full`, in both orders.
`invoices` first: it marked the three invoices in the inbox and opened an
item for each. Once `sorting` had moved two of them, their updates reached
`invoices` through the feed after about 23 seconds, and it recorded the
folders and the moves into `Rechnungen` with no further model call. The
third, of a held group, stayed in the inbox with its item open. `sorting`
first: `backfill` found the two in the folders of their groups, and
`invoices` recorded the same. The mail was put back.
