#!/bin/sh
# Prepares a Linux host, or a WSL distribution, for the service llama-gpu:
# installs the NVIDIA Container Toolkit from NVIDIA's package repository
# and writes the CDI spec that names the card nvidia.com/gpu=all.
#
# Run as root, on Debian or Ubuntu with the NVIDIA driver installed
# (nvidia-smi works). In WSL the driver comes from Windows. Inside WSL:
#   sudo sh containers/live/mailbox-agents/nvidia-toolkit.sh
# From Windows:
#   wsl -d <distribution> -u root -- sh containers/live/mailbox-agents/nvidia-toolkit.sh
#
# It can run again: the repository and the package are kept up to date and
# the spec is written anew, after a driver update for instance. Docker reads
# CDI specs when it creates a container, so neither Docker nor a running
# container is restarted, and the docker runtime setting is left alone.

set -eu

say() { printf 'nvidia-toolkit: %s\n' "$1" >&2; }

if [ "$(id -u)" != 0 ]; then
    say "run it as root"
    exit 2
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
    say "no nvidia-smi: install the NVIDIA driver first"
    exit 1
fi

keyring=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
list=/etc/apt/sources.list.d/nvidia-container-toolkit.list

say "NVIDIA's package repository"
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --batch --yes --dearmor -o "$keyring"
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed "s#deb https://#deb [signed-by=$keyring] https://#g" > "$list"

say "the toolkit"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nvidia-container-toolkit >/dev/null
nvidia-ctk --version | head -1 >&2

say "the CDI spec"
mkdir -p /etc/cdi
nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml >/dev/null 2>&1
nvidia-ctk cdi list >&2

if command -v docker >/dev/null 2>&1; then
    say "a container with the card"
    # Pinned by the digest of its multi-platform index, as every image of
    # the repository is.
    docker run --rm --device nvidia.com/gpu=all \
        ubuntu:24.04@sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289 \
        nvidia-smi -L
fi
