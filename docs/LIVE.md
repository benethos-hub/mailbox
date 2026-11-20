# Live checks

The manual checks in `live/`: what each one reads, sends, changes and
deletes. They are scripts, outside `testpaths`, and no test of the
suite reaches a mail server.

They run against **test accounts**: on an IMAP server of our own, the
Microsoft test account, the Gmail test account, and the test mail
server in a container. The server's address and the list of test
accounts are in `live/.env` (not versioned, template
`live/.env.example`). Only the accounts listed there count as confirmed
test accounts for golden rule 1 of [CLAUDE.md](../CLAUDE.md).

| Check | Against | Writes |
|---|---|---|
| [`smoke.py`](#smokepy) | the test accounts | nothing |
| [`changes.py`](#changespy) | the two test accounts | mail, a folder, all deleted for good |
| [`register.py`](#registerpy) | a running service | the test accounts in that service |
| [`mcp_stdio.py`](#mcp_stdiopy) | the test accounts, a service of its own | mail, a folder, drafts, all put back or deleted |
| [`mcp_http.py`](#mcp_httppy) | the test accounts, a service of its own | nothing |
| [`ui.py`](#uipy) | the test accounts, a service of its own | mail, a folder, drafts, all removed |
| [`microsoft.py`](#microsoftpy) | the Microsoft test account | mail to the first test account, deleted for good |
| [`gmail.py`](#gmailpy) | the Gmail test account | mail to and from the first test account, deleted for good |
| [`pop3.py`](#pop3py) | the test mail server in a container | one mail, deleted for good |
| [`jmap.py`](#jmappy) | the test mail server in a container | one mail and a draft, deleted for good |
| [`imap.py`](#imappy) | the test mail server in a container | one mail, a folder and a draft, deleted for good |

The checks that start a service as a process make its first user with
`users create-admin`, change the one-time password in the UI and make a
token there, as an operator would. `smoke.py`, `changes.py` and
`pop3.py` run the service in their own process, in memory, and store
nothing.

## `smoke.py`

`uv run python live/smoke.py [--show] [--wrong-password]`

Read-only, the folder `all` among it, and the `sender_check` of the
newest message, without `--show` its result and reason only. It also
lists across all accounts and syncs each account once.

- `--show` prints the messages of the first page: sender, recipients,
  subject, attachment names and the start of the text.
- `--wrong-password` also tries one login with a wrong password, which
  the server may count against the account.

## `changes.py`

`uv run python live/changes.py [--keep]`

Sends one test mail from the second test account to the first, flags
and moves it, replies, forwards and sends a draft back to the second,
checks that the mail and the reply are one thread in each account,
makes and removes a folder, deletes it all for good, and checks the
change feed and a webhook on a receiver at 127.0.0.1.

With `--keep` the mail stays in the inbox and the copy in the sent
folder, to look at in a mail client. Delete them by hand.

## `register.py`

`MAILBOX_SERVICE_TOKEN=... uv run python live/register.py [--url URL] [--count N]`

`uv run python live/register.py --own-service [--count N]`

Adds the first two test accounts, or the first `N`, to a running
service over its API and checks them. An account the service has
already is only checked. Nothing in the mailboxes is written. With
`--own-service` it starts a service and database of its own and needs
no token.

## `mcp_stdio.py`

`uv run python live/mcp_stdio.py`

Checks the MCP server over stdio against the test accounts, with a
service and database of its own.

- The read tools read the conversation of a search hit as well.
- A user whose grant names the inbox alone sees that folder alone and
  finds nothing in the archive.
- A user that may share gets a link to a PDF attachment, which a GET
  without a token fetches once, the bytes `get_attachment` answers, and
  a second GET answers `404`.
- `server_status` must name the service of its own version, both ways.
- A user loses `mail.share` and gets it back while its server runs,
  which must tell its client each time and list the tools left, then
  the user is disabled and `server_status` alone is left.
- The write tools create a folder and star, move and trash a message of
  the first test account, then put everything back. They also rename
  the folder and add and take off a keyword. A label is refused there.
- The draft tools write a reply draft there without the quote, with a
  file, replace it with the file of the stored draft and delete it.
- The send tools send three mails from the first test account to the
  second, one of them twice with the same call, one from a draft and
  one as HTML, and delete them for good.
- Grants with recipients and a send limit stop mails. One more mail
  passes the limit and goes to the second test account, deleted for
  good as well. The audit names each attempt.
- `whats_new` must name the changes of the write tools.

## `mcp_http.py`

`uv run python live/mcp_http.py`

Checks the MCP server over streamable HTTP behind its bearer token,
read-only, with a service and database of its own.

## `ui.py`

`uv run python live/ui.py`

Checks the configuration UI against the test accounts.

- It connects the second test account through the UI, reads the inbox
  by conversations, and writes a folder, a draft and a reply draft on
  the first and removes them. It sends one mail from the first to the
  second, which it stars, marks read and gives a keyword there, then
  deletes for good on both sides.
- It also makes a user, a role and a token and uses the token on the
  API, reads the state of the service on the overview and the Accounts
  list, adds and removes a webhook, shows the recovery key of its own
  service, reads its log, makes a user with a one-time password and
  reads the audit of administration.
- A user of its own adds two devices of the second factor's first
  method, TOTP, from the keys of their QR codes, renames one, signs in
  with a code of each and a recovery code, and has them removed by
  itself, the admin and the host.

## `microsoft.py` and `gmail.py`: what they keep

Both run a service of their own at `http://localhost:8080`, which the
redirect address of the sign-in needs, so no other service may use that
port. Its database stays between runs, in `data/live-microsoft/`,
`data/live-microsoft-project/` with `--project`, and `data/live-gmail/`.
It holds the encrypted refresh token, and beside it the master key and
the password and a token of its user `admin`.

## `microsoft.py`

`uv run python live/microsoft.py --connect` once (a person signs in in
the browser), then `uv run python live/microsoft.py` checks the adapter
against the Microsoft test account in `live/.env` with an app of your
own, named there as well. With `--project` both use the project's app:
`--connect` prints a code a person enters at Microsoft. How an app is
set up: [MICROSOFT.md](MICROSOFT.md).

- It makes and removes a folder and a reply draft there, sends one mail
  with a file from it to the first test account and deletes it for good
  on both sides.
- The send names the sent copy, whose text and file are as sent, and
  the mail arrives under the Message-ID the send answered.
- A reply to the copy goes to the first test account too and names what
  it answers. The copy then carries `$answered`, which the check takes
  off, and it puts `$forwarded` on.
- It gives the sent copy a keyword and takes it off, reads its
  conversation, and checks that the change feed learns of the sent copy
  through Graph delta queries.
- With `--large` it reads, then sends one mail of about 7 MB alone, its
  files one by one, a large one through an upload session, which must
  arrive whole.
- With `--marks` it reads, then puts `$answered` and `$forwarded` on the
  newest mail of the inbox and takes them off, and sends nothing.
- Where a mail of the inbox has inline images, they must be listed and
  download.
- A report of non-delivery of an earlier run in the inbox of the
  Microsoft test account is deleted for good, and so is every mail of
  this check left in either account.

## `gmail.py`

`uv run python live/gmail.py --connect` once (a person signs in in the
browser), then `uv run python live/gmail.py` checks the adapter against
the Gmail test account in `live/.env` with the Google client of your
own. How the client is set up: [GOOGLE.md](GOOGLE.md).

- It makes a label inside a label, renames the outer one and removes
  both, writes, replaces and deletes a draft, sends one mail from the
  Gmail test account to the first test account, deleted for good there,
  stars, labels, unlabels and labels again, reads the thread of and
  archives the copy in Sent, deletes it for good, and checks that the
  change feed learns of it through Gmail's history.
- Then the first test account sends one mail to it, which must arrive
  in the inbox, be found, open and turn read.
- A reply draft to it and a reply sent back must be in its thread.
- All is deleted for good on both sides.

## `pop3.py`

`uv run python live/pop3.py`

Checks the POP3 adapter against the test mail server in a container:
one mail from the first account to the second, read, found by the sync
and deleted for good. The server is made by
`sh containers/test-mail-server/setup.sh`
([its README](../containers/test-mail-server/README.md)).

## `jmap.py`

`uv run python live/jmap.py`

Checks the JMAP adapter against the same server, with a service of its
own as a process: one mail from the first account to the second,
reported by push, found in the folder `all`, its thread read, changed,
put in a folder and back, a draft, left out of `all` in the trash, then
deleted for good on both sides.

## `imap.py`

`uv run python live/imap.py`

Checks the IMAP adapter, with SMTP for sending, against the same server,
with a service of its own as a process: one mail from the first account
to the second and to an address the server does not know, which the send
names as refused, reported through IDLE, found in the folder `all`, its
thread read, changed, moved into a new folder that is renamed with the
mail in it, moved back, a draft replaced under its id, left out of `all`
in the trash, then deleted for good on both sides. The folder is deleted
as well.
