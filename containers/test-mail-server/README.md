# Test mail server

[Stalwart](https://stalw.art) in a container, as a mail server of our own
for trying the adapters: IMAP, POP3, SMTP and JMAP, with two accounts and
no real mail. It is a manual aid like the scripts in `live/`, never part
of `uv run pytest`.

## Set it up

Needs Docker with compose and `openssl`, on Linux, macOS or in WSL:

```
sh containers/test-mail-server/setup.sh
```

The script makes the server anew each time. It removes the container's
volumes, sets up the domain `mailbox.test` (reserved for tests, RFC 2606),
a certificate of a local test CA, the listeners and the accounts `test1`
and `test2`, and checks that TLS answers with that certificate.

What it keeps between runs, in `containers/secrets/` (not versioned):

| File | Holds |
|---|---|
| `test-mail-server.env` | the administrator of Stalwart's recovery mode |
| `test-mail-server-accounts.env` | the addresses and passwords of the two accounts |
| `test-mail-server-tls/ca.pem` | the test CA, which a client must trust |
| `test-mail-server-tls/` | the CA's key and the server's certificate and key |

So a second run gives the same accounts, and a client that trusts the CA
keeps trusting it. Delete these files for new passwords and a new CA.

## Ports

On `127.0.0.1` only, 30000 plus the standard port:

| Protocol | TLS | STARTTLS |
|---|---|---|
| IMAP | 30993 | 30143 |
| POP3 | 30995 | 30110 |
| SMTP submission | 30465 | 30587 |
| JMAP, HTTPS | 30443 | |
| HTTP, Stalwart's management | | 30080 (plain) |

The certificate names `localhost`, `127.0.0.1`, `::1` and
`mail.mailbox.test`. Under WSL, the ports reach Windows as well.

## Use it with the service

The service checks every certificate. To trust the test CA, start it, or
a live check, with `SSL_CERT_FILE` naming `ca.pem`. Its host names
resolve to private addresses, which the service refuses unless they are
named as internal:

```
export SSL_CERT_FILE=containers/secrets/test-mail-server-tls/ca.pem
export MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS='["localhost"]'
```

`SSL_CERT_FILE` replaces the default file of OpenSSL. On Linux the
process then trusts only the test CA. Set it for a process that talks to
this server alone.

## Run it

```
docker compose -f containers/test-mail-server/compose.yaml stop
docker compose -f containers/test-mail-server/compose.yaml start
docker compose -f containers/test-mail-server/compose.yaml down -v   # remove it
```

To change its configuration, start it in recovery mode, which serves only
the management API on port 30080, with the administrator of
`test-mail-server.env`:

```
STALWART_RECOVERY_MODE=true docker compose -f containers/test-mail-server/compose.yaml up -d --force-recreate
```

Then use the [Stalwart CLI](https://stalw.art/docs/management/cli/), as
`setup.sh` does, and start it again without the variable.
