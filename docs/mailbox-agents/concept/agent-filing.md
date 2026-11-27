# Concept: the agent `filing`

Part of the [concept](../CONCEPT.md).

An actor ([agent contract](agent-contract.md)): it files mail into
folders by its keywords, by a list its owner wrote. It asks no model and
reads nothing of what a mail says. It sees a message as `Placed`: where
it lies, the keywords it carries. The keywords come from another agent,
such as the instances of [categorization](categorization-chain.md), or
from a person in a mail client. Built on 2026-11-27.

## Its question

Which folder does the list name for the keywords this message carries?

## The list

`MAILBOX_AGENTS_FILING_FILE` names a JSON file, as
`config/benethos-mailbox-agents/filing.example.json` shows:

```json
{
  "on": {"keywords": ["agent-partner-*", "agent-invoice"]},
  "rules": [
    {"keywords": ["agent-partner-cloudhost"], "move": "Providers/CloudHost"},
    {"keywords": ["agent-partner-telco"], "move": "Providers/Telco"},
    {"keywords": ["agent-invoice"], "below": "Invoices"}
  ]
}
```

| Field | What it holds | Form |
|---|---|---|
| `on.keywords` | the keywords the list waits for, a `*` at the end for every keyword it starts. Without `on`, every keyword of its rules | lower case letters, digits and dashes, 1 to 50 |
| `rules` | the rules in order | 1 to 200 |
| `keywords` of a rule | the keywords a message carries, all of them, for the rule to fit | lower case letters, digits and dashes, 1 to 10 |
| `move` | a folder from the top | names between `/`, none empty, `.` or `..` |
| `below` | a folder below the one the message goes to or lies in | the same |

A rule names `move` or `below`, one of them. Two folders that differ in
case only are refused. A list that waits for the agent's own keyword is
refused, as it would set itself off. A message about a refused list names
the place of a rule, never a keyword or a folder: both are the owner's
own text.

## Where a message goes

- **From the inbox:** to the `move` of the first rule with a move that
  fits, and below it to the `below` of the first rule with a below that
  fits, unless the move ends in it already. A message with a below alone
  stays in the inbox.
- **From a folder of the owner,** one without a role: only below that
  folder, by the first rule with a below. A `move` does not take mail out
  of a folder the owner or a rule of the mail server put it in. A message
  that lies where its rules from the inbox lead already, such as one whose
  move went through while its keyword did not, gets the keyword.
- **Anywhere else** it stays.

With the example, a message in the inbox that carries
`agent-partner-cloudhost` and `agent-invoice` goes to
`Providers/CloudHost/Invoices`, the folders made from the top where they
are missing. One in `Projects/Alpha` that carries `agent-invoice` goes to
`Projects/Alpha/Invoices`.

A decision is labelled `rule-<n>` by the place of the rule that leads,
the move's, else the below's, or `none`. Its details name the places of
the move and the below, never a folder.

## By stage

| Stage | Folder creation | Move | Its keyword |
|---|---|---|---|
| `shadow` | recorded | recorded | recorded |
| `suggest` | recorded | recorded | recorded. It goes with the move, so the stage acts like `shadow` |
| `full` | made | made | set |

## The owner's will

- **Once per message.** After the move it sets its keyword,
  `agent-filed`, and a message that carries it is not taken up again. A
  message it moved once is not moved again by it, also when a person put
  it back and changed its keywords ([agent contract](agent-contract.md)).
- **Never in the trash, junk, spam, drafts or sent mail.** A message
  there is `skipped`.
- **Waiting for a keyword.** A new message without a keyword the list
  waits for ends `skipped`. An update that shows it with one takes it up
  again, and `backfill` takes up the mail that carries one, in the inbox,
  in sent mail and, when a rule has a below, in the folders of the owner.

## Rights

A user of its own in the mailbox service with `mail.read` and
`mail.write` on the accounts it works on, nothing else
([mailbox service](mailbox-service.md)). It needs no gateway and no key.

## Beside `categorization`

The instance `filing` of `categorization` in
`containers/live/mailbox-agents/chain/` does the same work with the
actions `move` and `move_below` of its list. Both stay: `categorization`
keeps its moves until this agent has proven itself in `shadow` and Gmail
is reached through labels (decided 2026-11-27).
