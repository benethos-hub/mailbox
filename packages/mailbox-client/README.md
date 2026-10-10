# <img src="https://raw.githubusercontent.com/benethos-hub/mailbox/main/assets/logo/icon-3d.svg" alt="" height="36" align="absmiddle"> mailbox-client

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI benethos-mailbox-client](https://img.shields.io/pypi/v/benethos-mailbox-client?label=PyPI%20benethos-mailbox-client)](https://pypi.org/project/benethos-mailbox-client/)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-client)](https://pypi.org/project/benethos-mailbox-client/)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

> **Beta, version 0.4.0.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

The Python client of the REST API of
[`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service),
on PyPI as `benethos-mailbox-client`. It covers the whole REST API: it
reads, searches, sorts, drafts and sends mail of the accounts the
service holds, and administers the service: accounts, users, roles,
tokens, second factors, webhooks, the audit and the state of the
service, as far as its token allows. Every operation of the API is a
method of both clients, named like its `operationId`. The MCP server of the project,
[`mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp),
is built on it.

It knows the service through its REST API alone, and needs nothing but
[httpx](https://www.python-httpx.org/). The REST API follows the status
above. This package's Python interface has no stability promise yet.

What the project is for: [the repository's README](https://github.com/benethos-hub/mailbox#readme).

## Install

```sh
uv add benethos-mailbox-client      # or: pip install benethos-mailbox-client
```

## Use

Make a token on your user's page in the service's UI. The client reads
it from `MAILBOX_SERVICE_TOKEN`, and the address of the service from
`MAILBOX_SERVICE_URL` (default `http://127.0.0.1:8080`). Both can be
passed as arguments instead.

For async code:

```python
from benethos_mailbox_client import MailboxClient

async with MailboxClient() as mailbox:
    me = await mailbox.get_me()
    for account in me.accounts:
        page = await mailbox.list_messages(account.id, folder="inbox", limit=10)
        for summary in page.items:
            print(account.email, summary.sender, summary.subject)
```

For code without an event loop, `SyncMailboxClient` has the same
methods (`close()` for `aclose()`) and answers the same records:

```python
from benethos_mailbox_client import SyncMailboxClient, message_body

with SyncMailboxClient() as mailbox:
    body = message_body(
        to=[("someone@example.org", None)],
        cc=[],
        bcc=[],
        subject="Hello",
        text="Hi there",
        html=None,
        reference=None,
    )
    mailbox.send_message("acc_...", body, idempotency_key="hello-1")
```

Administering the service works the same way. A user with a grant and a
token for it:

```python
from benethos_mailbox_client import Grant, SyncMailboxClient

with SyncMailboxClient() as mailbox:
    user = mailbox.create_user(
        "desktop",
        grants=[Grant(accounts=("acc_...",), allow=("mail.read", "drafts"))],
    )
    made = mailbox.create_token(user.id, "laptop")
    print(made.secret.get_secret_value())  # shown this once
```

A message comes as a `Message`, a message in a page, a changed one
and a written draft as a `MessageSummary`, its sender and recipients
as `Address` records.

A secret the service shows once, a new token, a one-time password or a
webhook's signing secret, comes as a `Secret`: `repr` and `str` show
stars, so it reaches no log by accident, and `get_secret_value()` reads
it. Lists that page answer `Paged`, with `next_cursor` for the next
page.

`request(method, path, ...)` sends any request and answers its JSON as
it comes, e.g. for a field a record leaves out. The routes and their
fields:
[`docs/openapi.json`](https://github.com/benethos-hub/mailbox/blob/main/docs/openapi.json).

The token travels in a header. Over http the client talks only to this
machine. To another machine it needs https, or
`MAILBOX_SERVICE_ALLOW_HTTP=1` (`allow_http=True`) for a network you
trust, such as between containers.

A client made without an address or a token reads the environment when
it is made. A program that makes clients for a long time can read it
once, with `from_environment()`:

```python
from benethos_mailbox_client import MailboxClient, from_environment

found = from_environment()
client = MailboxClient(found.url, found.token, allow_http=found.allow_http)
```

## Errors

Everything the client raises is a `MailboxError`:

| Error | When |
|---|---|
| `ConfigurationError` | no token, or an address it refuses |
| `ServiceUnavailableError` | the service cannot be reached |
| `ServiceTimeoutError` | the service took the request but did not answer in time |
| `ApiError` | the API answered with an error: `status`, `code`, `message` |

## Inside

Each endpoint is described once, in `endpoints/`, one module per
resource of the API: its method, path, query, body and how its answer
becomes a record of `models/`. That package sends nothing.
`MailboxClient` sends those requests with `httpx.AsyncClient`,
`SyncMailboxClient` with `httpx.Client`, and a method of either is one
line made from its endpoint, with the endpoint's name, docstring and
signature, `get_attachment`, which streams, a few more. A test holds
every operation of the API to a method of both clients. What both share stands
beside them: the address and the token (`environment.py`), the shape
of a request (`calls.py`), how an answer or a failure is read
(`answers.py`) and an attachment read in chunks (`attachments.py`).

## License

MIT, see [LICENSE](https://github.com/benethos-hub/mailbox/blob/main/LICENSE).
