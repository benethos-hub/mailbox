# mailbox-client

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI mailbox-client](https://img.shields.io/pypi/v/benethos-mailbox-client?label=PyPI%20mailbox-client)](https://pypi.org/project/benethos-mailbox-client/)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-client)](https://pypi.org/project/benethos-mailbox-client/)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

> **Alpha, version 0.2.0.** Usable with real accounts for testing. The
> API and the configuration may still change. Stored data is carried
> forward by migrations.

The Python client of the REST API of
[`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service),
on PyPI as `benethos-mailbox-client`. It reads, searches, sorts, drafts
and sends mail of the accounts the service holds, as far as its token
allows. The MCP server of the project,
[`mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp),
is built on it.

It knows the service through its REST API alone, and needs nothing but
[httpx](https://www.python-httpx.org/). Its interface has no stability
promise yet: it follows what the MCP server and the project's own checks
need.

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
    me = await mailbox.me()
    for account in me.accounts:
        page = await mailbox.list_messages(account.id, folder="inbox", limit=10)
        for summary in page.items:
            print(account.email, summary["subject"])
```

For code without an event loop, `SyncMailboxClient` has the same
methods and answers the same records:

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

`request(method, path, ...)` reaches any route of the API the methods do
not cover and answers its JSON. The routes and their fields:
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

Each endpoint is described once, in `endpoints.py`: its method, path,
query, body and how its answer becomes a record. That module sends
nothing. `MailboxClient` sends those requests with `httpx.AsyncClient`,
`SyncMailboxClient` with `httpx.Client`, and each method of either is
one line.

## License

MIT, see [LICENSE](https://github.com/benethos-hub/mailbox/blob/main/LICENSE).
