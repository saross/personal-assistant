#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# push-archives-to-r2.sh — mirror the canonical cc-archives store to
# Cloudflare R2 (offsite backup + travel bridge; Phase 0e, 2026-05-28).
#
# Source:  ~/mnt/rpi-shares/cc-archives-consolidated/   (canonical store)
# Dest:    r2archives:pa-cc-archives/
#
# Architecture (continuity workstream A, decision 2026-05-20): rpi-server
# has no toolkit / cron / rclone, so the WORKING MACHINE runs rclone,
# reading the canonical store via the rpi-shares mount and pushing UP to
# R2. R2 is offsite backup + travel bridge, never the primary.
#
# Semantics — ``rclone copy`` (NOT ``sync``):
# - Additive + updates: new files uploaded, changed files (e.g. a
#   v1.2→v1.3 metadata rewrite) overwritten with the newer copy.
# - Never deletes from R2. These are open-science records we never want
#   to lose; if a session is removed from canonical we still keep the R2
#   copy. (Use ``rclone sync`` instead only if exact mirroring with
#   deletion is ever explicitly wanted.)
#
# R2 quirks handled:
# - --s3-no-check-bucket: bucket-scoped R2 tokens reject the HEAD/
#   CreateBucket preflight rclone runs before uploads; without this every
#   PutObject 403s even on a Read&Write token (diagnosed 2026-05-28).
# - --s3-disable-checksum: R2 does not implement some S3 checksum
#   operations (observed transient ``501 NotImplemented``); disabling the
#   checksum step avoids the retry churn. File-change detection falls back
#   to size + modtime, which correctly catches the metadata rewrites.
#
# Credentials: env vars ``RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID`` +
# ``_SECRET_ACCESS_KEY`` sourced from ~/personal-assistant/.env; the
# ``[r2archives]`` remote (type=s3, provider=Cloudflare, env_auth=true,
# endpoint, region=auto) lives in ~/.config/rclone/rclone.conf.
#
# Exit codes: 0 success, 1 precondition not met (skipped), 2 rclone error.
# Designed to be safe to run from daily-sync.sh (self-loads .env, does its
# own mount/remote checks) and standalone for the initial / ad-hoc push.
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PA_DIR/.env"
LOG_DIR="$PA_DIR/logs"
LOG_FILE="$LOG_DIR/r2-push.log"

CANON="$HOME/mnt/rpi-shares/cc-archives-consolidated"
DEST="r2archives:pa-cc-archives"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

mkdir -p "$LOG_DIR"

log() {
    local ts
    ts="$(date +'%Y-%m-%d %H:%M:%S')"
    printf '[%s] %s\n' "$ts" "$*" | tee -a "$LOG_FILE" >&2
}

# --- Load R2 credentials from .env (idempotent if already in env) --------
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
else
    log "r2-push: .env not found at $ENV_FILE — relying on ambient env"
fi

# --- Preconditions -------------------------------------------------------
# Override the rclone binary via RCLONE_BIN if a newer build lives outside
# PATH (e.g. a user-local ~/.local/bin/rclone alongside an old distro one).
RCLONE_BIN="${RCLONE_BIN:-rclone}"

if ! command -v "$RCLONE_BIN" >/dev/null 2>&1; then
    log "r2-push: rclone not found ($RCLONE_BIN) — skipped"
    exit 1
fi

# rclone < 1.64 has flaky Cloudflare R2 support: PutObject intermittently
# returns 501 NotImplemented, so a bulk push of thousands of files cannot
# complete within the retry budget (diagnosed 2026-05-28 on v1.60.1, which
# landed only ~20% of 4654 files before exhausting --retries). Warn loudly
# but don't hard-fail — a partial push is still progress and re-runs are
# additive.
rclone_ver="$("$RCLONE_BIN" version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)"
rclone_major="${rclone_ver%%.*}"
rclone_minor="${rclone_ver#*.}"
if [[ -n "$rclone_ver" ]] && { [[ "$rclone_major" -lt 1 ]] || { [[ "$rclone_major" -eq 1 ]] && [[ "$rclone_minor" -lt 64 ]]; }; }; then
    log "r2-push: WARNING rclone $rclone_ver is < 1.64 — known R2 501 flakiness; upgrade recommended (push may not complete)"
fi

if [[ ! -d "$CANON" ]]; then
    log "r2-push: canonical mount point missing ($CANON) — skipped"
    exit 1
fi

# Distinguish a live rpi-server mount from the silent-empty-dir failure
# mode (same guard as daily-sync.sh's cc-archives step). Pushing from an
# empty mount would be a no-op here (copy never deletes) but the check
# keeps the log honest about why nothing moved.
if ! df "$CANON" 2>/dev/null | tail -1 | grep -q "rpi-server"; then
    log "r2-push: rpi-shares not mounted (silent-empty-dir state) — skipped"
    exit 1
fi

if ! "$RCLONE_BIN" listremotes 2>/dev/null | grep -q '^r2archives:'; then
    log "r2-push: rclone remote [r2archives] not configured — skipped"
    exit 1
fi

# --- Push ----------------------------------------------------------------
RCLONE_FLAGS=(
    --s3-no-check-bucket
    --s3-disable-checksum
    --fast-list
    --transfers 16
    --checkers 16
    --stats 30s
    --stats-one-line
    --log-file "$LOG_FILE"
    --log-level INFO
)

if [[ $DRY_RUN -eq 1 ]]; then
    log "r2-push: DRY-RUN copy $CANON/ → $DEST/"
    "$RCLONE_BIN" copy "${RCLONE_FLAGS[@]}" --dry-run "$CANON/" "$DEST/"
    log "r2-push: dry-run complete"
    exit 0
fi

log "r2-push: copy $CANON/ → $DEST/ (additive, no delete)"
if "$RCLONE_BIN" copy "${RCLONE_FLAGS[@]}" "$CANON/" "$DEST/"; then
    log "r2-push: complete"
    exit 0
else
    rc=$?
    log "r2-push: rclone exited non-zero (rc=$rc; see $LOG_FILE)"
    exit 2
fi
