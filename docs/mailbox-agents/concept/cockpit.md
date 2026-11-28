# Concept: cockpit

Part of the [concept](../CONCEPT.md).

**Status: prototype, 2026-11-27.** Its stylesheet,
`cockpit/static/css/app.css`, is a copy of the one of the mailbox
service, `web/pages/static/css/app.css` of `mailbox-service`, held equal
byte for byte by `tests/test_packaging.py`: a wheel carries the files of
its own folder alone.

The cockpit is a page of what every agent did, for its owner. It reads
the state files and shows each instance: its profile, its state, its
counts, its decisions, its open items, the newest results, and one
message with its decision, its evidence, its steps and its actions.

It only reads. It writes no state file, changes no mail, asks no model
and holds no token of an agent. It reads a state file through the
methods of the store alone, opened read-only for one request.

It finds the instances through sources behind one seam: a source names
its instances, and each opens its state for reading and says whether its
writer stopped. The pages do not know which source an instance comes
from. A name a source before took already is not shown a second time.

Decided on 2026-11-27:

- It stands apart from the pages of the mailbox service, a command of
  the agents of its own.
- It is built with the framework of the service: FastAPI, Jinja2 and
  `python-multipart`, served by uvicorn.
- It is started by hand, never by itself: `benethos-mailbox-agents
  cockpit`. It serves until SIGINT or SIGTERM.
- As a prototype, a person signs in with one secret, read from a file.

## Where it reads from

Every `*.db` in `DATA_DIR` and in its direct folders, so a folder per
volume of an agent needs no setting of its own. An instance is named by
its file without the ending, with the name of its folder before it when
two folders hold a file of the same name. A page names an instance and
never takes a path from its address: a name it does not find is a page
of 404.

The worker writes its profile into the state file when it starts
([state](state.md)): the stage, the accounts, the keyword, the seconds
between polls and of a model call, the model alias and the versions. The
cockpit holds none of these settings and reads them there. A file older
than the profile, or one whose worker has not started since the update,
shows its name and counts and says "no profile yet".

A file that cannot be read, is no state file, or is of a newer schema, is
a row with its reason, never an error of the page. So is a state that
fails while its page reads it. An error no page expects is a page of
its own with the headers below, and a line in the log names its class
alone.

### On a PostgreSQL server

With `COCKPIT_DATABASE_URLS` the cockpit reads the servers it names as
well, signed in with a role of its own, such as `agents_cockpit`, a
member of the read role `agents_read` that `storage provision` makes
(2026-11-27). On each server it finds every database the role may
connect to, and in it each schema where it may read the table
`profile`: that is an instance. The cockpit shows what its role may
read. An owner gives it that by naming the read role in
`DATABASE_READERS`, which the agent grants at each start, and any role
that owns such a table could give it as well. A table that only
`PUBLIC` may read is left out. A database whose owner did not, or the database of the service,
which it closes to every other role, is not found. The instance is
named by its database, with its schema after it where the database
holds several.

It reads on a short connection of its own for each instance and
request, whose transactions only read, without a lock and without a step
of the schema. A database that answers with another schema, or a server
that is away, is a row with its reason. No file says whether a writer
there stopped: an instance without fresh progress is `silent`.

Every role of a server sees the names of all its databases. The read
role sees no row of a database it was not given. It can never change a
state, but in a database it may connect to it sees the key of the
agent's lock in `pg_locks` and could hold it, so that the agent does
not start: give the read role only to the cockpit and to roles trusted
as much as the agent.

## The state of an instance

| State | When |
|---|---|
| `healthy` | a writer holds the file and its last progress is within the window of its health, worked out from the numbers of its profile |
| `silent` | a writer holds the file and its last progress is older |
| `stopped` | no writer holds the file. Never on a server |
| `no profile yet` | a writer holds the file, which has no profile |
| `unreadable` | the file cannot be read, with the reason |

A writer in WAL mode keeps `-wal` beside the file with what it wrote, at
the least its profile, and takes it away when it closes the file
cleanly. A reader in a folder it may write leaves an empty `-wal` behind,
which says nothing of a writer. So the file of a writer that was killed,
or that stopped while the cockpit read it, reads as running, and as
`silent` once its window has passed. A reader from a folder it may not
write, such as a volume mounted read-only, opens a cleanly closed file as
immutable ([state](state.md)).

**Measured on 2026-11-27** with the image of the agents built from the
repository, a writer and the cockpit in two containers, the volume
mounted read-only in the cockpit. A writer that runs shows as `healthy`.
After `docker stop` it shows as `stopped` and is still read. After
`docker kill` it shows as running until its window has passed. When the
cockpit starts first, Docker makes the volume owned by root, and the
agent that mounts it at `/data` later still writes to it: Docker gives
the empty volume the owner of `/data` in the image, uid 10001.

## Signing in

`COCKPIT_SECRET` or `COCKPIT_SECRET_FILE` holds the secret. Without it
the cockpit does not start. Whoever holds the secret sees everything the
state files hold, the quotes of mail among it.

- The secret is compared in constant time. The form of the sign-in
  carries a nonce that a cookie holds, so a page of elsewhere cannot sign
  a browser in.
- A session lives in the memory of the process, for 8 hours without a
  request and 24 hours at most. A restart signs everyone out. Its cookie
  is `HttpOnly`, `SameSite=strict`, `Secure` when the cockpit itself
  serves https, and ends with the browser.
- Ten failed sign-ins from one address in 15 minutes hold it for 15
  minutes. The page names only the wait. The address is that of the
  connection: no `X-Forwarded-For` is believed.
- Signing out is a form with a token of the session.
- A page says nothing it takes from its address: a notice is chosen by a
  key from a fixed list.

The numbers are those of the pages of the mailbox service.

## Subject and sender

The state file holds ids. The cockpit fetches subject and sender from the
mailbox service when `SERVICE_URL` and `SERVICE_TOKEN` or
`SERVICE_TOKEN_FILE` are set, and shows the ids alone otherwise. Its
token is best one of a user of its own with `mail.read` alone. Its line
in the log says when it shows the ids alone. A mailbox service that
does not answer, or whose settings are wrong, leaves the ids alone as
well, and the page says so.

## Every answer

- `content-security-policy: default-src 'self'; script-src 'none';
  style-src 'self'; img-src 'self' data:; frame-ancestors 'none';
  form-action 'self'; base-uri 'none'`
- `x-content-type-options: nosniff`, `referrer-policy: same-origin`
- `cache-control: no-store` for a page, `no-cache` for the stylesheet.

No page holds a script or a style of its own or loads anything from
elsewhere. Everything from a state file or a mail is foreign text: it
passes `text_values.escaped` of `mailbox-common`, and the page escapes it
as HTML, and no template marks a text as safe.

## Its limits

- One machine for the files: it reads the state files it can reach on
  its disk or its volumes, and the servers `COCKPIT_DATABASE_URLS` names.
- No paging and no search: the newest results, 50 by default, 200 at
  most.
- Nothing to change: no stage, no list, no pause.
