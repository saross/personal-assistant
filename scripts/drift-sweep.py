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

Exit codes:
  0 — sweep completed, fail rate within the threshold, trend row appended
  1 — fail rate exceeds ``--alert-threshold``
  2 — the sweep could not be trusted or could not be recorded: the corpus
      was unreadable, repository discovery was empty or smaller than the
      floor, more than ``MAX_PENDING_PCT`` of records could not be checked,
      or the trend row could not be appended. No trend row is written in the
      unreliable cases. The repository floor comes from the last logged
      sweep and is overridden with ``--min-repos`` (see ``--help``).

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

# Above this share of ``pending`` verdicts the sweep is not measuring drift, it
# is measuring its own inability to check: an unmounted mount, a missing git
# binary, a locked index. Logging a trend row from such a run would put a
# fabricated spike in an append-only log for ever (audit 2026-09-08, AN3/AN7).
MAX_PENDING_PCT = 10.0


def run_sweep(records: list[dict], *, as_of: datetime,
              days: int = FULL_BACKSET_DAYS, min_repos: int = 0) -> dict:
    """Re-resolve the anchored records and return the tier_c_audit result.

    Wires the same resolution callables the memory-health report uses; the
    only difference is ``days`` defaults to the full back-set. Scans the broad
    repo set once (working tree + git history of every relevant repo).

    *min_repos* is a floor on the DISCOVERY-ONLY repository count. A run that
    discovers fewer repositories than that is probably running on a degraded
    machine — a different host, an unpopulated ``~/Code``, an unmounted volume
    — and every anchor in the missing repositories would resolve as absent, so
    it raises :class:`triage_anchors.RepoSetShrunk` rather than reporting a
    drift spike that is really a discovery failure (finding AN7). The returned
    dict carries ``repo_count`` so the next run can apply the same floor.

    The count deliberately EXCLUDES ``broad_repo_set``'s ``PA_DIR``
    augmentation. That augmentation depends on where the running copy lives —
    a worktree adds one repository, the main checkout adds none — so counting
    it would let a single sweep from a second checkout ratchet the floor above
    what the main checkout can ever reach, permanently bricking an append-only
    series that has no way back (finding C1). The floor is also an operator
    decision, not a law: ``--min-repos`` overrides it, and the refusal names
    the value to pass.
    """
    # Raises RepoSetUnavailable when DISCOVERY is empty — the augmented list
    # being non-empty is not a substitute (finding M-a).
    repos, discovered = ta.broad_repo_set_detail()
    if discovered < min_repos:
        raise ta.RepoSetShrunk(
            discovered, min_repos,
            f"re-run with --min-repos {discovered} if the set legitimately "
            "shrank (a repository archived or removed), or --min-repos 0 to "
            "drop the floor entirely",
        )
    # Start from a clean exclusion registry so the row below describes THIS
    # sweep, not one inherited from an earlier call in the same process.
    av.reset_unusable_repos()
    basename_index = ta.build_basename_index(repos)
    # Memoise both ref-level resolvers: verify_file walks every repository and
    # spawns up to two git processes per repository, and the same ref recurs
    # across many records. The key carries the resolver identity, so a file
    # ref and a commit ref that share text cannot share an answer (AN10).
    ref_memo: dict[tuple[str, str], object] = {}

    def _memoised(kind: str, fn):
        def call(ref: str):
            key = (kind, ref)
            if key not in ref_memo:
                ref_memo[key] = fn(ref)
            return ref_memo[key]
        return call

    result = tier_c_audit(
        records,
        as_of=as_of,
        days=days,
        verify=lambda rec: av.verify_memory(rec, repos),
        verify_file_ref=_memoised("file", lambda ref: av.verify_file(ref, repos)),
        recover=_memoised("recover", lambda ref: ta.recovery_status(
            ref, basename_index)),
    )
    # Discovery-only, for the reason in the docstring above.
    result["repo_count"] = discovered
    # Which repositories anchor resolution had to leave out. Until now the
    # only trace was one stderr WARN, which a cron run discards, while the
    # row recorded the full discovered count as though every repository had
    # answered (round 4f-4, finding M-b).
    result["unusable_repos"] = sorted(av.unusable_repos())
    return result


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
        # Recorded so the NEXT sweep can refuse to run against a smaller
        # repository set than this one saw (finding AN7).
        "repos": result.get("repo_count", 0),
        # Repositories resolution could not consult. A run with a non-empty
        # list resolved against fewer repositories than ``repos`` claims, and
        # a reader comparing rows needs to know that (finding M-b).
        "unusable": list(result.get("unusable_repos", [])),
    }


