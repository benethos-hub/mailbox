# Concept: the agent `forwarding`

Part of the [concept](../CONCEPT.md).

An actor ([agent contract](agent-contract.md)): it drafts a forward of
mail with certain keywords, by a list its owner wrote. It sends nothing:
the forward lies in the drafts folder of the account until the owner
sends or deletes it. It asks no model and reads nothing of what a mail
says. It sees a message as `Placed`: where it lies, the keywords it
carries, its sender check, and whether it came from an address of a rule.
Built on 2026-11-27.

## Its question

Which rule of its list fits the keywords of this message, and may its
forward be drafted?

## The list

`MAILBOX_AGENTS_FORWARDING_FILE` names a JSON file, as
`config/benethos-mailbox-agents/forwarding.example.json` shows:

```json
{
  "on": {"keywords": ["agent-invoice"]},
  "rules": [
    {"keywords": ["agent-invoice"], "to": ["books@example.org"],
     "forward_as": "attachment", "sender_check": "required"}
  ]
}
```

| Field | What it holds | Form |
|---|---|---|
| `on.keywords` | the keywords the list waits for, a `*` at the end for every keyword it starts. Without `on`, every keyword of its rules | lower case letters, digits and dashes, 1 to 50 |
| `rules` | the rules in order, the first that fits holds | 1 to 50 |
| `keywords` of a rule | the keywords a message carries, all of them | lower case letters, digits and dashes, 1 to 10 |
| `to` | the addresses of the forward | 1 to 5, each one `@` between two parts, no white space, at most 254 characters, compared in lower case, one named twice kept once |
| `forward_as` | `inline`, the message quoted with its attachments, or `attachment`, the message as a file | `inline` when left out |
| `sender_check` | `required`: a draft only when the sender check of the message passed, `off`: also when it is `unknown` | `required` when left out |

The addresses stand in this list alone: no second list in the settings
names them, and the runtime drafts to no address but those of the list
(`recipients()`). A message about a refused list names the place of a
rule, never an address or a keyword: both are the owner's own text.

## What it does

The first rule whose keywords the message carries all gives the
addresses and the form. The forward carries no text of its own, the
mailbox service sets its subject.

- **The sender check (decided 2026-11-27).** A message whose check is
  `fail` is never forwarded: the draft is recorded only. One whose check
  is `unknown` is recorded only, unless the rule says `"sender_check":
  "off"`. One that passed is drafted.
- **Never back to its sender.** A message that came from an address of
  the rule gets no draft: it would go round in a loop.
- **Never the owner's own mail,** nor mail in the trash, junk or spam: a
  message in the drafts or sent mail, or one the owner discarded, is
  `skipped`.

A decision is labelled `rule-<n>` by the place of the rule, or `none`.
Its details say why with a code, `forward`, `sender-check` or
`from-recipient`, never an address.

## By stage

| Stage | The forward |
|---|---|
| `shadow` | recorded |
| `suggest` | drafted |
| `full` | drafted. Sending is not built: `full` does what `suggest` does (decided 2026-11-27) |

No agent sends, in any stage.

## Its limits

- **Once per message.** The state file holds that a forward was drafted,
  and it is not drafted again, whatever update comes. The agent sets no
  keyword: its own, `agent-forwarded`, is declared and never set. A
  state file made anew knows none of the forwards before, so a `backfill`
  then drafts a second one for mail that still carries its keyword.
- **At most 20 a day.** Beyond them the action is refused and logged, and
  the message ends. Only the forwards drafted count, and a forward only
  recorded, in a stage below `suggest` or held by its sender check, is
  recorded past them as well.
- **A forward drafted whose answer did not come** is looked up among the
  drafts: when it is there, it counts as drafted.

## Rights

A user of its own in the mailbox service with `mail.read` and `drafts`
on the accounts it works on: not `mail.write`, which it does not need as
it sets no keyword, and not send
([mailbox service](mailbox-service.md)). It needs no gateway and no key.

## An account without drafts

An account without a drafts folder, and one of a provider without drafts,
answers `501 not_supported`. The action is refused and logged, the
message ends, and the pass goes on.
