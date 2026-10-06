#!/bin/sh
# The first start of Mailbox in operation, the steps of README.md in one
# run: .env from its template, the master key, the keys in the database,
# the first administrator, then the start. Needs docker with compose.
#
#   sh setup.sh
#
# A second run changes nothing that exists: it keeps .env and the master
# key, and only starts what is not running. The recovery key and the
# one-time password of the administrator are shown once, at the first run.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
cd "$here"

say() { printf '%s\n' "$*"; }
command -v docker >/dev/null || { say "setup: docker is missing"; exit 1; }

if [ ! -e .env ]; then
    cp .env.example .env
    chmod 600 .env
    say "Wrote .env from .env.example. It names version $(sed -n 's/^MAILBOX_VERSION=//p' .env)."
fi

# The master key: a file only the container user (uid 10001) reads.
mkdir -p secrets
[ -e secrets/master_key ] || : >secrets/master_key
chmod 700 secrets
image=$(docker compose config --images | grep benethos-mailbox-service)
if [ ! -s secrets/master_key ]; then
    say "Making the master key"
    docker run --rm "$image" keys generate >secrets/master_key
    chmod 400 secrets/master_key
    # On Linux the container user must own it. The image changes the
    # owner, so this needs no sudo. Docker Desktop ignores it.
    docker run --rm --user 0 --entrypoint chown \
        -v "$here/secrets:/secrets" "$image" 10001 /secrets/master_key
fi

say "Creating the keys in the database"
if made=$(docker compose run --rm -T mailbox-service keys init 2>&1); then
    say ""
    say "$made"
    say ""
    say "The first administrator, with a one-time password:"
    docker compose run --rm -T mailbox-service users create-admin
    say ""
elif printf '%s' "$made" | grep -q "already initialized"; then
    say "They exist already: no new recovery key, no new administrator."
else
    say "$made"
    exit 1
fi

# The MCP server needs the API token of a user, which the UI makes once
# the service runs. Without it, everything else starts.
services=$(docker compose config --services)
token=$(sed -n 's/^MAILBOX_MCP_API_TOKEN=//p' .env)
if [ -z "$token" ] && printf '%s\n' "$services" | grep -qx mailbox-mcp; then
    services=$(printf '%s\n' "$services" | grep -vx mailbox-mcp)
    say "The MCP server waits for MAILBOX_MCP_API_TOKEN in .env, see README.md."
fi
# shellcheck disable=SC2086 # one service name per word
docker compose up -d --wait $services

port=$(sed -n 's/^MAILBOX_SERVICE_PORT=//p' .env)
say ""
say "Running. The UI: http://127.0.0.1:${port:-8080}/ui, sign in as admin."
