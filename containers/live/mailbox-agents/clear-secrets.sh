#!/bin/sh
# Clears the secrets/ of the live setup for setup.sh: removes what the
# setup and its checks make there, and nothing else. When secrets/ holds
# anything else, such as the state files of a run on a real account, it
# names each and stops with exit code 2 before anything is removed, so the
# owner moves it first.
#
#     sh containers/live/mailbox-agents/clear-secrets.sh <secrets folder>
#
# The Claude API key in secrets/anthropic_api_key stays: setup.sh keeps it
# across runs.

set -eu

secrets="${1:?the secrets folder}"
[ -d "$secrets" ] || exit 0

# What setup.sh and provision.py make, the folder of the agents' state
# that agent.env names, the reports of README.md, and the gold files of
# live/mailbox-agents/gold.py.
made="agent.env service-token service-admin stalwart-admin master_key
gateway.env gateway-db.env tls data reports"

ours() {
    case "$1" in
        anthropic_api_key | gold-*.jsonl) return 0 ;;
    esac
    # sh has no local variables: a name of its own, so the caller's stays.
    for known in $made; do
        [ "$1" = "$known" ] && return 0
    done
    return 1
}

unknown=""
for entry in "$secrets"/* "$secrets"/.[!.]*; do
    [ -e "$entry" ] || continue
    name=$(basename "$entry")
    ours "$name" || unknown="$unknown $name"
done
if [ -n "$unknown" ]; then
    printf 'setup: %s holds what the setup does not make:%s\n' "$secrets" "$unknown" >&2
    printf 'setup: move it elsewhere first. Nothing was removed.\n' >&2
    exit 2
fi

for name in $made; do
    rm -rf "${secrets:?}/$name"
done
rm -f "$secrets"/gold-*.jsonl
