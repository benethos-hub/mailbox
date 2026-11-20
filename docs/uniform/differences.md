# Uniform: what still differs per provider

Part of [UNIFORM.md](../UNIFORM.md): sections 4 and 7.

## 4. What still differs per provider

Before 0.5.0 the API behaved differently per provider in many places.
Version 0.5.0 ended that for everything a capability can announce. What
follows still differs today. Either a capability or a mark of the
account says so in advance, or the point is named here as left the way
it is.

### 4.1 Keywords and marks

- **Microsoft keeps `$answered` and `$forwarded`** as the verb Outlook
  last carried out, and has no place for another `$` keyword: it answers
  `501`, though the account has `keywords`. IMAP and JMAP keep it.
- **Gmail has no keywords.** The account lacks `keywords`.
- **The account's `marks`** say which marks it reads and which it
  writes (section 3).
- **Keywords keep the provider's spelling**, the marks that of RFC 8621.
  The pattern takes any keyword on one line. IMAP and JMAP answer `400`
  for one that is no atom. Microsoft takes a category with spaces.
- **Server notes are no keywords**: `$hasattachment`,
  `$hasnoattachment`, `$mdnsent`, `$submitpending` and `$submitted`
  (decision 6.2).
- **One vocabulary for display.** `mail/marks.py` of `mailbox-common`
  holds the marks with their words. The UI picks their icons in
  `web/pages/templates.py`.

### 4.2 Listing without a folder, and across accounts

- **A list without `folder` is the inbox** on every account. The role
  `all` is everything but the trash and junk: Gmail's All Mail, a
  server's own folder of that role, and otherwise an emulation by
  Microsoft, IMAP and JMAP. POP3 answers `501`.
- **A role the account has no folder for answers `501`**, announced by
  no capability. Gmail has no `archive`. Across accounts such an account
  is named in `incomplete` with `not_supported`.

### 4.3 Dates and order

- **`date` is the Date header everywhere**, and `received` the time the
  filters compare and lists sort by.
- **IMAP lists newest first by UID**, which is arrival order. The others
  sort by received time. Across accounts each account's place counts
  what it gave, and of the accounts' next messages the newest comes
  first. None is skipped or given twice, though a page may hold a
  message older than one of the next page.
- **Days count in UTC** on Gmail, Microsoft and JMAP, and in the
  server's day on IMAP. Left so: a day is the provider's unit.

### 4.4 Search and attachments

- **How text matches is the provider's** (decision 6.7). IMAP matches
  parts of words ("ail" finds "mail"), as IMAP `SEARCH` compares. Gmail
  and Microsoft match whole words or prefixes, JMAP as its server does.
- **On Microsoft, `q`, `from`, `to` or `subject` switch the list to
  Graph's `$search`.** `unread`, `starred` and `has_attachments=false`
  are then checked after each page, so a page can come back short or
  empty with a `next_cursor`.
- **A cursor is bound to the folder and the search.** Another list's
  cursor answers `400 bad_request`.
- **A list counts attachments as `get_message` does**, from IMAP's
  BODYSTRUCTURE, Gmail's parts and JMAP's attachments. Microsoft's
  `hasAttachments` leaves inline parts out. A POP3 list guesses from
  the headers (decision 6.10, decided 2026-10-15).

### 4.5 Sending

- **A reply or forward marks the original where the account writes the
  mark.** Gmail and POP3 write none. The send says so in
  `original_marked`.
- **Microsoft sends a mail as a draft**, whose immutable id the sent
  copy keeps. Above 2.5 MiB the mail is stored without its files, which
  follow one by one: a file below 3,000,000 bytes in one request, a
  larger one through an upload session.
- **An account that keeps no sent copy lacks `sent_copy`**: POP3, and
  JMAP without a sent folder. One that cannot send lacks `send`.
- **`refused` says whether a send names the recipients it refuses**, as
  SMTP does. Gmail, Microsoft and JMAP report them later, as a bounce
  mail.

### 4.6 Drafts

- **A replaced draft keeps its id on IMAP and gets a new one
  elsewhere.** Where the old one cannot be deleted, the new one is taken
  back, and only where that fails too the error names it. IMAP without
  UIDPLUS refuses before it stores the new one.
- **Without a drafts folder** an IMAP or a JMAP account lacks `drafts`.

