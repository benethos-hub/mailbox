#!/bin/sh
# Fetches the local models of the live setup as GGUF files into
# containers/live/mailbox-agents/models/, which the llama services mount read-only. The
# services themselves never reach the internet.
#
#   sh containers/live/mailbox-agents/fetch-models.sh                 # the default model
#   sh containers/live/mailbox-agents/fetch-models.sh qwen3.5-9b ...  # the models named
#   sh containers/live/mailbox-agents/fetch-models.sh all             # every model below
#   sh containers/live/mailbox-agents/fetch-models.sh list            # names and sizes
#
# Each file comes from a fixed revision of its repository and is checked
# against its size and its sha256 there: a complete and checked one is
# skipped, a partial one resumed, a wrong one fetched again. A file once
# checked gets <name>.gguf.sha256 beside it, so the next run need not read
# it again. The names are the presets of llama/presets-gpu.ini and
# llama/presets-cpu.ini, and a model's file is named after its preset, so
# the routers list it under that name.

set -eu

here=$(cd "$(dirname "$0")" && pwd)
dir="${MODELS_DIR:-$here/models}"
hub=https://huggingface.co

# name | repository | revision | file | sha256 | bytes, looked up 2026-11-18
MODELS='
qwen3-4b-2507|unsloth/Qwen3-4B-Instruct-2507-GGUF|a06e946bb6b655725eafa393f4a9745d460374c9|Qwen3-4B-Instruct-2507-Q4_K_M.gguf|3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597|2497281120
qwen3.5-4b|unsloth/Qwen3.5-4B-GGUF|e87f176479d0855a907a41277aca2f8ee7a09523|Qwen3.5-4B-Q4_K_M.gguf|00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4|2740937888
gemma-4-e4b|unsloth/gemma-4-E4B-it-GGUF|bfc15c382204943c3a8fff0c750b94ae2364d7a3|gemma-4-E4B-it-Q4_K_M.gguf|85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87|4977171584
ministral-3-8b|mistralai/Ministral-3-8B-Instruct-2512-GGUF|0102285ad796bd99af90f58de616092e5630e970|Ministral-3-8B-Instruct-2512-Q4_K_M.gguf|33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761|5198911904
qwen3.5-9b|unsloth/Qwen3.5-9B-GGUF|3885219b6810b007914f3a7950a8d1b469d598a5|Qwen3.5-9B-Q4_K_M.gguf|03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8|5680522464
gemma-4-12b|google/gemma-4-12b-it-qat-q4_0-gguf|29d097773436b69ff9feafd636ab4cf873786537|gemma-4-12b-it-qat-q4_0.gguf|93567e57a8fe10b23569b9d9ec38cd005deedf71e29477c421a4b83f418a538b|6975879296
qwen3.6-35b-a3b|unsloth/Qwen3.6-35B-A3B-GGUF|a483e9e6cbd595906af30beda3187c2663a1118c|Qwen3.6-35B-A3B-UD-Q4_K_M.gguf|ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61|22134528992
'
# The model of mail-classifier-cpu in litellm.yaml.
DEFAULT=qwen3.5-4b

say() { printf 'fetch-models: %s\n' "$1" >&2; }

field() { printf '%s' "$line" | cut -d'|' -f"$1"; }

size_of() { if [ -f "$1" ]; then stat -c%s "$1"; else echo 0; fi; }

# Whether the file is complete and the one the table names. Writes the
# mark beside it when it is.
checked() {
    [ "$(size_of "$target")" = "$bytes" ] || return 1
    [ -f "$target.sha256" ] && [ "$(cat "$target.sha256")" = "$sha" ] && return 0
    [ "$(head -c4 "$target")" = "GGUF" ] || return 1
    say "checking $1"
    [ "$(sha256sum "$target" | cut -d' ' -f1)" = "$sha" ] || return 1
    printf '%s\n' "$sha" > "$target.sha256"
}

fetch() {
    line=$(printf '%s\n' "$MODELS" | grep "^$1|") || { say "no model named $1"; exit 2; }
    repo=$(field 2)
    url="$hub/$repo/resolve/$(field 3)/$(field 4)"
    sha=$(field 5)
    bytes=$(field 6)
    target="$dir/$1.gguf"
    if checked "$1"; then
        say "$1 is there and checked"
        return 0
    fi
    rm -f "$target.sha256"
    if [ "$(size_of "$target")" -ge "$bytes" ]; then
        rm -f "$target"
    fi
    say "fetching $1 from $repo"
    # The hub redirects to a CDN, so -L. -C - resumes a partial file.
    curl -fsSL -C - -o "$target" "$url"
    if ! checked "$1"; then
        say "$1 is not the file the table names: removed, run again"
        rm -f "$target"
        exit 1
    fi
    say "$1 fetched and checked"
}

mkdir -p "$dir"
if [ $# -eq 0 ]; then
    set -- "$DEFAULT"
fi
for name in "$@"; do
    case "$name" in
        list)
            printf '%s\n' "$MODELS" | awk -F'|' 'NF { printf "%-18s %5.1f GB  %s\n", $1, $6 / 1e9, $2 }'
            ;;
        all)
            for each in $(printf '%s\n' "$MODELS" | awk -F'|' 'NF { print $1 }'); do
                fetch "$each"
            done
            ;;
        *)
            fetch "$name"
            ;;
    esac
done
