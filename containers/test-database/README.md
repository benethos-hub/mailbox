# <img src="../../assets/brand/icon.svg" alt="" height="36" align="absmiddle"> Test database

PostgreSQL 19 in a container, as the server of the suite against
PostgreSQL: the storage of the service on a database server, in a
schema of its own for each test. Without it `uv run pytest` leaves that
suite out. CI's job `postgres` runs it on a server of its own.

**Contents**

- [Set it up](#set-it-up)
- [Run the suite](#run-the-suite)
- [Run it](#run-it)

## Set it up

Needs Docker with compose and `openssl`, on Linux, macOS or in WSL:

```
sh containers/test-database/setup.sh
```

The script makes the server anew each time. It removes the container's
volume, starts PostgreSQL on `127.0.0.1:35432` (30000 plus the standard
port, on the loopback alone) with TLS from a test CA of its own, and
waits until it answers. Under WSL, the port reaches Windows as well.
The certificate names `localhost`, `db.mailbox.test`, `127.0.0.1` and
`::1`.

What it keeps in `secrets/` beside it (not versioned):

| File | Holds |
|---|---|
| `admin_password` | the password of the administrator `postgres`, made once, never printed |
| `tests.env` | what the tests need to connect: host, port, user, database and the names of the password file and the two CAs |
| `tls/ca.pem` | the test CA the server's certificate comes from |
| `tls/other-ca.pem` | a second CA, for the tests that a strange certificate is refused |
| `tls/` | the keys of both CAs and the server's certificate and key |

Delete `admin_password` for a new password, the files of `tls/` for new
certificates.

## Run the suite

`MAILBOX_POSTGRES_TESTS` names `tests.env`. With it the tests of the
repositories run on PostgreSQL as well, beside memory and SQLite, and
the folder `packages/mailbox-service/tests/postgres/` is collected:

```
MAILBOX_POSTGRES_TESTS=containers/test-database/secrets/tests.env uv run pytest packages/mailbox-service/tests
```

Each test gets a schema of its own and drops it after. Nothing else on
the server is touched.

## Run it

```
docker compose -f containers/test-database/compose.yaml stop
docker compose -f containers/test-database/compose.yaml start
docker compose -f containers/test-database/compose.yaml down -v   # remove it
```
