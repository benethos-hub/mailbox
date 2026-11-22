# Concept: the agent contract

Part of the [concept](../CONCEPT.md).

Every agent package defines exactly one concrete `Agent` subclass in its
`agent.py`. A package under `agents/` without `agent.py` is not an agent.
The class attributes are validated on instantiation.

| Attribute | Meaning |
|---|---|
| `name`, `version`, `description` | identity. `name` equals the package name |
| `triggers` | the feed events it wants, and whether it wants the tick |
| `actions` | the actions it may take, from the list below |
| `limits` | model calls per message and per day |
| `requires` | settings that must be present before it starts |
| `default_keyword` | the keyword it sets when `MAILBOX_AGENTS_KEYWORD` is unset |
| `prompt_version` | the version of the prompt its model step runs under. Read from the instance: `sorting` sets it from its list |
| `skip_marked` | whether a message that carries its keyword and that its state file does not know is `skipped` before baseline and model. Off by default |
| `report_labels`, `report_fields` | the labels and field names an evaluation report names in plain text, its own fixed ones. Any other, such as the name of a group of `sorting`, becomes `label-<n>` or `field-<n>` there (decided 2026-11-19). None by default |

**Marked mail a state file does not know (decided 2026-11-19).** An agent
that declares `skip_marked` leaves a message alone that carries its keyword
while its state file holds no step for it: the message was marked before
this state file, by the agent before the file was made anew or by a
person. It is not asked about again and not moved again. A message the
state file knows goes on as before, so `backfill`, which takes up again
the messages decided before, still reaches it after a change of stage or
prompt, and an update routed to `observe` is
not touched. A person takes the keyword off to have the message looked at
again: the update that shows it without the keyword makes it `pending`
anew, as long as no step of it is stored and the agent admits it
(2026-11-19). A message moved by a mail client keeps its id at the service
([mailbox service](mailbox-service.md)), so this matters after a state file
made anew, not after each move. Which agents declare it, and why the
others do not:

| Agent | `skip_marked` | Why |
|---|---|---|
| `invoices` | on | a filed invoice the owner took out of its subfolder stays where the owner put it, also after a state file made anew |
| `inquiries` | off | its state file holds the fields of an inquiry, which a skipped message would lack |
| `awaiting_reply` | off | it watches its marked mail to take the keyword off |
| `counting` | off | it sets no keyword |
| `sorting` | off | its own rule is stricter: `admit` refuses every message in the inbox that carries its keyword |

**An agent's keyword is `agent-<word>` (decided 2026-11-18).** A keyword
in that form is recognisable as set by an agent, shares no name with a
keyword another mail client or tool uses, and carries no `$` in front, as
IMAP registers such keywords with meanings, `$Junk` for a spam filter,
`$label1` for a tag of Thunderbird. It is lower case, as a service may
answer keywords in lower case. The contract refuses a `default_keyword`
that is not lower case letters, digits and dashes, the same form
`MAILBOX_AGENTS_KEYWORD` must have (2026-11-20). The defaults:

| Agent | Keyword |
|---|---|
| `invoices` | `agent-invoice` |
| `awaiting_reply` | `agent-awaiting-reply` |
| `inquiries` | `agent-inquiry` |
| `sorting` | `agent-sorted` |
| `counting` | `agent-counted`, never set |

`MAILBOX_AGENTS_KEYWORD` names another keyword for one deployment.

| Method | Meaning |
|---|---|
| `select(event)` | whether this event concerns the agent, and its route: `decide` or `observe`. Code only |
| `admit(message)` | after the fetch, whether the message is one for the agent, such as one in the inbox. Code only |
| `baseline(message)` | the question answered by rules |
| `decide(message, context)` | the question answered with the model, within the limits |
| `effect(decision, message, context)` | the actions that follow from a decision |
| `observe(message, context)` | for an event routed to `observe`: the actions it calls for, no model |
| `tick(now, context)` | for agents with deadlines: what is due |
| `prepare()` | reads what the agent needs beyond its settings, such as a list in a file |
| `backfill_folder(folder)` | whether `backfill` takes up the messages of this folder besides the inbox and sent mail. No folder by default |
| `folders_needed()` | the folders its configuration names and expects to be there, which `status` looks up. None by default |
| `describe_folders(folders)` | for `status`: a line for each folder of an account that matters to it, such as one it looks in and what it does there. `folders` are the account's folders by path. Folder names only. Asked of an agent whose `folders_needed()` names one, nothing by default |
| `may_create(path, folders)` | whether the runtime may make the folder at `path` for it: one its configuration names. `folders` are the account's folders by path, so an answer may rest on the folder above and its role. Code only, no folder by default |
| `summarize(shown)` | for `report`: lines about the messages shown, each given as sender, decision and its actions with whether each was carried out |

