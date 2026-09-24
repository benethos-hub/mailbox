# Ideas

Collected, not decided. An idea moves into [CONCEPT.md](CONCEPT.md) once it
is designed, and into [ROADMAP.md](ROADMAP.md) once it is scheduled. Until
then nothing in the code depends on it.

## Sender identities, aliases and signatures

Many people send from more than one address in the same mailbox: `info@`,
`rechnung@`, a personal alias. Sending needs an "as whom", and each
identity may have its own signature and reply-to.

- JMAP models this as `Identity`, Gmail as "send-as" addresses, Graph as
  shared or delegated mailboxes. IMAP has nothing: identities would be ours,
  stored per account.
- API sketch: `GET {acc}/identities`, and `identity_id` on send and drafts.
- Rights: may a user send as every identity of an account, or only as some?
  That could be a grant constraint like `recipients`.

## Safe display of HTML mail

- Never load remote content. A tracking pixel tells the sender that a mail
  was opened, and when, and from where.
- For the model: HTML converted to text, hidden content dropped (already
  required by CONCEPT 7.7).
- For the configuration UI or other clients: sanitized HTML, remote images
  replaced by placeholders, links shown with their real target.

## Attachments for the model

- Size limits per attachment and per tool call.
- Text extraction from PDF, Office documents and plain text, so the model
  can read an invoice without a download. A PDF library has to fit this
  project's MIT licence: PDFium bindings (BSD / Apache) yes, PyMuPDF (AGPL)
  no.
- Images: pass through for models that can see them, or skip.
- Never execute or open anything. Attachments are data.
- Attachment text is foreign content like the mail body (CONCEPT 7.7).

## Further

- **Outbox with scheduled sending** (`send_at`): sending is queued,
  delivered later, and reported by event.
- **A marker on mail sent through the API**, for example a header naming
  the user, so it can be traced later which mail a script or an assistant
  sent.
- **Local search index** across all accounts (SQLite FTS). See open
  question 5 in CONCEPT.md.
