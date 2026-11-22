# Concept: the agent `awaiting_reply`

Part of the [concept](../CONCEPT.md).

**Question:** does this sent message expect an answer, and has one come?

| | |
|---|---|
| Triggers | `message.sent`, `message.created`, `message.updated`, the tick |
| Baseline | a question mark or a request phrase in the last paragraph written |
| Model | whether the message expects a reply, yes or no |
| Actions | `add_keyword`, `remove_keyword`, both on the sent message |
| Deadline | `MAILBOX_AGENTS_REPLY_DAYS` working days, Monday to Friday, 3 by default (decided 2026-11-17, public holidays kept as a later option) |

A sent message that expects a reply becomes an open item. It closes when:

- a later message from another sender appears in its thread, automatic
  answers not counted. The service exposes no header, so an automatic
  answer is told by a sender such as `noreply` or `mailer-daemon` and a
  subject such as `automatische antwort` or `out of office`, matched
  without case (decided 2026-11-17),
- a person takes the keyword off, which the agent learns from the feed where
  the provider reports flag changes (`message.updated`, routed to
  `observe`). Its own keyword set or taken off closes nothing,
- the sender writes again in the same thread. That restarts the deadline and
  does not count as a reply: when the new message expects a reply itself,
  the earlier item closes as `followed_up` and the new one opens, otherwise
  the earlier item starts again from the new message,
- the sent message is not there any more when the tick would set its
  keyword: the item closes as `message_gone`, so the tick does not ask
  for the keyword every round. So does an item whose sent message a later
  message of its thread no longer finds, and the later message goes on
  (2026-11-20),
- the sent message is moved to the trash, junk or spam: the item closes as
  `discarded`, as no keyword is set there (decided 2026-11-20).

A sent message whose thread already holds a later answer from someone
else opens no item. So a reply taken up before the message it answers,
by a backfill or a backoff, is not missed.
Taking a message up again, as `backfill` does, opens no item it
had before: an item a reply or a person closed stays closed.

An item past its deadline gets the keyword on the tick. The message stays
where it is. The item counts the keyword as set only once it is on the
message, so in `shadow` a star or another flag closes nothing. A stage
that does not allow the keyword records it once, and a later stage that
does sets it. A keyword the service refused is offered again on the next
tick. The deadline counts from the date of the sent message, and a
date on a weekend counts from the Monday after.

An item closed as `replied` or `followed_up` takes the keyword off with
the step that closes it. When that write fails, the step run again finds
no open item. So the tick also takes the keyword off every such item that
still counts it as set, and the item counts it as gone once the keyword
is off the message (2026-11-20). An item closed as `keyword_removed` or
`message_gone` is never asked about.

The model is given the recipients, the subject and the text the sender
wrote, without what it quotes, the last 4000 characters of it. The
subject is cut at 300 characters, as a reply keeps the one a stranger
chose (2026-11-19). The prompt is
`prompts/system.v1.md`, version `v1`. A received message asks no model:
what it closes is a rule. The agent works on messages in sent mail, and on
messages in the inbox that belong to a thread.

Known misses, to be counted in the evaluation rather than argued away: an
answer that comes as a new mail outside the thread, an answer by telephone,
and several recipients of whom one answers.
