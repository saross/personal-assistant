#!/bin/bash
# ollama-endpoint.sh — print the first reachable Ollama endpoint
#
# Probes a list of candidate Ollama endpoints in priority order and prints
# the first one that responds to /api/tags within a short timeout. Used to
# resolve OLLAMA_BASE_URL for embedding-capable scripts on machines without
# local Ollama (e.g., amd-tower), with automatic fallback when the primary
# endpoint is down.
#
# Priority order:
#   1. sapphire (192.168.1.150) — primary, dedicated compute server
#   2. zbook    (192.168.1.80)  — fallback, when on the home LAN
#
# The fallback covers the case where sapphire is rebooted and pending LUKS
# unlock (physical console access required), or hardware/service failure,
# while zbook is present. It does NOT help when both machines are
# unreachable (power cut, off-network) — in that case the wrapper prints
# an empty string and embed.py falls through to localhost, which fails
# best-effort on amd-tower and leaves new rows with NULL embeddings
# (recoverable via backfill-embeddings.py once any endpoint returns).
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
#   1 — no candidate responded within the timeout (empty stdout)

set -u

CANDIDATES=(
    "http://192.168.1.150:11434"   # sapphire — primary
    "http://192.168.1.80:11434"    # zbook    — fallback
)

for url in "${CANDIDATES[@]}"; do
    if curl -s --max-time 3 "${url}/api/tags" >/dev/null 2>&1; then
        echo "$url"
        exit 0
    fi
done

echo ""
exit 1
