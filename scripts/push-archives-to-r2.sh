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
# Semantics — ``rclone copy --immutable`` (NOT ``sync``):
# - Additive: new files are uploaded.
# - Never deletes from R2. These are open-science records we never want
#   to lose; if a session is removed from canonical we still keep the R2
#   copy. (Use ``rclone sync`` instead only if exact mirroring with
#   deletion is ever explicitly wanted.)
# - ONE exception, by design: `CATALOG.json` at the archive root. It is a
#   DERIVED index, rebuilt from disk by `bulk-archive.py verify
#   --fix-catalogue`, so its content legitimately changes whenever a
#   session is added. It is excluded from the immutable copy and pushed
#   afterwards with `rclone copyto` and no --immutable, where a replace is
#   the intent. Nothing else in the archive is mutable: a session
#   transcript or its metadata changing IS the corruption signal.
# - Never MODIFIES any other object already in R2 (audit 2026-09-08, AR17).
#   ``--immutable`` is rclone's documented flag for exactly this: an
#   existing destination file whose size or modtime differs from the
#   source raises an error and aborts that transfer instead of
#   overwriting. The archive is append-only, so a canonical file that
#   changed is a corruption signal — a truncated transcript with a fresh
#   mtime, which ``--s3-disable-checksum``'s size+modtime comparison
#   would happily push over the last good offsite copy — and not an
#   update. The cost of the guard is that a deliberate metadata rewrite
#   (a v1.2→v1.3 schema bump) now errors here rather than propagating;
#   that is the intended trade, and such a rewrite is republished by
#   removing the old object deliberately, not by a cron job.
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
# Exit codes: 0 success, 1 precondition not met (skipped), 2 rclone or
# credential error (retryable), 3 --immutable refusal (a canonical object
# changed — corruption signal, needs a human).
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
# Read the two variables we need; do NOT source the file. `set -a; . .env`
# executed .env as a shell script — command substitutions in it would run,
# and every other secret in the file was exported into the environment of
# rclone, df, and grep (audit 2026-09-08, finding AR17). Here the file is
# only ever read as text: the value after the first `=` is assigned
# literally, so `KEY=$(rm -rf ~)` becomes those nine characters and nothing
# more.
R2_VARS=(
    RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID
    RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY
)

