# Architecture of the Python client

The modules of `mailbox-client`: section 3.2 of the
[architecture](../mailbox-service/ARCHITECTURE.md). The shape, the
layers of the service and the rules for every package (sections 5
to 17) are there.

## 3.2 The client

The Python client of the REST API is a package of its own. It cannot
import the service or the MCP server, and its
`tests/test_architecture.py` checks that, with the lines below, a
package counting as one, httpx only in the modules that make or read
a request or check an address, and the endpoints reached through
their package alone.

```
packages/mailbox-client/
  src/benethos_mailbox_client/
    __init__.py         # what a caller imports: both clients, the
                        #   records, the errors, message_body(),
                        #   from_environment()
    client.py           # MailboxClient: sends the calls with
                        #   httpx.AsyncClient, one line per method
    sync.py             # SyncMailboxClient: the same calls with
                        #   httpx.Client
    endpoints/          # each endpoint once, one module per resource
                        #   of the API, with the readings of its
                        #   records. Sends nothing
      me.py             # get_me(): the caller and its accounts, the
                        #   catalogue of rights
      health.py         # whether the service answers
      accounts.py       # list, connect, read, change, verify, remove,
                        #   the names receiving servers wrote
      discovery.py      # discovery, the sign-in with a code
      folders.py        # the folders of an account
      messages.py       # lists and search in one account or across,
                        #   a message and its source, flags, keywords
                        #   and moves for one or many, deleting, and
                        #   the page the drafts read too
      changes.py        # the change feed of one account or of all
      attachments.py    # an attachment's bytes, a link to it
      threads.py        # the threads of a folder, one thread
      drafts.py         # list, write, replace, delete drafts
      sending.py        # send a message, send a draft, each at once or
                        #   through the outbox
      outbox.py         # the sends of the outbox, one, cancelling one
      sends.py          # the audit of sends
      users.py          # users, a password set
      tokens.py         # a user's tokens
      roles.py          # roles
      rights.py         # grants read and written, for users and roles
      factors.py        # a user's second factor
      webhooks.py       # webhooks, a new signing secret
      audit.py          # the audit of administration
      status.py         # the state of the service
      readings.py       # what the resources read alike: times, pages
      compose.py        # message_body: what drafts and sending share
      generic.py        # request(): any route, its JSON as it comes
    answers.py          # an answer read: its JSON, the error envelope
                        #   as ApiError, an answer that cannot be
                        #   read, a failure on the way
    attachments.py      # an attachment's bytes in chunks, up to a
                        #   limit, what its headers say
    environment.py      # the address and the token: from the
                        #   environment (from_environment) or given,
                        #   checked before a client is made
    calls.py            # Call: the request an endpoint describes,
                        #   its path below /v1, the timeouts. Awaiting
                        #   and blocking make a client's method of it
    models/             # the records the clients answer with, one
                        #   module per resource as in endpoints/, every
                        #   one offered by its __init__.py
      me.py             # the caller, its accounts, its sending limits
      health.py         # the service's health and version
      accounts.py       # an account, its stored credentials and marks,
                        #   the names receiving servers wrote
      discovery.py      # what discovery found, a sign-in with a code
      folders.py        # a folder
      messages.py       # a message and its summary with its sender
                        #   check, a page, a batch's outcome
      changes.py        # the changes since a state
      attachments.py    # an attachment's bytes, a link to an attachment
      threads.py        # a thread and its summary
      sending.py        # a recipient, what a send answered, a send in
                        #   the outbox
      sends.py          # a record of the audit of sends
      rights.py         # a grant, the catalogue of rights
      users.py          # a user, a password made for one
      tokens.py         # a token, a new one with its secret
      roles.py          # a role
      factors.py        # a second factor and its devices
      webhooks.py       # a webhook, its posts, a new one or a new
                        #   signing secret
      audit.py          # an activity of the audit
      status.py         # the worker and the health of each account
      paging.py         # Paged: a page of records and its cursor
      secrets.py        # Secret: what the service shows once, kept out
                        #   of repr and str
    errors.py           # MailboxError and its subclasses
```

The modules stand in lines, each importing only lines below:

```
 client · sync
 endpoints
 answers · attachments · environment
 calls
 models · errors
```

**An endpoint of the client** is a function in the module of its
resource in `endpoints/` that answers a `Call`, named like the
operation's `operationId`, and a one-line method on each client made
from it: `list_users = awaiting(endpoints.list_users)` in
`MailboxClient`, `blocking(...)` in `SyncMailboxClient` (`calls.py`).
The method takes the function's arguments and has its name, docstring
and signature. Its test is in `tests/endpoints/`, in the file of that
module, and runs for both clients. Neither client
knows a path or a field: when the two differ in more than `await`,
the difference belongs in `endpoints/`, `calls.py` or `answers.py`.
