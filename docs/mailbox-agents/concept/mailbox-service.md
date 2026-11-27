# Concept: the mailbox service

Part of the [concept](../CONCEPT.md).

The agents use the service's REST API through `benethos-mailbox-client`.
Operation names below are the service's `operationId`s.

| Need | Operation |
|---|---|
| What changed since the last look | `list_all_changes` with a state token |
| A message, its text and attachment list | `get_message` |
| The conversation a message belongs to | `get_thread` |
| Set or remove a keyword, move to a folder | `update_message` |
| The folders of an account, read anew in every pass: a renamed folder keeps its id with Microsoft, Gmail and JMAP **(to verify)** | `list_folders` |
| Make a folder, below a parent or at the top | `create_folder` |
| A forward of a message as a draft, and whether one is there already | `create_draft` with a `reference` to forward, `list_drafts` and `get_message` |
| The messages received since a day, for `backfill` | `list_all_messages`, once for the inbox and once for sent mail |
| The messages of one folder since a day, for `backfill` | `list_messages` of one account, the folder by its id |
| The accounts to look in for those folders, and for the folders `status` checks, without `ACCOUNTS` | `get_me` |
| The version of the service, before every pass and every backfill | `health` |

`sources/mailbox.py` offers these and nothing else: no send, no delete, no
trash. Which folder an agent may make is the runtime's to decide
([agent contract](agent-contract.md)). A move sets the message's folders to
the one target. A message is read with its text part. When that holds
white space only, or is missing, the visible text of its HTML part takes
its place, with `mail_text` of `mailbox-common`, as the mail page of the
service and the MCP server read it. Hidden elements, scripts and styles
are left out (2026-11-22).
A message carries `sender_check`, what the account's receiving server
stated about the domain of its sender: `pass`, `fail` or `unknown`,
and `unknown` when the answer has none. Another value is an answer that
is not what the API describes, a refusal (2026-11-27). No agent acts on
it yet.
A forward is drafted with `create_draft`: the addresses, no subject and
no text of its own, and a `reference` to the message with the action
`forward` and its form. Whether it is there is looked up on the first
page of `list_drafts`, a draft to exactly those addresses whose
`reference` names the message. Assumed until a live check has shown
it: a user with `mail.read` and `drafts` may make a draft with a
`reference` **(to verify)**, the service sets the subject `Fwd: ...` and
carries the attachments of the original when `inline` **(to verify)**,
and the original stays unchanged until the draft is sent **(to
verify)**.
An answer from `500` on and a `429` count as the service away: the pass
ends and the runtime waits. A `501` with the code `not_supported` is
not: it says what an account cannot do, a keyword on Gmail or POP3, a
draft on an account without a drafts folder. It is a refusal of that
request, logged as refused and not recorded, the message ends and the
pass goes on (2026-11-27).
`list_all_messages` without a folder lists the inbox alone (measured
2026-11-17 against 0.7.5), so a backfill names each folder role it wants.

What the agents rely on:

- The feed names created, updated, deleted and sent messages by id and
  answers with a new state token. A token older than the service keeps
  changes for answers `410 changes_expired`.
- The feed may name a change more than once. Every step is therefore
  idempotent ([runtime](runtime.md)).
- The text of a message is its plain text part. The service does not
  convert an HTML body: the agents do, as above.
- A change of flags made in another mail client reaches the feed only where
  the provider reports it, for IMAP with CONDSTORE. `awaiting_reply` depends
  on this ([awaiting reply](agent-awaiting-reply.md)).
- Keywords are not available on every provider **(to verify per account
  before an agent is switched to the stage `suggest`)**. At Stalwart over
  IMAP they are: measured 2026-11-17 against 0.7.5, a keyword set and
  taken off again, and 2026-11-20 against 0.8.0 and 2026-11-21 against
  0.9.0, where `live/mailbox-agents/categorization.py` and `live/mailbox-agents/invoices.py`, removed with the agent `invoices`, set an agent's
  keyword, find it on the message and take it off when they put the mail
  back.

