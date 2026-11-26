#!/bin/sh
# Makes PostgreSQL a database for the suite against a server, anew:
# removes its volume, starts it, waits until it answers, and writes what
# the tests need to connect to secrets/tests.env. Needs docker with
# compose and openssl.
#
#   sh containers/test-database/setup.sh
#
# Then MAILBOX_POSTGRES_TESTS names that file for pytest. What it keeps
# between runs, in secrets/ beside it (not versioned): the password of
# the administrator. Never printed.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
secrets="$here/secrets"
password="$secrets/admin_password"
tests_env="$secrets/tests.env"

say() { printf '%s\n' "$*"; }

for tool in docker openssl; do
    command -v "$tool" >/dev/null || { say "setup: $tool is missing"; exit 1; }
done

mkdir -p "$secrets"
chmod 0700 "$secrets"

umask 077
if [ ! -e "$password" ]; then
    openssl rand -hex 16 >"$password"
fi
# The image reads the file as the user postgres.
chmod 0644 "$password"
{
    printf 'host=127.0.0.1\n'
    printf 'port=35432\n'
    printf 'user=postgres\n'
    printf 'database=postgres\n'
    printf 'password_file=%s\n' "admin_password"
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
