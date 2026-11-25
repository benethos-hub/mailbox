# Roadmap: the agents

Part of the [roadmap](../ROADMAP.md): the agents, `mailbox-agents`,
alpha. Their concept is [docs/mailbox-agents/CONCEPT.md](../mailbox-agents/CONCEPT.md).

## The agents

### Built

Version 0.11.0 holds the runtime and the agents `counting`,
`invoices`, `awaiting_reply`, `inquiries` and `sorting`, each described in
its file under [concept/](../mailbox-agents/concept/). All of it ran on the test account of
invented mail. On a real mailbox, read-only and in `shadow`: `invoices`
version 3 on 2026-11-18, `sorting` and `invoices` on 2026-11-22, and
`invoices`, `inquiries` and `awaiting_reply` in the versions of 0.11.0
on 2026-11-23. None changed anything.

Since 2026-11-24 `sorting` version 2 also assigns a message by the topic
of a group, a line of the owner that a model is given, where no sender
rule settles it. Its choice is recorded only, unless the group acts on
it ([sorting](../mailbox-agents/concept/agent-sorting.md)).

Since 2026-11-25 `sorting` version 3 runs a chain: a list of dimensions
run one after another, each category found by its sender, its topic or
a recognizer of a register, and what follows from it named beside it, a
keyword, a move, a folder below, by priority and with a stage per entry
([the chain of sorting](../mailbox-agents/concept/sorting-chain.md)).

### Next

| Step | Content |
|---|---|
| On a real mailbox | Each agent in `shadow` on its owner's account, measured against a gold set of labelled mail ([evaluation](../mailbox-agents/concept/evaluation.md)), then `keyword`, then `full`. Each change of stage is the owner's decision |
| Verified senders | A switch for a group of `sorting` that moves only mail whose sender the receiving server verified. The mailbox service names that result per message since 0.8.0, and the agents do not read it yet ([sorting](../mailbox-agents/concept/agent-sorting.md)) |
| Embeddings | Recognising a repeated inquiry by embeddings, stored in the state file |
| External agent server | Handing a message to an external agent server over HTTP, and reply drafts |
| Daily overview | A daily overview of what every agent did, read from the state files by a process of its own, with no model involved |

Ideas not scheduled: newsletters to a folder by the `List-Unsubscribe`
header, a keyword for mail that names a deadline, a mark for mail from
authorities.

### Open questions

1. **How the daily overview reaches the owner.** A mail to the owner's own
   address, from a user that may send there and nowhere else, or a draft.
   Not decided, the overview is a later step.
2. **Keywords per provider.** To verify per account before an agent is
   switched to the stage `keyword` ([mailbox service](../mailbox-agents/concept/mailbox-service.md)).
   Measured for IMAP at Stalwart, on the test account: a keyword is set
   and taken off, a move to another folder keeps the message's id and is
   taken back by a move to the folder before, and a keyword set as
   `Awaiting-Reply` comes back as `awaiting-reply`, so the runtime and the
   agents compare keywords without case. Other providers are still to
   verify.
3. **Folder-narrowed grants and moves.** To verify
   ([mailbox service](../mailbox-agents/concept/mailbox-service.md)). It decides whether
   the grant of `invoices` can be narrowed to the inbox and the folders
   `INVOICES_FOLDERS` names, with the subfolders below them
   ([invoices](../mailbox-agents/concept/agent-invoices.md)).
4. **Automatic answers.** The agents read no header of a message, so
   `Auto-Submitted` is not read. `awaiting_reply` uses a heuristic on
   sender and subject (decided 2026-11-17) and the evaluation counts what
   it misses.
