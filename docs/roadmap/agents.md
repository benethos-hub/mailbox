# Roadmap: the agents

Part of the [roadmap](../ROADMAP.md): the agents, `mailbox-agents`,
alpha. Their concept is [docs/mailbox-agents/CONCEPT.md](../mailbox-agents/CONCEPT.md).

## The agents

### Built

Version 0.11.0 holds the runtime and the agents `counting`,
`invoices`, `awaiting_reply`, `inquiries` and `categorization` (named
`sorting` until 2026-11-25). `invoices` was removed on 2026-11-25, its
question is the recognizer `invoice` of `categorization`
([the chain](../mailbox-agents/concept/categorization-chain.md#from-invoices)). The others are each described in
its file under [concept/](../mailbox-agents/concept/). All of it ran on the test account of
invented mail. On a real mailbox, read-only and in `shadow`: `invoices`
version 3 on 2026-11-18, `categorization` and `invoices` on 2026-11-22, and
`invoices`, `inquiries` and `awaiting_reply` in the versions of 0.11.0
on 2026-11-23, and the recognizer `invoice` beside `invoices` on
2026-11-25. None changed anything.

Since 2026-11-24 `categorization` version 2 also assigns a message by the topic
of a group, a line of the owner that a model is given, where no sender
rule settles it. Its choice is recorded only, unless the group acts on
it ([categorization](../mailbox-agents/concept/agent-categorization.md)).

Since 2026-11-25 `categorization` version 3 runs a chain: a list of dimensions
run one after another, each category found by its sender, its topic or
a recognizer of a register, and what follows from it named beside it, a
keyword, a move, a folder below, by priority and with a stage per entry
([the chain of categorization](../mailbox-agents/concept/categorization-chain.md)).

Since 2026-11-25 several instances of `categorization` hand a message
on by keywords, each with a list and a state file of its own, and the
command `check` names lists that set each other off
([the chain](../mailbox-agents/concept/categorization-chain.md#8-instances-that-hand-a-message-on)).
Each agent can export spans over OpenTelemetry
([operation](../mailbox-agents/concept/operation.md)).

Since 2026-11-25 an agent answers another agent over A2A how it
classifies a message, read only, behind a token
([peers over A2A](../mailbox-agents/concept/a2a.md)).

Since 2026-11-27 an agent is a classifier or an actor. The first
actor, `filing`, files mail into folders by its keywords, by a list,
with no model and nothing of what a mail says
([filing](../mailbox-agents/concept/agent-filing.md)). The second,
`forwarding`, drafts a forward of mail by its keywords, to the
addresses of its list, and sends nothing
([forwarding](../mailbox-agents/concept/agent-forwarding.md)).

Since 2026-11-27 the command `cockpit` shows what every agent did on
read-only pages, read from the state files by a process of its own,
started by hand and behind a secret, as a prototype
([cockpit](../mailbox-agents/concept/cockpit.md)).

Since 2026-11-27 the state of an agent can lie on PostgreSQL, in a
database of its own for each agent and instance, on the storage layer of
`mailbox-common` the service stands on as well. The agent closes its
database to every other role at each start and gives the read to the
roles it names. `storage provision` makes the role and the database,
`storage move` copies a state file over, `status`, `paths`, `health`
and `report` read either, and the cockpit reads the servers it names
with a role of its own. The mailbox service closes its own database the
same way. Checked by the suites against PostgreSQL in the CI, its live
check: `live/mailbox-agents/postgres_state.py`
([state](../mailbox-agents/concept/state.md)).

### Next

| Step | Content |
|---|---|
| On a real mailbox | Each agent in `shadow` on its owner's account, measured against a gold set of labelled mail ([evaluation](../mailbox-agents/concept/evaluation.md)), then `suggest`, then `full`. Each change of stage is the owner's decision |
| Verified senders | A switch for a group of `categorization` that moves only mail whose sender the receiving server verified. The mailbox service names that result per message since 0.8.0, and the agents read it since 2026-11-27. The switch for `categorization` is open ([categorization](../mailbox-agents/concept/agent-categorization.md)) |
| Embeddings | Recognising a repeated inquiry by embeddings, stored in the state file |
| External agent server | Handing a message to an external agent server over HTTP, and reply drafts |
| Daily overview | A daily summary of what every agent did that reaches the owner, with no model involved. The pages to read it from are the cockpit, built 2026-11-27 |

Ideas not scheduled: newsletters to a folder by the `List-Unsubscribe`
header, a keyword for mail that names a deadline, a mark for mail from
authorities.

### Open questions

1. **How the daily overview reaches the owner.** A mail to the owner's own
   address, from a user that may send there and nowhere else, or a draft.
   Not decided, the overview is a later step.
2. **Keywords per provider.** To verify per account before an agent is
   switched to the stage `suggest` ([mailbox service](../mailbox-agents/concept/mailbox-service.md)).
   Measured for IMAP at Stalwart, on the test account: a keyword is set
   and taken off, a move to another folder keeps the message's id and is
   taken back by a move to the folder before, and a keyword set as
   `Awaiting-Reply` comes back as `awaiting-reply`, so the runtime and the
   agents compare keywords without case. Other providers are still to
   verify.
3. **Folder-narrowed grants and moves.** To verify
   ([mailbox service](../mailbox-agents/concept/mailbox-service.md)). It decides whether
   the grant of an instance of `categorization` can be narrowed to the
   inbox and the folders its list moves to.
4. **Automatic answers.** The agents read no header of a message, so
   `Auto-Submitted` is not read. `awaiting_reply` uses a heuristic on
   sender and subject (decided 2026-11-17) and the evaluation counts what
   it misses.
