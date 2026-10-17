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

## A project app for Google, as for Microsoft

With Microsoft every installation signs in through the project's app.
For Gmail each one needs a Google client of its own, or an app
password (docs/GOOGLE.md). A project app would spare that. It needs:

- **Google's verification and a yearly security assessment (CASA)**,
  since every Gmail scope that reads mail is restricted. Google charges
  nothing, the approved labs do: quotes range from about 500 to a few
  thousand dollars a year, and the review takes weeks. Further a privacy
  policy, a verified domain and a demo video. Without verification a
  client is limited to 100 users over its whole life, across every
  installation.
- **A way back for the browser.** Google offers no sign-in with a code
  for Gmail. A project app reaches `localhost` only. A server needs a
  redirect service run by the project, which passes the sign-in on to
  the installation named in the state, as Home Assistant does with
  my.home-assistant.io. PKCE keeps the code useless to that service.
- **A single point of failure.** If Google suspends the app, every
  installation loses Gmail at once.
- **An open question:** whether an installation on the operator's own
  server counts as "a server" under Google's assessment rule. To be
  asked of Google before anything is built.

Worth it once the project has users beyond the 100 a client of one's
own allows, and a budget for the assessment.

## Gmail pushes through Cloud Pub/Sub

Gmail tells of changes only through Cloud Pub/Sub: `users.watch` names a
topic, Gmail publishes to it, and the watch runs out after 7 days unless
renewed. Today the worker asks Gmail's history every
`MAILBOX_SERVICE_SYNC_INTERVAL` seconds instead (CONCEPT 5.5).

- Needs more of Google Cloud: a topic, a subscription, and the right of
  Gmail's service account to publish to it.
- A pull subscription works without a public address: the worker asks
  the subscription and wakes the account's sync. A push subscription
  needs an HTTPS endpoint the service would have to offer.
- Gives `PUSH` and with it `wait_for_change`.

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
- For the model this is built: HTML converted to text, hidden content
  dropped (CONCEPT 7.7).
- Left for the configuration UI or other clients: sanitized HTML, remote images
  replaced by placeholders, links shown with their real target.

## Attachments for the model

- Text extraction from PDF and Office documents, so the model can read
  an invoice without a download. Today `get_attachment` hands the pages
  of a PDF over as images, text types as text and images as images
  (CONCEPT 8), with limits on size, pages and characters.
- **Attachments in the summaries.** A listed message says only
  `has_attachments`. Naming its attachments, with name, type, size, id
  and whether inline, would show in search results what is attached
  without opening the mail, in the MCP server and in the UI. IMAP reads
  BODYSTRUCTURE while listing anyway, JMAP has the property on
  `Email/get`, Graph needs `$expand`, Gmail the full form of every
  message, and POP3 cannot, so a capability would say that the list
  carries nothing there (UNIFORM.md, rule R5). It changes the summary's
  contract and belongs in a version of its own.
- **Attachments as MCP resources.** A person picks an attachment in the
  client and attaches it to the message, with no download and no tool
  call. It needs the item above: the server lists the newest N messages
  with attachments across the token's accounts, fresh on every
  `resources/list`, without a copy of its own, bounded in messages and
  entries, and only with `get_attachment` in the grant. Reading goes
  through the REST API with the token's rights and a size limit of its
  own, since a resource reaches the model whole, where the tool renders
  pages. The name carries account and subject before the sender's
  filename, since no marker separates sender content from the person's.
  Measured on 2026-10-16: Claude Desktop lists resources once at start,
  does not re-list on `resources/list_changed`, and starts a stdio
  server twice, one process for the lists and one for the calls. In
  such a client the list is the state of the start, and a list filled
  from the session's tool calls would never be seen. Notifications are
  not worth building until a client re-lists.
- **An attachment on disk.** `save_attachment` writes an attachment
  unchanged into a directory of the configuration, for a person who
  needs the file, or a program on the same machine that takes paths
  only. The link of `share_attachment` covers service to service over
  the network.

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

## More for the UI sign-in

TOTP came on 2026-10-09 as a choice per user
([AUTHENTICATION.md](AUTHENTICATION.md)). Left for later:

- A switch for the operator that requires a second factor, for everyone
  or for users with `users.manage` (AUTHENTICATION.md 8).
- A passkey (WebAuthn), which needs no shared secret.

## Beyond the static API token

Collected 2026-10-09. Today the REST API takes a static bearer token
(CONCEPT 7.5): random, stored as a hash, revocable, with an optional
expiry. Whoever copies it from a settings file, a log or a proxy can use
it until it is revoked or expires. Three steps, each building on the one
before:

1. **A life cycle for the token.** A maximum lifetime as a setting.
   `POST /v1/tokens/{id}/rotate` makes a new token and keeps the old one
   valid for a short overlap, so a client changes without an outage. A
   response header warns of a near expiry, and `mailbox-client` and the
   MCP server log it. A checksum in the token lets a leak scanner tell a
   real token from noise. Nothing changes for a client, curl included.
2. **Short-lived tokens from the service itself**, OAuth 2.0 with
   `POST /v1/oauth/token`. A new credential kind of a user, an API
   client: it holds a public key, and the client proves itself with
   `private_key_jwt` (RFC 7523), so the service stores nothing a thief
   could use. The grants `client_credentials` and `refresh_token`. An
   access token lives about ten minutes. It stays opaque and hashed as
   today rather than a JWT, so a revocation takes effect at once. A
   refresh token changes with each use, and an old one used again
   revokes the whole chain. `mailbox-client` fetches and renews the
   tokens, and the MCP server gets this through it. The static token
   stays for scripts.
3. **Tokens bound to a key**, DPoP (RFC 9449). Each request carries a
   small signed proof, so a stolen access token is of no use without the
   private key. Most clients cannot do this, but `mailbox-client` is
   ours, so every client of the project would.

mTLS would bind a token to a certificate as well, but it depends on the
proxy and on keeping certificates. On the side of the client, a token in
the keyring of the operating system rather than in a `.env` file lowers
the risk of a leak without any change to the protocol.

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

## Parts of words in every search

CONCEPT.md open question 5 asks the same. The search runs on the
provider's server, so how text matches differs
per provider: IMAP finds parts of words, Microsoft beginnings of words,
Gmail whole words only (docs/UNIFORM.md, decision 6.7). A search for
`rechnung` finds "Stromrechnung" on IMAP alone, and "Rechnungsnummer"
on IMAP and Microsoft. Finding parts of words on every account needs
the service to search itself.

- **An index of the headers.** The message index also keeps subject,
  sender and recipients. `sender`, `to` and `subject` then find parts of
  words on every account, while `text` stays the provider's. For the
  first time the service would keep content of the mail, if only
  headers: the backup, the deletion of an account and the sync carry
  it along.
- **An index of the whole text.** The same for the body. Far more
  storage and time to sync, and the mail's content at rest in the
  service.

## Further

- **Outbox with scheduled sending** (`send_at`): sending is queued,
  delivered later, and reported by event.
- **A marker on mail sent through the API**, for example a header naming
  the user, so it can be traced later which mail a script or an assistant
  sent.
- **Live Public Suffix List** in addition to the bundled one (CONCEPT 5.8),
  for example a file the operator keeps current.
