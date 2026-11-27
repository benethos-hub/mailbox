# Concept: the agent contract

Part of the [concept](../CONCEPT.md).

Every agent package defines exactly one concrete `Agent` subclass in its
`agent.py`. A package under `agents/` without `agent.py` is not an agent.
The class attributes are validated on instantiation.

**Two kinds of agent.** An agent is a classifier or an actor, a subclass of `Classifier` or of
`Actor`, both subclasses of `Agent`.

| Kind | What it reads | A model | What it writes |
|---|---|---|---|
| `Classifier` | the message, its text among it | where its limits allow | `baseline`, `decide`, `effect` and the rest of the methods below |
| `Actor` | the message as `Placed` alone | never | `waits_for`, `rule`, `act`, and `takes` if it wants |

A classifier reads a message and answers a question about it, with
rules or with the model. `awaiting_reply`, `inquiries`, `categorization`
and `counting` are classifiers. An actor acts on mail by its keywords,
by a list its owner wrote, with no model and without reading what a
mail says. Actors are agents of their own, not instances of
`categorization` (decided 2026-11-25). `categorization` keeps its
moves until an actor that files mail has proven itself in `shadow` and
Gmail is reached through labels: until then there are two ways to the
same move (decided 2026-11-27).

An actor sees a message as `Placed`:

| `Placed` shows | |
|---|---|
| `ref` | the ids of account and message |
| `folders` | its folders by path and role, `in_inbox`, `own_folder` |
| `keywords` | the keywords it carries |
| `sender_check` | what the receiving server stated about the domain of its sender: `pass`, `fail` or `unknown` |
| `sent_by(addresses)` | whether it came from one of `addresses`, yes or no. The address itself is out of `repr` and of a comparison |

Never its subject, text, sender or the names of its attachments. The
code keeps this narrow view, not a right of the mailbox service: the
service has no right to read the metadata of a mail alone.

The base `Actor` puts the methods of `Agent` together from `rule` and
`act`. `admit` takes a message that carries a keyword `waits_for`
names, lies in none of the trash, junk, spam, drafts or sent mail, and
that `takes` takes. `baseline` and `decide` answer `rule`, `effect`
answers `act`, `decide_again` answers `admit`, and `refresh` works the
rule out anew. `message.created` is decided and `message.updated`
observed, so a new message without a waited keyword ends `skipped`,
an update that shows one takes it up again, and `backfill` reaches
mail that carries one. A decision is labelled `rule-<n>` by the place
of its rule, from 1, or `none`, and the version of its list is a
digest of it (`list_version`), so a changed list is new work. The
contract refuses an actor whose limits allow a model call, and one
that writes one of the methods the base puts together.

| Attribute | Meaning |
|---|---|
| `name`, `version`, `description` | identity. `name` equals the package name |
| `triggers` | the feed events it wants, each with its route, `decide` or `observe`, and whether it wants the tick |
| `actions` | the actions it may take, from the list below |
| `limits` | model calls per message and per day, the longest quote or value an answer may hold, 300 characters, and the forwards it may draft per day, none by default |
| `requires` | settings that must be present before it starts |
| `default_keyword` | the keyword it sets when `MAILBOX_AGENTS_KEYWORD` is unset |
| `former_names` | the names it had before: it does not start beside a state file of one, and `status` names one. None by default, `sorting` for `categorization` (2026-11-25) |
| `prompt_version` | the version of the prompt its model step runs under. Read from the instance: `categorization` sets it from its list |
| `skip_marked` | whether a message that carries its keyword and that its state file does not know is `skipped` before baseline and model. Off by default |
| `report_labels`, `report_fields` | the labels and field names an evaluation report names in plain text, its own fixed ones. Any other, such as the name of a group of `categorization`, becomes `label-<n>` or `field-<n>` there (decided 2026-11-19). None by default |
| `peer_fields` | whether the fields of a decision are categories of the owner's list, which a peer over A2A may be told ([a2a.md](a2a.md)). Off by default, as a field may hold a value taken from the mail |

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
| `inquiries` | off | its state file holds the fields of an inquiry, which a skipped message would lack |
| `awaiting_reply` | off | it watches its marked mail to take the keyword off |
| `counting` | off | it sets no keyword |
| `categorization` | off | its own rule is stricter: `admit` refuses every message in the inbox that carries its keyword |
| `filing` | off | its own rule is stricter: `takes` refuses every message that carries its keyword |
| `forwarding` | off | it sets no keyword, its state file holds what it forwarded |

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
| `awaiting_reply` | `agent-awaiting-reply` |
| `inquiries` | `agent-inquiry` |
| `categorization` | `agent-categorized` |
| `counting` | `agent-counted`, never set |
| `filing` | `agent-filed` |
| `forwarding` | `agent-forwarded`, never set |

`MAILBOX_AGENTS_KEYWORD` names another keyword for one deployment.