A keyword as a signal between agents, for the instances of `categorization`
that wait for one ([the chain](categorization-chain.md)), measured 2026-11-25
against 0.11.1 with IMAP at Stalwart, on the test account: a keyword set
through `update_message`, a second one set, the first taken off, the
second taken off. Each change came as one `message.updated` of the same
id, about 9 seconds later, and `get_message` showed the keywords as set.
A keyword a person sets or takes off in a mail client over IMAP reaches
the feed as well, measured 2026-11-25 against Stalwart 1.2 with a
service whose worker waits in IDLE: a second IMAP client set a keyword
with `STORE +FLAGS` and took it off with `STORE -FLAGS`. Each change
came as one `message.updated` of the same id, within two seconds, and
`get_message` showed the keyword set and then gone.

Folders and moves, measured 2026-11-18 against 0.7.5 with IMAP at
Stalwart, on the test account:

- A move through `update_message` keeps the message's id. The feed names
  it as `message.updated` of that id, once per move.
- A move made by a mail client over IMAP keeps the message's id as well
  (measured 2026-11-19 against 0.7.5, for the plan of
  the agent `invoices` version 5). One message was moved out of
  the inbox into a folder made for the check and back, once with `MOVE`
  and once with `COPY`, `\Deleted` and `EXPUNGE`, as clients without
  `MOVE` do. Each way the feed named only `message.updated` of the same
  id, within one sync, no `message.created` and no `message.deleted`.
  `get_message` read it under that id in its new folder, and a keyword
  set before the move went with it. So the state file of an agent knows a
  message a person moves by hand, and its open item follows it. A message
  under an id no state file knows, but with an agent's keyword, comes from
  a state file made anew, or from a provider that gives a moved message a
  new id, which this check did not see at Stalwart.
- A message moved and moved back keeps its id (measured 2026-11-19 to
  2026-11-21 against 0.8.0 and 0.9.0). A message that came back under a
  new id would be new to an agent's state file: an agent asks about it
  anew, unless its own rule leaves a message with its keyword alone.
- `create_folder` makes a folder at the top without a parent, and below
  another with the parent's id. At IMAP a folder's id follows its path.
- A name that exists in the same case is refused, `409 conflict`. The same
  name in another case is made as a second folder beside the first, as IMAP
  names differ by case. So the runtime compares names ignoring case itself
  before it makes one.
- `delete_folder` is refused, `403 forbidden`, to a user with `mail.read`
  and `mail.write`. A folder an agent made is removed by the owner.
- A folder deleted or renamed at IMAP is no longer listed by its old id.
  A move through `update_message` to that id answers `404 not_found`,
  the same status and code as a message that is gone, and the message
  stays where it was. `create_folder` below a parent deleted so answers
  `404 not_found` as well. So the runtime reads the folders anew before
  the folders and the move of a message, and after such an answer to a
  folder or a move it asks for the message again: when it answers, the
  action is refused, and the message is not ended as gone.
- A message that arrives straight in a folder other than the inbox, as one
  a mail server files by a rule of its own, reaches the feed as
  `message.created`, here about 20 seconds after it arrived, and is read
  in that folder.
- `list_messages` of one account lists the messages of a folder named by
  its id, with `after` for a day. Named by its path it answers
  `404 not_found`. `list_all_messages` takes a role only and answers a
  folder id with `422 validation_error`. So a backfill of a folder looks up
  the folder's id first and asks each account by itself.
- A cursor of a list holds until the service starts again. One from
  before a restart answers `400 bad_request`, measured 2026-11-19 against
  0.8.0 with a restart between two pages of the inbox. The state of the
  feed holds across a restart: the same measurement read the feed from a
  state taken before it. A backfill keeps a cursor for one listing only,
  so a restart of the service in the middle of a backfill ends it with
  exit code 1 before it takes anything up, and the backfill is run again.
- A message the feed or a listing names may be gone by the time it is
  read. The runtime then ends it as `skipped`, as for any message deleted
  before it is read, and nothing is decided or done.
- `get_me` answers the agents' user exactly the one account it is
  granted, the test account (measured 2026-11-18). `list_accounts` answers it `200` with no
  account at all: it belongs to the group `accounts.read`, which an agent
  is not granted. So the accounts an agent works on come from `get_me`.
  Without `ACCOUNTS` a backfill looks in the folders of each of them, so
  an account whose inbox and sent mail are empty is not left out.

Rights. Each agent has a user of its own in the service:

