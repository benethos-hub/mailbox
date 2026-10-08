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

## One thread for every IDLE connection

Today each watched account holds a thread while it waits in IDLE, at
most `MAILBOX_SERVICE_SYNC_WATCHERS` of them. One thread could hold all
IDLE sockets in a `selectors` object and wake the account's sync task
when its socket becomes readable. Worth it once accounts go into the
hundreds, or when the IMAP session is rebuilt anyway.

- The one thread must never wait on a server: login, `SELECT`, the
  renewal every 25 minutes and the logout stay in the pool, short and
  per account, with socket timeouts. The thread only waits.
- TLS buffers data the file handle does not show: check `pending()`
  as imapclient's `idle_check` does, or changes go unseen until the
  next record.
- `wait_for_change` keeps its signature: the adapter registers with
  the watcher and waits for an event. The worker does not change.
- Tests need a real handle: socket pairs, or an injectable wait.
- `selectors` on Windows falls back to `select`, 512 handles.

## Safe display of HTML mail

- Never load remote content. A tracking pixel tells the sender that a mail
  was opened, and when, and from where.
- For the model: HTML converted to text, hidden content dropped (already
  required by CONCEPT 7.7).
- For the configuration UI or other clients: sanitized HTML, remote images
  replaced by placeholders, links shown with their real target.

## Attachments for the model

- Text extraction from PDF and Office documents, so the model can read
  an invoice without a download. Today `get_attachment` hands the pages
  of a PDF over as images, text types as text and images as images
  (CONCEPT 8), with limits on size, pages and characters.

## The standard library's mail parser instead of imap-tools

Since the switch to IMAPClient (CONCEPT 5.1), imap-tools is left only for
its mail parser in `data/mail/parse.py`. The standard library's `email` module
could take that over and drop the dependency. It would have to handle the
encoding traps of CONCEPT 5.10 as well, which the fixtures check.

## A policy file for the MCP server

A file beside the MCP server that names the tools it offers, nothing
enabled by default. It would matter only where a user may do more than
its MCP server should offer, e.g. may send but the model should only
draft. An option of the MCP server, such as leaving out the send tools,
would do the same with less.

## A second factor for the UI sign-in

Postponed on 2026-09-27, after the password sign-in (CONCEPT 7.5).

- TOTP (RFC 6238) as a credential kind beside the password: set up with a
  QR code, confirmed with a first code, with recovery codes shown once.
- Or a passkey (WebAuthn), which needs no shared secret.
- Open: required for users with `users.manage`, or a choice per user.

## The master key from systemd

Left open on 2026-10-06, with the key file (CONCEPT 7.3). A service run
by systemd could read its key from `$CREDENTIALS_DIRECTORY`, which
`LoadCredential=` fills. systemd keeps the file apart and readable by the
service alone, and the operator names no path of its own.

## One MCP server for many users

Collected 2026-10-06. Today the MCP server acts as one user, with the
token it starts with, and each client runs an instance of its own. The
operator leans towards that. A shared MCP server could instead pass the
token of each caller through: a client sends its own Mailbox API token
as bearer token, the MCP server uses it for its REST calls and holds no
token itself. The service still decides what each may do. It would need
a REST client and a tool list per session, made from `/v1/me` of that
token, instead of once at the start. The OAuth of the MCP specification
could follow. `containers/production/` would then run it for everyone.

## A framework for the assembly

Collected 2026-10-07, when `main.py` became `assembly/`. The services are
wired by hand in `assembly/domain.py`, and that is enough while each
lives as long as the service. A container of services such as `svcs`
would pay off once one of these comes: services that live for one
request, plugins found through entry points, or wiring chosen by the
settings rather than in code.

## Further

- **Outbox with scheduled sending** (`send_at`): sending is queued,
  delivered later, and reported by event.
- **A marker on mail sent through the API**, for example a header naming
  the user, so it can be traced later which mail a script or an assistant
  sent.
- **Local search index** across all accounts (SQLite FTS). See open
  question 5 in CONCEPT.md.
- **Live Public Suffix List** in addition to the bundled one (CONCEPT 5.8),
  for example a file the operator keeps current.
