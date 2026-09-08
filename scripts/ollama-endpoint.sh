#!/bin/bash
# ollama-endpoint.sh — print the first reachable Ollama endpoint
#
# Probes a list of candidate Ollama endpoints in priority order and prints
# the first one that responds to /api/tags within a short timeout. Used to
# resolve OLLAMA_BASE_URL for embedding-capable scripts on machines with
# no dedicated GPU (e.g., amd-tower), with automatic fallback to a local
# Ollama instance when sapphire is unreachable.
#
# Priority order:
#   1. sapphire  (192.168.1.150) — primary, dedicated GPU compute
#   2. localhost (127.0.0.1)     — fallback, local Ollama on the current
#                                  machine. CPU-only on amd-tower, which
#                                  is still adequate for nomic-embed-text
#                                  (~12 ms/record, ~3 min per 16k backfill)
#
# Both candidates use Ollama's default port 11434. The localhost fallback
# means the pipeline keeps working in every realistic outage: sapphire
# reboot pending LUKS unlock, hardware or service failure on sapphire,
# home-network issues, or physical travel away from sapphire's network.
# The only remaining failure mode is "the current machine's own ollama
# service is stopped" — in which case the wrapper prints an empty string
# and exits 1. embed.py then falls through to its own localhost default
# (same URL), which also fails, and embedding calls return None per
# record best-effort. sync-to-postgres.py still commits INSERTs, so new
# rows land with embedding IS NULL (recoverable via backfill-embeddings.py
# once any endpoint returns).
#
# Usage (e.g. in a cron job on amd-tower):
#     OLLAMA_BASE_URL=$(~/personal-assistant/scripts/ollama-endpoint.sh) \
#         ~/personal-assistant/venv/bin/python3 \
#         ~/personal-assistant/scripts/sync-to-postgres.py
#
# Usage (ad-hoc manual catchup):
#     OLLAMA_BASE_URL=$(scripts/ollama-endpoint.sh) \
#         venv/bin/python3 scripts/backfill-embeddings.py
#
# Exit codes:
#   0 — a reachable endpoint was printed on stdout
#   1 — no candidate responded within the timeout; NOTHING is printed
#
# Consuming the failure (audit round 4d, E20)
# -------------------------------------------
# The `VAR=$(script) command` form above discards this script's status —
# the shell reports `command`'s status, not the substitution's — so a total
# outage used to be indistinguishable from success while setting
# OLLAMA_BASE_URL to an empty line. The script now prints nothing at all on
# failure, so that form at least yields an empty variable rather than a
# blank-line URL. To act on the failure, assign first and test the status:
#
#     if url=$(~/personal-assistant/scripts/ollama-endpoint.sh); then
#         OLLAMA_BASE_URL="$url" venv/bin/python3 scripts/embed.py
#     else
#         echo "no Ollama endpoint reachable; skipping embedding" >&2
#     fi

set -u

CANDIDATES=(
    "http://192.168.1.150:11434"   # sapphire  — primary (dedicated GPU)
    "http://127.0.0.1:11434"       # localhost — fallback (CPU-only on amd-tower)
)

for url in "${CANDIDATES[@]}"; do
    if curl -s --max-time 3 "${url}/api/tags" >/dev/null 2>&1; then
        echo "$url"
        exit 0
    fi
done

# Print NOTHING on failure: an empty line is a value, and a caller that
# interpolates it gets a blank URL that fails far from here.
exit 1