An event routed to `decide` makes the message `pending` and runs the steps
of [runtime](runtime.md) once per message, prompt version and model. An
event routed to `observe` is one that may come many times for one message,
such as an update of its flags. It is fetched and handed to `observe` at
once.

The `context` is all an agent reaches while it works: the model, as one call
with a schema that the runtime counts, records and keeps the content of for
the evidence check, the mailbox read-only, its open items, and `now`, the
clock of the runtime. The items are opened, started again, read, by
message, by thread or when due, closed with a reason, and found closed
with their keyword still counted as set (`marked_closed`, 2026-11-20). Its settings an agent has as `self.settings`, not in
the context (2026-11-19). An agent never holds the mailbox client, the
gateway client or the state file.

The actions that exist:

| Action | Reversible by |
|---|---|
| `add_keyword` | `remove_keyword` |
| `remove_keyword` | `add_keyword` |
| `move_to_folder` | a move back, the previous folder is recorded |
| `create_folder` | none by an agent: deleting a folder needs a right no agent has. The owner removes an empty one |

An agent declares which of them it uses, and the runtime carries out no
other. A new action is added here first, with how it is taken back.

The runtime carries out an action only on these terms: it is declared, a
keyword is the agent's own, a move goes into a folder that exists and is
neither the trash, junk or spam nor below them, the message itself is in
none of them nor in a folder below one, and the account is one the agent
works on. The path of a folder, for a move or to be made, is names between
slashes: one that starts or ends with a slash, holds two in a row or names
`.` or `..` is refused, whatever the agent may make. A folder is made only when the agent's `may_create` answers yes
for its path, the folder above it exists and is none of those three nor
below them, and no folder of the same name exists in another case. A folder
below a missing one is made after it, each as an action of its own,
recorded under the message whose move needs it. Before the folders and the
move of a message, the runtime reads the account's folders anew, so a
folder the owner deleted or renamed since the last look is made again, not
taken as there. One deleted between that look and the write refuses the
folder or the move, and the message stays where it is, not ended as gone.
`create_folder` is the one action without a reverse of its own. It is
accepted because it changes no message (decided 2026-11-18). An action
whose result is already there is not taken again. A write whose answer does
not come, a timeout or a service away, is looked up at once: an action
whose result is there counts as taken, so a move that went through counts
as the agent's one move, and one whose result is not there is dropped. When
the service cannot tell either, it stays recorded and not taken. What the
stage does not allow is recorded as what would have been done, and so is an
action the agent asks to be `held`, whatever the stage: for a group of
[sorting](agent-sorting.md) whose folder would lend a forged mail trust.
An action recorded and not taken is recorded once per message and stage:
asked for again with the same argument, as by a second `backfill`, it adds
no row and no log line, and counts as recorded (decided 2026-11-18). A
folder recorded and not made counts as there for the folder and the move
below it in the same effect, and they are recorded only too, whatever the
stage: a stage that records only, or a folder held, records the folders and
the move alike, and never sends a move into a folder that is not there.

**A message is moved at most once by one agent (decided 2026-11-18).** A
move of a message the agent has moved before is not taken, so a message the
owner moved back, into the inbox or anywhere, stays where the owner put it,
also when `backfill` takes it up anew. It is a settled state, not a
refusal: the line `actions.kept` says so at INFO, no failure is counted,
however often an update asks for the move again (2026-11-19). The folders
the move would need are not made either, so no empty folder is left behind
it. A move only recorded in `shadow` or `keyword` does not count. A message
moved by hand never wanders back in a later pass. The actions of one
message are taken in order, and after a refused move or folder, or a move
not taken, the rest are not taken.
After a move or folder recorded only, by the stage or held, the rest are
recorded only, as if held, whatever the stage allows (decided 2026-11-18).
So a keyword that says a message was moved never stands without the move,
and the rule lives in the runtime alone: an agent asks for its actions
whatever the stage and compares no stage. This holds for an effect, for
`observe` and for the tick alike: the tick's actions are taken message by
message.

`status` reports for each agent whether it is ready and which required
setting is missing, without starting it. For a ready agent that names
folders it expects, it looks them up in the mailbox service, in each
account the settings name or else in each account the user is granted,
lists the lines `describe_folders` gives per account, and names each one
missing or there in another case only.