### 4.7 Folders

- **An IMAP folder's id follows its name.** It changes when the folder
  is renamed, and so do the ids of its subfolders. The subfolders keep
  their subscription under their new names.
- **Folder counts are null on IMAP and POP3**, and on Gmail's All Mail.
  Microsoft, JMAP and other Gmail labels fill them. Left so: IMAP would
  need a `STATUS` per folder, POP3 has one folder.
- **Gmail's own folders refuse neutral operations with `400`**: a
  folder made or moved below one of its own, and a message moved into
  Sent or Drafts. Open. The domain refuses a change of a folder with a
  role with `409` first (CONCEPT 6.2).
- **Microsoft shows Outbox, Conversation History and similar folders
  without a role**, as if a person had made them. Renaming them fails at
  Graph with a general error. Left so.
- **The subfolders of an IMAP `\Noselect` folder** go below the nearest
  listed folder, or to the top.

### 4.8 Message fields

- **`snippet` is always null on IMAP and POP3**, also in `get_message`.
  Left so: IMAP and POP3 read headers for a list.
- **A Microsoft message is read from its MIME**, as on Gmail and IMAP:
  its bodies, `in_reply_to` and its attachments, inline images among
  them.

### 4.9 Threads

- **Providers group differently** (decision 6.9). The service threads
  IMAP by headers only. Gmail and Exchange use their own rules, which
  include the subject. JMAP depends on the server. POP3 lacks `threads`.
- **An IMAP thread id can be missing until the index reaches the
  message, and a merge turns the younger id into a `404`.** Native
  thread ids never do either. Decided 2026-10-16: the list of threads
  shows such a message as a thread of its own under the message's id,
  which finds the thread once the index has it (CONCEPT 6.3). The `404`
  after a merge stays.
- **Microsoft cuts long conversations at the pages read first**, which
  may not be the newest messages. Marked unverified in the code. Open.

### 4.10 The change feed

- **IMAP without CONDSTORE reports no change of read state, stars or
  keywords by another client.** The account lacks `external_changes`.
  Only the IMAP adapter has `FlagChanges`, the others learn of a change
  of flags from their changes since a point.
- **Without IDLE an IMAP account lacks `push`**, and so does a JMAP
  account without an event source. IDLE watches the inbox only.
- **A JMAP deletion carries no folder.** A message in several folders is
  reported with one of them. Left so: JMAP does not say where it was.
- **`message.updated` also means a thread merge.**
- **After an expired state**, the messages that arrived in the gap are
  reported as created, for JMAP, Gmail and Microsoft.

### 4.11 Errors and partial effects

- **Every lack of a capability answers `501`**, and so does a missing
  role folder.
- **An IMAP change of flags and folder in one request** has no
  transaction over both. The move is checked before the first `STORE`,
  and a move that fails after it says the flags are changed.
- **A batch answers what was done before a step failed.** Microsoft's
  delete for good moves to the trash, then deletes, and says so when the
  message stayed in the trash.
- **A JMAP `forbidden`**, as from a read-only token, is a
  `ProviderError`, as an HTTP `403` is. It does not set the account to
  `needs_reauth`.

## 7. What holds it

- **One test suite for all adapters.** Every adapter, through its fake,
  runs the same expectations: each operation either does what the
  neutral model says, or answers `501` and lacks the capability.
  `tests/integration/test_conformance.py` holds every kind of mailbox to
  the rules through the API, and
  `tests/data/providers/test_conformance.py` holds each adapter to its
  contract towards the domain. A test that falls short is a strict
  expected failure that names its place here. None is marked now.
- **The client package** answers the capabilities as strings. A client
  that checks the values strictly fails on new ones.
- **The MCP server** names what an account can do from the operations
  the API answers, and what it lacks from the account's capabilities
  (`list_accounts`). Its tool descriptions name no provider.
- **The UI.** Each action follows the operation that guards it. The
  parts of a change of messages, such as the keyword form, follow the
  account's capabilities as well.
- **The live checks** of Gmail, JMAP and POP3 hold the account to the
  capabilities it names: what it announces works, what it lacks answers
  `501`. The check of IMAP at the test mail server (`live/imap.py`)
  compares the names it gives with those the server offers. The checks
  against the IMAP server of our own (`smoke.py`, `changes.py`) and of
  Microsoft do not compare them.
