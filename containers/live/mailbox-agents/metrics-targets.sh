#!/bin/sh
# Names the agents' workers to Prometheus: writes prometheus/targets/agents.json
# with the address of this machine as the containers reach it, and the
# ports 38900 to 38905, one per worker that runs at once. setup.sh runs
# it. Run it again when the address changed, such as after a restart of
# WSL. Prometheus reads the file anew by itself.
#
#     sh containers/live/mailbox-agents/metrics-targets.sh [ADDRESS]
#
# Without ADDRESS: the default gateway, which in WSL is the Windows host
# the agents run on.

set -eu

here=$(cd "$(dirname "$0")" && pwd)
host="${1:-$(ip route | awk '/^default/ { print $3; exit }')}"
[ -n "$host" ] || { echo "metrics-targets: no address found, name one" >&2; exit 2; }

mkdir -p "$here/prometheus/targets"
targets=""
for port in 38900 38901 38902 38903 38904 38905; do
    targets="$targets${targets:+, }\"$host:$port\""
done
printf '[{"targets": [%s]}]\n' "$targets" > "$here/prometheus/targets/agents.json.new"
mv "$here/prometheus/targets/agents.json.new" "$here/prometheus/targets/agents.json"
echo "metrics-targets: the workers at $host, ports 38900 to 38905" >&2
