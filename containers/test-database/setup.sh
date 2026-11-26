#!/bin/sh
# Makes PostgreSQL a database for the suite against a server, anew:
# removes its volume, starts it with TLS from a test CA of its own, waits
# until it answers, and writes what the tests need to connect to
# secrets/tests.env. Needs docker with compose and openssl.
#
#   sh containers/test-database/setup.sh
#
# Then MAILBOX_POSTGRES_TESTS names that file for pytest. What it keeps
# between runs, in secrets/ beside it (not versioned): the password of
# the administrator, never printed, and the test CA with the server's
# certificate, and a second CA no certificate comes from, for the tests
# that a strange one is refused.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
secrets="$here/secrets"
password="$secrets/admin_password"
tests_env="$secrets/tests.env"
tls="$secrets/tls"

say() { printf '%s\n' "$*"; }

for tool in docker openssl; do
    command -v "$tool" >/dev/null || { say "setup: $tool is missing"; exit 1; }
done

mkdir -p "$secrets" "$tls"
chmod 0700 "$secrets" "$tls"

umask 077
if [ ! -e "$password" ]; then
    openssl rand -hex 16 >"$password"
fi
# The image reads the file as the user postgres.
chmod 0644 "$password"

# A test CA, the server's certificate for the names a test uses, and a
# second CA of nothing.
for ca in ca other-ca; do
    if [ ! -e "$tls/$ca.pem" ]; then
        openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
            -subj "/CN=Mailbox test database $ca" \
            -addext "basicConstraints=critical,CA:TRUE" \
            -addext "keyUsage=critical,keyCertSign,cRLSign" \
            -keyout "$tls/$ca.key" -out "$tls/$ca.pem" 2>/dev/null
    fi
done
if [ ! -e "$tls/server.pem" ]; then
    openssl req -newkey rsa:2048 -nodes -subj "/CN=db.mailbox.test" \
        -keyout "$tls/server.key" -out "$tls/server.csr" 2>/dev/null
    printf 'subjectAltName=DNS:localhost,DNS:db.mailbox.test,IP:127.0.0.1,IP:::1\nextendedKeyUsage=serverAuth\n' \
        >"$tls/server.ext"
    openssl x509 -req -in "$tls/server.csr" -CA "$tls/ca.pem" -CAkey "$tls/ca.key" \
        -CAcreateserial -days 825 -extfile "$tls/server.ext" -out "$tls/server.pem" 2>/dev/null
    rm -f "$tls/server.csr" "$tls/server.ext"
fi
# The container copies the key for its own user at start.
chmod 0644 "$tls/server.key" "$tls/server.pem"
{
    printf 'host=127.0.0.1\n'
    printf 'port=35432\n'
    printf 'user=postgres\n'
    printf 'database=postgres\n'
    printf 'password_file=%s\n' "admin_password"
    printf 'ca_file=%s\n' "tls/ca.pem"
    printf 'other_ca_file=%s\n' "tls/other-ca.pem"
} >"$tests_env"
umask 022

compose() { docker compose -f "$here/compose.yaml" "$@"; }

say "Removing the database and its volume, if there are any"
compose down -v >/dev/null 2>&1 || true

say "Starting PostgreSQL"
compose up -d >/dev/null 2>&1
tries=0
# The image starts a server twice: wait for the one that listens on TCP.
until docker exec mailbox-test-postgres \
    psql -h 127.0.0.1 -U postgres -Atc "SELECT 1" >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 60 ] || { say "setup: PostgreSQL did not answer"; exit 1; }
    sleep 1
done
say "Ready on 127.0.0.1:35432: MAILBOX_POSTGRES_TESTS=$tests_env"
