# Concept: safety

Part of the [concept](../CONCEPT.md).

Three locks, in three places, none of which the model can reach:

| Where | What it stops |
|---|---|
| The mailbox service | sending, deleting for good, drafts: the agent's user has no right to them |
| The model gateway | a model outside the agent's list, spending past its budget |
| The runtime | every action the agent did not declare, the trash among them, and a folder made that its configuration does not name |

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
  `invoices` from version 4 is the one exception (decided 2026-11-18): it
  moves a message its model takes for an invoice. The model answers only
  whether it is one, and the folder follows from where the message lies
  and the settings: the subfolder of a folder the agent looks in, and out
  of the inbox only the inbox folder, and only when the owner set one.
  Unset, an invoice in the inbox is marked and stays. So in `full` a
  forged invoice that lies in such a folder is filed beside the real
  ones. The folder it lies in was chosen by a rule or by hand, never by
  the model ([invoices](agent-invoices.md)).
- **A value needs evidence.** A label and every extracted field carry a
  quote. The code looks for the quote in the parts of the mail the model
  was given, each on its own: sender, subject, attachment names, text.
  The frame the code writes around them, `From:`, `To:`, `Subject:` and
  `Attachments:`, is no part, and a quote that starts with one is looked
  up without it. A test holds the words each agent writes to that list. Both sides are
  brought to Unicode NFC and compared word for word: case, punctuation,
  typographic quotes and dashes, and the whitespace between words do not
  count, the words and their order do. A changed or missing word is not
  forgiven, nor a first or last word cut short: a quote matches whole
  words only (confirmed 2026-11-19). A quote of fewer than eight letters
  and digits counts as not
  found (decided 2026-11-17, case and punctuation forgiven 2026-11-18: of
  13 quotes the shadow run on the owner's account refused, none was
  invented, and every one differed in such marks or in a few characters).
  A value code found by a rule, such as the group of a sender rule of
  `sorting`, carries no quote, so nothing of the mail is stored for it. A
  field whose quote is not found is dropped, and a label whose quote is
  not found is recorded and not acted on. A confidence the model reports
  about itself is not used.
- **Reversible only.** Every action records what was there before.
- **Secrets never travel.** The service token and the gateway key are never
  logged, never stored in the state file and redacted from error text.
- **Nothing of a mail in a log line.** A line names ids, states, counts and
  durations.
