#!/usr/bin/env python3
"""Standing anchor drift-sweep (item 8) — full anchored back-set + trend log.

Re-resolves **every** anchored memory against the current working tree + git
history and records the outcome to an append-only trend log, so anchor drift
(files moved/deleted after a memory was written) can be tracked over time.

It reuses the memory-health report's ``tier_c_audit`` engine verbatim
(resolution via ``anchor_verify`` + ``triage_anchors``), so there is a single
classification code path. The three things it adds over the report's Tier-C
(per the 2026-06-06 scoping in
``wiki/planning/memory-write-path-plan.md`` §6a):

1. **Full back-set, not a trailing window.** Tier-C only re-checks anchors
   written in the last N days (default 30). That window happens to cover the
   entire anchored population *today* — the anchoring epoch is 2026-05-16 — but
   will not once the epoch is more than 30 days past (≈ late July 2026), at
   which point old anchors silently age out of Tier-C. This sweep uses an
   effectively-infinite window, so it never ages out: drift on a long-lived
   anchor is exactly what it exists to catch.
2. **Append-only trend log** (``data/logs/drift-sweep.jsonl``) — one JSON line
   per run, for week-over-week comparison (e.g. in the weekly review).
3. **A threshold exit code** (``--alert-threshold``) — exits 1 when the fail
   rate exceeds the threshold, for cron/hook alerting.

**Read-only** with respect to the corpus and PostgreSQL: it mutates nothing,
takes no locks, and only appends to its own trend log. Safe to run during
concurrent extraction (the memory-health-report posture). No API calls.

Usage:
    python3 scripts/drift-sweep.py                 # sweep + append a trend line
    python3 scripts/drift-sweep.py --no-log        # sweep without appending
    python3 scripts/drift-sweep.py --json          # machine-readable
    python3 scripts/drift-sweep.py --alert-threshold 20   # exit 1 if fail% > 20
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PA_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PA_DIR / "scripts"))

import anchor_verify as av  # noqa: E402
import triage_anchors as ta  # noqa: E402

# memory-health-report.py is hyphenated, so it cannot be imported with a plain
# ``import``; pull the two functions we reuse off the module object.
_mh = __import__("memory-health-report")
tier_c_audit = _mh.tier_c_audit
load_records = _mh.load_records

MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
LOG_PATH = PA_DIR / "logs" / "drift-sweep.jsonl"

# An effectively-infinite trailing window, so ``tier_c_audit`` considers the
# whole anchored back-set rather than a trailing slice (~274 years of days).
FULL_BACKSET_DAYS = 100_000

# Default fail-rate alert threshold (per cent). The baseline is ~18 % (stable
# 2026-06-04 → 2026-06-06); 25 % gives headroom before alerting.
DEFAULT_ALERT_THRESHOLD = 25.0


def run_sweep(records: list[dict], *, as_of: datetime,
              days: int = FULL_BACKSET_DAYS) -> dict:
    """Re-resolve the anchored records and return the tier_c_audit result.

    Wires the same resolution callables the memory-health report uses; the
    only difference is ``days`` defaults to the full back-set. Scans the broad
    repo set once (working tree + git history of every relevant repo).
    """
    repos = ta.broad_repo_set()
    basename_index = ta.build_basename_index(repos)
    return tier_c_audit(
        records,
        as_of=as_of,
        days=days,
        verify=lambda rec: av.verify_memory(rec, repos),
        verify_file_ref=lambda ref: av.verify_file(ref, repos),
        recover=lambda ref: ta.recovery_status(ref, basename_index),
    )


def trend_line(result: dict, *, as_of: datetime) -> dict:
    """Flatten a tier_c_audit result into one trend record (pure; no I/O).

    Keys are stable so a downstream parser (weekly review / future plotting)
    can read the whole ``drift-sweep.jsonl`` history uniformly.
    """
    verdicts = result.get("verdicts", {})
    recovery = result.get("failing_file_ref_recovery", {})
    return {
        "run_at": as_of.isoformat(),
        "total_anchored": result.get("anchored_in_window", 0),
        "pass": verdicts.get("true", 0),
        "fail": result.get("fail_count", 0),
        "pending": verdicts.get("pending", 0),
        "no_valid_anchor": verdicts.get("no_valid_anchor", 0),
        "fail_pct": result.get("fail_rate_pct", 0.0),
        "absent": recovery.get("absent", 0),
        "recoverable": recovery.get("recoverable", 0),
        "ambiguous": recovery.get("ambiguous", 0),
    }


def append_trend(record: dict, *, log_path: Path = LOG_PATH) -> bool:
    """Append one trend record as a JSON line (best-effort; never raises)."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return True
    except Exception:  # noqa: BLE001 — instrumentation must never raise
        return False


def _render(record: dict) -> str:
    """A short human-readable summary of one sweep."""
    return (
        "# Anchor drift-sweep (item 8 — full back-set)\n\n"
        f"Anchored swept:   {record['total_anchored']}\n"
        f"Resolve (pass):   {record['pass']}\n"
        f"Fail:             {record['fail']}  ({record['fail_pct']} %)\n"
        f"Pending:          {record['pending']}\n"
        f"No valid anchor:  {record['no_valid_anchor']}\n"
        f"Failing file-ref split — absent {record['absent']} / "
        f"recoverable {record['recoverable']} / ambiguous {record['ambiguous']}"
    )


def main(argv: list[str] | None = None) -> int:
    """Sweep the full anchored back-set, append a trend line, alert on threshold."""
    parser = argparse.ArgumentParser(
        description="Re-resolve all anchored memories; log drift trend (item 8).",
    )
    parser.add_argument("--memories", type=Path, default=MEMORIES_FILE,
                        help="Path to memories.jsonl.")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH,
                        help="Trend log path (default data/logs/drift-sweep.jsonl).")
    parser.add_argument("--days", type=int, default=FULL_BACKSET_DAYS,
                        help="Trailing window in days (default: full back-set).")
    parser.add_argument("--alert-threshold", type=float,
                        default=DEFAULT_ALERT_THRESHOLD,
                        help="Exit 1 if fail%% exceeds this (default 25).")
    parser.add_argument("--no-log", action="store_true",
                        help="Run the sweep but do not append to the trend log.")
    parser.add_argument("--json", action="store_true",
                        help="Emit the trend record as JSON.")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    records = load_records(args.memories)
    result = run_sweep(records, as_of=now, days=args.days)
    record = trend_line(result, as_of=now)

    if not args.no_log:
        if not append_trend(record, log_path=args.log_path):
            print(f"[drift-sweep] WARN: could not append to {args.log_path}",
                  file=sys.stderr)

    print(json.dumps(record, indent=2) if args.json else _render(record))

    if record["fail_pct"] > args.alert_threshold:
        print(f"[drift-sweep] ALERT: fail rate {record['fail_pct']}% exceeds "
              f"threshold {args.alert_threshold}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