def last_repo_count(log_path: Path) -> int:
    """The repository count the most recent logged sweep recorded, else 0.

    Reads the append-only trend log backwards for the last line carrying a
    POSITIVE ``repos``. A missing, unreadable, or pre-``repos`` log yields 0,
    which imposes no floor — the guard can only tighten over time, never
    block a first run.

    Zero is skipped rather than accepted, so a degraded row already in the
    log (written before the guards in finding M-a) does not mask a real floor
    recorded before it. Accepting zero would also make the newest such row
    stop the scan and return "no floor at all".
    """
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        count = record.get("repos")
        if isinstance(count, int) and count > 0:
            return count
    return 0


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
    lines = [
        "# Anchor drift-sweep (item 8 — full back-set)\n",
        f"Anchored swept:   {record['total_anchored']}",
        f"Resolve (pass):   {record['pass']}",
        f"Fail:             {record['fail']}  ({record['fail_pct']} %)",
        f"Pending:          {record['pending']}",
        f"No valid anchor:  {record['no_valid_anchor']}",
        f"Failing file-ref split — absent {record['absent']} / "
        f"recoverable {record['recoverable']} / ambiguous {record['ambiguous']}",
    ]
    unusable = record.get("unusable") or []
    if unusable:
        lines.append(
            f"Repositories EXCLUDED ({len(unusable)}) — resolution could not "
            "consult these, so their anchors read pending:"
        )
        lines.extend(f"  - {path}" for path in unusable)
    return "\n".join(lines)


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
                        help=("Run the sweep but do not append to the trend "
                              "log. Also drops the repository floor: nothing "
                              "is being recorded, so nothing can be corrupted."))
    parser.add_argument("--min-repos", type=int, default=None,
                        help=("Minimum repositories discovery must find, "
                              "overriding the floor taken from the last "
                              "logged sweep. Pass the current count to reset "
                              "the floor after a repository is legitimately "
                              "archived or removed; pass 0 to disable it."))
    parser.add_argument("--json", action="store_true",
                        help="Emit the trend record as JSON.")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        records = load_records(args.memories)
    except OSError as exc:
        # Clean failure for a standing/cron run, rather than a bare traceback.
        print(f"[drift-sweep] ERROR: cannot read {args.memories}: {exc}",
              file=sys.stderr)
        return 2
    # Floor precedence: an explicit --min-repos wins; otherwise a run that
    # writes no trend row imposes none (there is no series to protect); and
    # otherwise the last logged sweep's discovery-only count.
    if args.min_repos is not None:
        floor, floor_source = args.min_repos, "--min-repos"
    elif args.no_log:
        floor, floor_source = 0, "--no-log (no floor)"
    else:
        floor, floor_source = last_repo_count(args.log_path), "the last logged sweep"
    try:
        result = run_sweep(records, as_of=now, days=args.days, min_repos=floor)
    except ta.RepoSetShrunk as exc:
        # Discovery WORKED and found less than the floor. Say what changed
        # before refusing, and name the override — an archived repository is
        # a legitimate reason for the set to shrink, and the operator must be
        # able to say so without editing an append-only log.
        # Name where the floor came from: telling an operator who just
        # passed --min-repos that the number came from the log sends them to
        # the wrong place (round 4f-4, finding L-d).
        print(f"[drift-sweep] WARN: discovery found {exc.discovered} "
              f"repositories; the floor of {exc.floor} came from "
              f"{floor_source}", file=sys.stderr)
        print(f"[drift-sweep] ERROR: sweep unreliable — {exc}; no trend row "
              "written", file=sys.stderr)
        return 2
    except ta.RepoSetUnavailable as exc:
        # Not a drift result: a discovery failure wearing one. Log nothing.
        print(f"[drift-sweep] ERROR: sweep unreliable — {exc}; no trend row "
              "written", file=sys.stderr)
        return 2
    record = trend_line(result, as_of=now)

    # A sweep dominated by "pending" verdicts measured our own inability to
    # check, not the corpus. Say so, and keep it out of the trend log.
    total = record["total_anchored"]
    pending_pct = round(100 * record["pending"] / total, 1) if total else 0.0
    if pending_pct > MAX_PENDING_PCT:
        print(f"[drift-sweep] ERROR: sweep unreliable — {pending_pct}% of "
              f"{total} anchored records could not be checked (limit "
              f"{MAX_PENDING_PCT}%); no trend row written", file=sys.stderr)
        print(json.dumps(record, indent=2) if args.json else _render(record))
        return 2

    # A row whose repository count is zero describes a sweep that resolved
    # against nothing. It cannot be compared with anything, and
    # last_repo_count deliberately skips it — so it would sit in the
    # append-only log as a permanent 100 %-failure artefact imposing no floor
    # (finding M-a). Belt to the discovery guard's braces: never write one.
    if record["repos"] <= 0:
        print("[drift-sweep] ERROR: sweep unreliable — resolved against no "
              "discovered repositories; no trend row written", file=sys.stderr)
        print(json.dumps(record, indent=2) if args.json else _render(record))
        return 2

    log_failed = False
    if not args.no_log:
        if not append_trend(record, log_path=args.log_path):
            print(f"[drift-sweep] ERROR: could not append to {args.log_path}",
                  file=sys.stderr)
            log_failed = True

    print(json.dumps(record, indent=2) if args.json else _render(record))

    if record["fail_pct"] > args.alert_threshold:
        print(f"[drift-sweep] ALERT: fail rate {record['fail_pct']}% exceeds "
              f"threshold {args.alert_threshold}%", file=sys.stderr)
        if log_failed:
            return 2
        return 1
    # A lost trend row is a failed run: the whole point of the sweep is the
    # week-over-week series, and a silent gap in it is invisible later
    # (finding AN18).
    return 2 if log_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
