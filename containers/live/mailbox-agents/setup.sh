#!/bin/sh
# Makes the live setup anew: a test CA and a certificate for the mail
# server, Stalwart with one account made for the agents, the mailbox
# service with an administrator, the account connected, a user for the
# agents with mail.read and mail.write on it, its token, invented mail,
# and the model gateway in front of Claude and of a local model.
#
# Needs Docker with compose, openssl, curl and python3, as README.md says:
# curl fetches the file of a local model. Run from the repository:
#   sh containers/live/mailbox-agents/setup.sh
#
# Claude is used when its API key is in containers/live/mailbox-agents/secrets/anthropic_api_key
# or in ANTHROPIC_API_KEY. Without one, or with MAILBOX_LIVE_LOCAL=gpu or
# MAILBOX_LIVE_LOCAL=cpu, a local model under llama.cpp is started and the agents
# are set to it: on the graphics card when the host has NVIDIA's CDI spec
# or MAILBOX_LIVE_LOCAL=gpu, else on the CPU. Its model is fetched first.
#
# It removes the volumes of an earlier run. What it makes stays in
# containers/live/mailbox-agents/secrets/, never versioned: the CA, the passwords, the
# tokens, and secrets/agent.env, the settings the agents and agents_smoke.py read.
# The Claude API key and the fetched models are kept across runs.
#
# The mailbox service is built from this checkout, the version of the
# agents beside it. MAILBOX_LIVE_SERVICE=published with MAILBOX_VERSION
# pulls a published release instead (compose.published.yaml).

set -eu
# Secrets readable by their owner only. What a container reads as another
# user is opened up below, one file at a time.
umask 077

here=$(cd "$(dirname "$0")" && pwd)
secrets="$here/secrets"
# The compose file by the environment, not by -f: a path with a space
# would split the command where $compose is used unquoted below.
export COMPOSE_FILE="$here/compose.yaml"
case "${MAILBOX_LIVE_SERVICE:-checkout}" in
    checkout) ;;
    published) COMPOSE_FILE="$COMPOSE_FILE:$here/compose.published.yaml" ;;
    *) echo "setup: MAILBOX_LIVE_SERVICE is checkout or published, not $MAILBOX_LIVE_SERVICE" >&2
       exit 2 ;;
esac
compose="docker compose"

say() { printf 'setup: %s\n' "$1" >&2; }

anthropic_key="${ANTHROPIC_API_KEY:-}"
if [ -z "$anthropic_key" ] && [ -f "$secrets/anthropic_api_key" ]; then
    anthropic_key=$(tr -d ' \r\n' < "$secrets/anthropic_api_key")
fi

backend="${MAILBOX_LIVE_LOCAL:-}"
if [ -z "$anthropic_key" ] && [ -z "$backend" ]; then
    if ls /etc/cdi/nvidia*.yaml /var/run/cdi/nvidia*.yaml >/dev/null 2>&1; then
        backend=gpu
    else
        backend=cpu
    fi
fi
case "$backend" in
    "" | gpu | cpu) ;;
    *) say "MAILBOX_LIVE_LOCAL is gpu or cpu, not $backend"; exit 2 ;;
esac

say "removing an earlier run"
$compose --profile gpu --profile cpu down --volumes --remove-orphans >/dev/null 2>&1 || true
rm -rf "$secrets"
mkdir -p "$secrets/tls"
(umask 022 && mkdir -p "$here/models")
if [ -n "$anthropic_key" ]; then
    printf '%s\n' "$anthropic_key" > "$secrets/anthropic_api_key"
fi

say "a test CA and a certificate for mail.agents.test"
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=mailbox-agents live test CA" \
    -keyout "$secrets/tls/ca.key" -out "$secrets/tls/ca.pem" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=mail.agents.test" \
    -keyout "$secrets/tls/server.key" -out "$secrets/tls/server.csr" 2>/dev/null
printf 'subjectAltName=DNS:mail.agents.test,DNS:localhost,IP:127.0.0.1\n' > "$secrets/tls/san.ext"
openssl x509 -req -in "$secrets/tls/server.csr" -CA "$secrets/tls/ca.pem" \
    -CAkey "$secrets/tls/ca.key" -CAcreateserial -days 3650 \
    -extfile "$secrets/tls/san.ext" -out "$secrets/tls/server.pem" 2>/dev/null
chmod 644 "$secrets/tls/ca.pem"

say "passwords and keys"
rand() { openssl rand -hex 16; }
stalwart_admin=$(rand)
mailbox_password=$(rand)
service_password="$(rand)Aa1!"
gateway_key="sk-live-$(rand)"
gateway_db_password=$(rand)
printf 'POSTGRES_USER=litellm\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=litellm\n' \
    "$gateway_db_password" > "$secrets/gateway-db.env"
{
    printf 'LITELLM_MASTER_KEY=%s\n' "$gateway_key"
    printf 'DATABASE_URL=postgresql://litellm:%s@gateway-db:5432/litellm\n' \
        "$gateway_db_password"
    if [ -n "$anthropic_key" ]; then
        printf 'ANTHROPIC_API_KEY=%s\n' "$anthropic_key"
    fi
} > "$secrets/gateway.env"

say "the master key of the mailbox service"
$compose run --rm --no-deps -T mailbox-service keys generate > "$secrets/master_key"
# The container's user reads it. A test key, so readable rather than owned.
chmod 444 "$secrets/master_key"
$compose run --rm --no-deps -T mailbox-service keys init > /dev/null
one_time=$($compose run --rm --no-deps -T mailbox-service users create-admin 2>/dev/null)

say "Stalwart in bootstrap mode"
STALWART_RECOVERY_ADMIN="admin:$stalwart_admin" $compose up -d stalwart >/dev/null 2>&1

say "the mailbox service and the gateway"
$compose up -d mailbox-service gateway >/dev/null 2>&1

model=mail-classifier
if [ -n "$backend" ]; then
    # The model behind the alias mail-classifier-<gpu|cpu> in litellm.yaml.
    name=$(awk -v alias="mail-classifier-$backend" '
        $0 ~ "model_name: " alias "$" { found = 1; next }
        found && /model: openai\// { sub(/.*model: openai\//, ""); print; exit }
    ' "$here/litellm.yaml")
    say "the local model $name on the $backend, fetched once into containers/live/mailbox-agents/models"
    (umask 022 && sh "$here/fetch-models.sh" "$name")
    $compose --profile "$backend" up -d "llama-$backend" >/dev/null 2>&1
    model="mail-classifier-$backend"
fi
if [ -z "$anthropic_key" ]; then
    say "no Claude API key: the agents use the local model"
fi

say "provisioning"
STALWART_URL=http://127.0.0.1:38080 \
STALWART_BOOTSTRAP_PASSWORD="$stalwart_admin" \
MAILBOX_PASSWORD="$mailbox_password" \
SERVICE_URL=http://127.0.0.1:38081 \
SERVICE_ONE_TIME_PASSWORD="$one_time" \
SERVICE_PASSWORD="$service_password" \
GATEWAY_URL=http://127.0.0.1:38400/v1 \
GATEWAY_MASTER_KEY="$gateway_key" \
GATEWAY_MODEL="$model" \
SECRETS="$secrets" \
    python3 "$here/provision.py"

say "done: containers/live/mailbox-agents/secrets/agent.env holds the settings for the agents"