| Method | Meaning |
|---|---|
| `select(event)` | whether this event concerns the agent, and its route: `decide` or `observe`. Code only. By default the route its `triggers` name for the type of the event (2026-11-23) |
| `admit(message)` | after the fetch, whether the message is one for the agent, such as one in the inbox. Code only |
| `baseline(message)` | the question answered by rules |
| `decide(message, context)` | the question answered with the model, within the limits |
| `effect(decision, message, context)` | the actions that follow from a decision |
| `observe(message, context)` | for an event routed to `observe`: the actions it calls for, no model |
| `tick(now, context)` | for agents with deadlines: what is due |
| `prepare()` | reads what the agent needs beyond its settings, such as a list in a file |
| `asks_model()` | whether the agent, as configured, asks a model and needs the gateway. Asked after `prepare()`. By default whether its limits allow a call. `categorization` asks one only when a recognizer of its list does: a category with a topic, or one that names the recognizer `invoice` (2026-11-25) |
| `backfill_folder(folder)` | whether `backfill` takes up the messages of this folder besides the inbox and sent mail. No folder by default |
| `folders_needed()` | the folders its configuration names and expects to be there, which `status` looks up. None by default |
| `describe_folders(folders)` | for `status`: a line for each folder of an account that matters to it, such as one it looks in and what it does there. `folders` are the account's folders by path. Folder names only. Asked of an agent whose `folders_needed()` names one, nothing by default |
| `keywords()` | the keywords the runtime may set and take off for it: its own, and those its configuration names, such as the keywords of the list of `categorization` (decided 2026-11-25). Code only, never from an answer of the model. Its own by default |
| `recipients()` | the addresses the runtime may draft a forward to for it, in lower case: from its configuration, never from a mail or an answer of the model. None by default (2026-11-27) |
| `may_create(path, folders)` | whether the runtime may make the folder at `path` for it: one its configuration names. `folders` are the account's folders by path, so an answer may rest on the folder above and its role. Code only, no folder by default |
| `decide_again(message)` | after `observe`: whether the message is decided again, taken up anew as `backfill` does, such as one given a keyword the agent waits for. Code only. No by default (2026-11-25) |
| `refresh(stored, message)` | a decision stored before, as it holds for the message now: what code decides may be worked out anew, never what the model answered. The runtime asks it before it reuses a stored decision. Unchanged by default (2026-11-25) |
| `alone(part)` | for `eval --recognizer`: one part of the agent as an agent of its own, scored alone in its own space, such as the recognizer `invoice` of `categorization`. None by default (2026-11-25) |
| `check_together(configured)` | a class method, for the command `check`: what is wrong with the configuration of several instances of the agent together, each file by the name of its instance, a line per problem, such as a circle of lists of `categorization` that set each other off. None by default (2026-11-25) |
| `trace_parts(decision)` | the parts of a decision a span names below the span of the decision, such as the dimensions of `categorization`: a kind and attributes that are ids, states, counts or codes, never anything of the mail or the owner's text. None by default (2026-11-25) |
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
| `draft_forward` | none by an agent: the draft lies in the owner's drafts folder, where the owner deletes it. It changes no message and sends nothing |

An agent declares which of them it uses, and the runtime carries out no
other. A new action is added here first, with how it is taken back.

**A forward as a draft (decided 2026-11-27).** `draft_forward` puts a
forward of a message into the drafts folder of its account, to the
addresses the agent names, and sends nothing. It has no way back by an
agent, as `create_folder` has none, and is accepted for the same
reason: it changes no message. The runtime takes it only on these
terms: it is declared, the account is one the agent works on, every
address is one that `recipients()` of the agent names, from its
configuration and never from a mail or an answer of a model, the form
is `inline` or `attachment`, the message lies in none of the trash,
junk, spam, drafts or sent mail, there is no forward drafted for it
yet, and no more drafts were made today than `limits` allows. The
stages `suggest` and `full` take it. Sending is not built: no agent
sends.

The runtime carries out an action only on these terms: it is declared, a
keyword is one the agent names in `keywords()`, its own or one its
configuration names (2026-11-25), a move goes into a folder that exists and is
neither the trash, junk or spam nor below them, the message itself is in
none of them nor in a folder below one, and the account is one the agent
works on. A message in one of them is the owner's choice: its action is
logged as refused and not counted as a failure, and the runtime notes it
so an item of it is not asked about again. The path of a folder, for a move or to be made, is names between
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
[categorization](agent-categorization.md) whose folder would lend a forged mail trust.
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
it. A move only recorded in `shadow` or `suggest` does not count. A message
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
setting is missing, without starting it. The settings of the gateway are
required of an agent whose `asks_model()` says so once it is prepared,
and an agent that cannot be prepared yet, as a setting of its own is
missing, is not asked. For a ready agent that names
folders it expects, it looks them up in the mailbox service, in each
account the settings name or else in each account the user is granted,
lists the lines `describe_folders` gives per account, and names each one
missing or there in another case only.
