# Concept: safety

Part of the [concept](../CONCEPT.md).

Three locks, in three places, none of which the model can reach:

| Where | What it stops |
|---|---|
| The mailbox service | sending, deleting for good, drafts: the agent's user has no right to them |
| The model gateway | a model outside the agent's list, spending past its budget |
| The runtime | every action the agent did not declare, the trash among them, a folder made or a keyword set that its configuration does not name |

The runtime does not check the target of a move against the agent's
configuration: only the agent's code computes it, never a model
(decided 2026-11-18). A move into the trash, junk or spam, or below
them, is refused all the same.

Further rules:

- **Mail content is data.** The request names it as the content of a mail
  and never as an instruction, and the step that reads it has no tools.
- **The sender is not proof.** From is not authenticated. A move that
  rests on the sender needs a rule naming the address or its pattern. A
  domain rule and the model's choice mark only (decided 2026-11-17).
  The agent `invoices` was the first exception, from 2026-11-18 until it
  was removed on 2026-11-25. `categorization` from version 2 is
  the exception (2026-11-24): it moves a message into the folder
  of the group its model chose by the group's topic, or since 2026-11-25
  by a recognizer such as `invoice`, but only where the
  owner set `"by_topic": "act"` for that group, and only with a quote
  found in the mail, not in the topics. The model chooses among the
  groups of the list it is given and names no folder. A held group stays
  held. So a message that only names a project can land in the project's
  folder ([categorization](agent-categorization.md)).
- **A value needs evidence.** A label and every extracted field carry a
  quote. The code looks for the quote in the parts of the mail the model
  was given, each on its own: sender, subject, attachment names, text.
  The frame the code writes around them, `From:`, `To:`, `Subject:` and
  `Attachments:`, is no part, and a quote that starts with one is looked
  up without it. A test holds the frame words each agent writes to the words the check strips. Both sides are
  brought to Unicode NFC and compared word for word: case, punctuation,
  typographic quotes and dashes, and the whitespace between words do not
  count, the words and their order do. A changed or missing word is not
  forgiven, nor a first or last word cut short: a quote matches whole
  words only (confirmed 2026-11-19). A quote of fewer than eight letters
  and digits counts as not
  found (decided 2026-11-17, case and punctuation forgiven 2026-11-18).
  A value code found by a rule, such as the group of a sender rule of
  `categorization`, carries no quote, so nothing of the mail is stored for it. A
  field whose quote is not found is dropped, and a label whose quote is
  not found is recorded and not acted on. A confidence the model reports
  about itself is not used.
- **Reversible only.** Every action records what was there before.
- **Secrets never travel.** The service token and the gateway key are never
  logged, never stored in the state file and redacted from error text.
- **Nothing of a mail in a log line.** A line names ids, states, counts and
  durations.