| Agent | Rights | Not granted |
|---|---|---|
| `awaiting_reply` | `mail.read`, `mail.write` | `drafts`, send, `mail.delete` |
| `inquiries` | `mail.read`, `mail.write` | `drafts`, send, `mail.delete` |
| `categorization` | `mail.read`, `mail.write` | `drafts`, send, `mail.delete` |
| `counting` | `mail.read` | `mail.write`, `drafts`, send, `mail.delete` |
| `filing` | `mail.read`, `mail.write` | `drafts`, send, `mail.delete` |

`counting` changes nothing, so `mail.read` is all it needs. Measured
2026-11-20 against 0.8.0 on the test account: `status`, `backfill`, `run`
and `report` of `counting` under a user with `mail.read` alone, and no
call refused.

`mail.write` also allows moving a message to the trash and creating a
folder. The service cannot refuse those to an agent that may move mail, so
the runtime does ([safety](safety.md)). Narrowing a grant to chosen folders is
possible in the service
([PERMISSIONS.md](../../mailbox-service/PERMISSIONS.md#85-two-more-constraints)):
`mail.write` with folders moves only between them, and refuses a change of
a message that also lies outside them. A move of an agent replaces the
message's folders with the one target. Whether an agent works under such
a grant is not measured yet.

A move into the drafts folder is refused by the service since 0.9.0,
`400 bad_request`, and the message stays where it was: measured
2026-11-21 against 0.9.0 with IMAP at Stalwart, one message of the inbox
of the test account. The runtime refuses only the trash, junk and spam as
a target by itself, so an agent moves a message into drafts only where
its settings name that folder: a target of the categorization list. In the stage `full` such a move
meets the `400` and is logged as refused and not recorded, as any refused
action. In `shadow` and `suggest` it is recorded and the service is not
asked.

## The version of the service

The service names its version at `/health`, which it answers without a
right and counts against no limit. While its major version is 0, a minor
release may change what it does and what its interface takes, and the
offline suite sees none of that: it mocks the service. The agents are
released with the service under one version, so they work against the
service of their own version (decided 2026-11-22):

- **Before 1.0** the service has the agents' minor version: the agents
  0.10.x take the service 0.10.x, of any patch. **From 1.0** it has their
  major version and a minor version no older than theirs: the agents
  1.2.x take the service 1.2.0 and later releases of 1, since a newer
  minor release adds and an older one may lack a route the agents call
  (decided 2026-11-22).
- **A release** is three numbers with at most a local part after a `+`,
  such as `0.10.0+local`. A pre-release of the service such as
  `0.10.0rc1` or `0.10.1.dev3` matches no agents, also one of a later
  patch (decided 2026-11-20). The agents' own version
  counts by its first two numbers, also as a pre-release.
- **The check** is `matches` in `sources/versions.py`, against
  `__version__` of the package. The worker asks the service for its
  version before every pass and every backfill. A service of another
  version, or one that names no version or refuses `/health`, ends the
  command with a `ServiceVersionError` and exit code 2, before the feed is
  read: nothing is read, decided or changed. Its message names the
  version the agents take and says to run the agents of the service's
  version. It is asked in every pass and not only at the start, since a
  service can be replaced by another release between two passes without
  one request failing. A `503` at `/health` is no other version: it is
  the service away, as while it cannot reach its database
  (`service_unavailable`). The pass then ends at the question for the
  version and waits as for a service away **(to verify)**.
- **In every stage, with no setting to pass it.** The stage `shadow` is
  refused as well: what it records would be read from a service nobody
  measured. A warning alone would go unread in a process that runs for
  weeks.
- **`eval`** asks too, before it reads the gold set's mail, and is
  refused the same way (decided 2026-11-20).
- **`status`** names the version of the service and whether it matches,
  or that it names none, and starts no agent. `status` and `report` read
  only for showing and are not refused.
- **The client** is pinned to the agents' version, `==X.Y.Z`, as the
  workspace releases both together.

What follows from it: an operator updates the image of the service and
the images of the agents together, to the same version.

An agent does not go back to the stage `shadow` because of a new release
of the service (decided 2026-11-19): its prompt and its model are the
same, and the live checks on the test account are the gate for the
service.