load_r2_var() {
    local name="$1" line value
    # Already in the ambient environment: leave it alone.
    if [[ -n "${!name:-}" ]]; then
        return 0
    fi
    line="$(grep -m1 -E "^[[:space:]]*(export[[:space:]]+)?${name}=" \
        "$ENV_FILE" 2>/dev/null || true)"
    [[ -z "$line" ]] && return 0
    value="${line#*=}"
    value="${value%$'\r'}"                 # tolerate CRLF .env files
    value="${value#"${value%%[![:space:]]*}"}"   # strip leading whitespace
    value="${value%"${value##*[![:space:]]}"}"   # strip trailing whitespace
    # Strip one matching pair of surrounding quotes, nothing else. Quotes are
    # handled BEFORE the trailing-comment strip, so a '#' inside a quoted
    # secret survives; an unquoted value ends at the first " #".
    if [[ "$value" == \"*\" ]]; then
        value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' ]]; then
        value="${value:1:${#value}-2}"
    else
        # `KEY=value   # note` — the comment is not part of the credential.
        value="${value%%[[:space:]]#*}"
        value="${value%"${value##*[![:space:]]}"}"
    fi
    export "${name}=${value}"
}

if [[ -f "$ENV_FILE" ]]; then
    for _r2_var in "${R2_VARS[@]}"; do
        load_r2_var "$_r2_var"
    done
    unset _r2_var
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
# Audit 2026-09-08 S14: the trailing `|| true` is load-bearing. Under
# `set -euo pipefail` a non-matching `grep` (an rclone whose version banner
# does not carry an X.Y number, or one that errored with its output
# suppressed by 2>/dev/null) makes the whole pipeline non-zero and killed the
# script HERE — before the mount and remote preconditions below, and before
# any log line, so daily-sync reported the indistinguishable "push skipped or
# errored". The probe is advisory only: an unparseable version must fall
# through to an empty string, which the -n guard on the next line handles.
rclone_ver="$("$RCLONE_BIN" version 2>/dev/null \
    | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1 || true)"
rclone_major="${rclone_ver%%.*}"
rclone_minor="${rclone_ver#*.}"
rclone_too_old=0
if [[ -n "$rclone_ver" ]]; then
    if [[ "$rclone_major" -lt 1 ]]; then
        rclone_too_old=1
    elif [[ "$rclone_major" -eq 1 ]] && [[ "$rclone_minor" -lt 64 ]]; then
        rclone_too_old=1
    fi
fi
if [[ $rclone_too_old -eq 1 ]]; then
    log "r2-push: WARNING rclone $rclone_ver is < 1.64 — known R2 501" \
        "flakiness; upgrade recommended (push may not complete)"
fi

if [[ ! -d "$CANON" ]]; then
    log "r2-push: canonical mount point missing ($CANON) — skipped"
    exit 1
fi

# Distinguish a live rpi-server mount from the silent-empty-dir failure
# mode (same guard as daily-sync.sh's cc-archives step). Pushing from an
# empty mount would be a no-op here (copy never deletes) but the check
# keeps the log honest about why nothing moved.
# Captured first, then matched with a here-string: `… | grep -q` makes a
# MATCH read as a failure under `pipefail` once the producer has more to
# write than a pipe buffer holds (audit round 4c-7, finding C-1, and the
# repository lint in tests/test_pipefail_grep_lint.py). `df` on one path is
# small enough that it never bit here, but the shape is the defect.
canon_mount="$(df "$CANON" 2>/dev/null | tail -1 || true)"
if ! grep -q "rpi-server" <<< "$canon_mount"; then
    log "r2-push: rpi-shares not mounted (silent-empty-dir state) — skipped"
    exit 1
fi

configured_remotes="$("$RCLONE_BIN" listremotes 2>/dev/null || true)"
if ! grep -q '^r2archives:' <<< "$configured_remotes"; then
    log "r2-push: rclone remote [r2archives] not configured — skipped"
    exit 1
fi
# Both credentials must actually be set. Without this an unreadable .env, or
# one that has lost the R2 lines, sailed past every precondition above and
# ran a real rclone copy with no credentials — thousands of 403s against the
# retry budget, a log full of failures, and an exit code that says "rclone
# error" rather than "you have no keys" (audit round 4c-2, finding 10).
missing_creds=()
for _r2_var in "${R2_VARS[@]}"; do
    if [[ -z "${!_r2_var:-}" ]]; then
        missing_creds+=("$_r2_var")
    fi
done
unset _r2_var
if [[ ${#missing_creds[@]} -gt 0 ]]; then
    log "r2-push: missing R2 credential(s): ${missing_creds[*]} — set them" \
        "in $ENV_FILE or the environment; refusing to run"
    exit 2
fi

# --- Push ----------------------------------------------------------------
# Flags every invocation shares. Kept separate from the immutable-copy
# flags below because the catalogue push deliberately does NOT take
# --immutable; see CATALOGUE_FILE_NAME.
RCLONE_BASE_FLAGS=(
    # Pin the log format. The classifier below reads the level marker out of
    # rclone's own lines, and `--log-format` is settable from the ambient
    # environment (RCLONE_LOG_FORMAT) as well as by `--use-json-log`. Either
    # would reshape every line and turn every refusal into exit 2, silently
    # — the same failure C1 caused by assuming a shape rclone never emits.
    # `date,time` is rclone's own default, so this pins today's behaviour
    # rather than changing it (audit round 4c-7, finding M-2).
    --log-format date,time
    # Never upload a staged temporary. normalise-archive-storage.py and
    # bulk-archive.py both write via `<name>.tmp` and rename; a process
    # killed in between leaves the partial file behind. Uploading one is
    # worse than it sounds: the push is --immutable and never deletes, so a
    # half-written temporary becomes a PERMANENT object in R2 that cannot
    # be replaced or removed (audit round 4c-3, finding L-10).
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

#: The ONE file in the archive root that is mutable by design. CATALOG.json
#: is a DERIVED index, rebuilt from disk by `bulk-archive.py verify
#: --fix-catalogue`, so its content legitimately changes whenever a session
#: is added — it is a rebuild, not a rewrite of history.
#:
#: --immutable therefore refuses it, correctly by its own rule and wrongly
#: for this file: since 2026-09-09 10:28 every daily push exited 3
#: ("investigate before re-running") over a file whose change is expected,
#: and before the flag the log shows it as "Copied (replaced existing)" on
#: every run. So it is excluded from the immutable copy and pushed
#: separately afterwards, without --immutable, where a replace is the
#: intent (audit round 4c-7, live-consequence addendum).
#:
#: Nothing else in the archive is mutable. A session transcript or its
#: metadata changing IS the corruption signal --immutable exists to raise.
CATALOGUE_FILE_NAME="CATALOG.json"

# The immutable bulk copy: everything except the staged temporaries and the
# derived catalogue.
RCLONE_COPY_FLAGS=(
    "${RCLONE_BASE_FLAGS[@]}"
    # Never upload a staged temporary. normalise-archive-storage.py and
    # bulk-archive.py both write via `<name>.tmp` and rename; a process
    # killed in between leaves the partial file behind. Uploading one is
    # worse than it sounds: this copy is --immutable and never deletes, so
    # a half-written temporary becomes a PERMANENT object in R2 that cannot
    # be replaced or removed (audit round 4c-3, finding L-10).
    --exclude "*.tmp"
    # The derived index, handled separately below. The leading slash
    # anchors the pattern at the root of the transfer, so a session
    # directory that happens to contain a CATALOG.json is still covered by
    # the immutable rule.
    --exclude "/$CATALOGUE_FILE_NAME"
    # Refuse to modify an object already in R2 — see the header. An
    # existing file whose size or modtime differs from the source is a
    # corruption signal in an append-only archive, not an update.
    --immutable
)

# Push the derived catalogue, which is allowed to change. Runs only AFTER a
# successful immutable copy, so the index can never describe objects that
# failed to upload. A failure here is always transport — there is no
# --immutable and so no corruption signal to read — and is reported exit 2.
push_catalogue() {
    local dry_run="$1" source="$CANON/$CATALOGUE_FILE_NAME" rc=0
    if [[ ! -f "$source" ]]; then
        log "r2-push: no $CATALOGUE_FILE_NAME at $source — nothing to" \
            "publish (the archive has not been catalogued yet)"
        return 0
    fi
    if [[ "$dry_run" == "dry-run" ]]; then
        log "r2-push: DRY-RUN copyto $CATALOGUE_FILE_NAME (mutable," \
            "no --immutable)"
        "$RCLONE_BIN" copyto "${RCLONE_BASE_FLAGS[@]}" --dry-run \
            "$source" "$DEST/$CATALOGUE_FILE_NAME" || rc=$?
    else
        log "r2-push: copyto $CATALOGUE_FILE_NAME (mutable, no --immutable)"
        "$RCLONE_BIN" copyto "${RCLONE_BASE_FLAGS[@]}" \
            "$source" "$DEST/$CATALOGUE_FILE_NAME" || rc=$?
    fi
    if [[ $rc -ne 0 ]]; then
        # Never exit 3 here: this step carries no --immutable, so a failure
        # cannot be a corruption signal. The archive itself is already
        # safely uploaded; only the index is stale.
        log "r2-push: catalogue push failed (rc=$rc; see $LOG_FILE) —" \
            "the archive copy SUCCEEDED, only the derived index is stale;" \
            "transport failure, safe to retry"
        exit 2
    fi
    return 0
}

# Classify a failed transfer and exit. Shared by the dry-run and real
# branches, so a dry run cannot report a failure differently from the run it
# is previewing (audit round 4c-4, finding 6).
#
# $LOG_FILE is append-only and shared with every previous run, so grepping
# the WHOLE file latches: the ABORTED message this script writes itself
# contains the word "--immutable", so one genuine abort made every later
# transport failure exit 3 for ever (round 4c-3, finding M-1). Only the
# bytes this run appended are examined.
classify_failure_and_exit() {
    local rc="$1" bytes_before="$2" label="$3" this_run_output refusal_re
    # Only the bytes THIS run appended. $LOG_FILE is append-only and shared
    # with every previous run, so a refusal recorded weeks ago would
    # otherwise re-classify today's transport failure for ever.
    this_run_output="$(tail -c "+$((bytes_before + 1))" "$LOG_FILE" \
        2>/dev/null || true)"

    # Two very different failures share rclone's non-zero exit, and they want
    # opposite responses (round 4c-2, finding 12). A network or auth failure
    # is transient: the next run retries and nothing is wrong with the
    # archive. An --immutable refusal means a canonical object CHANGED,
    # which in an append-only archive is a corruption signal that a retry
    # cannot fix and that a human has to look at.
    #
    # Matched on rclone's ERROR/NOTICE lines carrying its own refusal
    # wording, NOT on the bare word "immutable" anywhere in the output.
    # This one test is what keeps every other source of that word out of the
    # decision: the paths in rclone's own INFO lines, and the paths this
    # script logs (CANON derives from $HOME, so our lines carry it too).
    #
    # A separate filter for our own lines is NOT needed and is deliberately
    # absent: log() writes `[YYYY-MM-DD HH:MM:SS] r2-push: …`, which carries
    # no level marker, so no line this script writes can satisfy the match
    # below. A second guard that no test could fail is the dead guard round
    # 4c-3 L-1 removed elsewhere.
    #
    # The level marker is matched as a TOKEN, not at the line start.
    # rclone's --log-format defaults to `date,time`, so every line it writes
    # to --log-file is `YYYY/MM/DD HH:MM:SS LEVEL : …` and an anchored
    # `^(ERROR|NOTICE)` matches nothing it ever emits — verified on the
    # deployed log, where 9,314 lines carry a level and zero match the
    # anchor, and against the binary, whose strings hold the layout
    # `2006/01/02 15:04:05` and the level format `%-6s: %s` (audit round
    # 4c-6, finding C1). That padding is also why the marker may be
    # `ERROR :` with a space but `NOTICE:` without one.
    # rclone logs one INFO line per transferred object naming its relative
    # path, so a single project slug containing the word — say
    # `-home-shawn-immutable-notes` — turned every transport failure into a
    # corruption abort (audit round 4c-5, finding L1).
    #
    # Only $LOG_FILE is read, never rclone's stderr. rclone writes its
    # refusals to the --log-file we give it, so in practice the two agree;
    # but if a future rclone reported one ONLY on stderr, this classifier
    # would call it exit 2, "safe to retry". That is the safe direction and
    # is left as it is deliberately (round 4c-5, finding L5): the retry is
    # harmless — --immutable refuses again rather than overwriting — so the
    # cost is a wasted run and a second identical failure, whereas teeing
    # stderr into the shared append-only log would put text we do not
    # control into the file the next run classifies against.
    #
    # What is ATTESTED, and what is merely defensive — the two are not the
    # same and an earlier revision of this comment ran them together (audit
    # round 4c-7, finding M-1).
    #
    # Attested by the deployed log, which carries both a level and the
    # wording for two real refusals recorded 2026-09-09:
    #
    #   ERROR : CATALOG.json: Source and destination exist but do not
    #           match: immutable file modified
    #   NOTICE: Failed to copy: immutable file modified
    #
    # Note the levels: the SAME event is reported at ERROR on one line and
    # NOTICE on another, which is why both are matched.
    #
    # Attested only as WORDING, by `strings $(command -v rclone) | grep -i
    # immutable` on v1.74.2: the string "Timestamp mismatch between
    # immutable objects!" exists in the binary. Its LEVEL is unverified and
    # it occurs zero times in the deployed log, so it is matched
    # defensively, at either level, and must not be read as observed.
    #
    # If a future rclone adds a phrasing not listed here, this classifier
    # fails SAFE: the run exits 2 ("safe to retry") rather than 3, so the
    # mistake is a wasted retry, not a missed corruption signal reported as
    # an abort.
    #
    # ONE grep, and no pipe. Chaining `… | grep -q …` looks equivalent and
    # is not: `grep -q` exits at its first match, the upstream grep then
    # dies of SIGPIPE, and the whole pipeline returns 141 under `pipefail`
    # — so the `if` took the FALSE branch and a real refusal was reported
    # "safe to retry", but only once more than a pipe buffer (~64 KB) of
    # marker-level output followed the refusal in the same run. That is the
    # ordinary regime here: the deployed log holds 4,658 `ERROR :` lines in
    # 2.5 MB (audit round 4c-7, finding C-1). A here-string has no
    # upstream process to kill.
    refusal_re='(^|[[:space:]])(ERROR|NOTICE)[[:space:]]*:.*'
    refusal_re+='(immutable file modified|immutable objects)'
    if grep -qE "$refusal_re" <<< "$this_run_output"; then
        log "r2-push: ABORTED — rclone refused to modify an object already" \
            "in R2 (--immutable). The archive is append-only, so a" \
            "canonical file whose size or modtime changed is a corruption" \
            "signal, not an update. Investigate before re-running; see" \
            "$LOG_FILE"
        exit 3
    fi
    log "r2-push: $label exited non-zero (rc=$rc; see $LOG_FILE) —" \
        "transport or auth failure, safe to retry"
    exit 2
}

# Where this run's output starts, recorded immediately before the transfer.
log_bytes_before=0
if [[ -f "$LOG_FILE" ]]; then
    log_bytes_before="$(wc -c < "$LOG_FILE")"
fi

if [[ $DRY_RUN -eq 1 ]]; then
    log "r2-push: DRY-RUN copy $CANON/ → $DEST/"
    # `set -e` would have killed the script here on any rclone failure,
    # exiting with rclone's raw status — and rclone's exit 1 would then read
    # as this script's "precondition not met, skipped" (round 4c-4, L-6).
    rc=0
    "$RCLONE_BIN" copy "${RCLONE_COPY_FLAGS[@]}" --dry-run \
        "$CANON/" "$DEST/" || rc=$?
    if [[ $rc -ne 0 ]]; then
        classify_failure_and_exit "$rc" "$log_bytes_before" "dry-run rclone"
    fi
    push_catalogue dry-run
    log "r2-push: dry-run complete"
    exit 0
fi

log "r2-push: copy $CANON/ → $DEST/ (additive, no delete, no overwrite)"

# `rc=$?` AFTER the `fi` reads the status of the `if` statement, which is
# zero whenever its else-branch ran — so the transport message reported
# "exited non-zero (rc=0)" every time (round 4c-4, finding 5). Captured
# inside the branch instead.
rc=0
"$RCLONE_BIN" copy "${RCLONE_COPY_FLAGS[@]}" "$CANON/" "$DEST/" || rc=$?
if [[ $rc -ne 0 ]]; then
    classify_failure_and_exit "$rc" "$log_bytes_before" "rclone"
fi

# Only now, with every archive object safely uploaded, publish the index.
push_catalogue live
log "r2-push: complete"
exit 0
