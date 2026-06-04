#!/usr/bin/env python3
"""monthly-archive.py — recurring archival cadence (write-path item 13 / P2).

The item-13 sweep (2026-06-02) was one-shot. At ~260 writes/day plus
multi-machine sync reconciliation, past-decay records re-accumulate in the
hot ``memories.jsonl`` continuously (a dry-run hours after the 7,673-record
sweep already found 46 fresh candidates), so without a recurring sweep the
corpus re-bloats. This wraps the *proven, Shawn-watched* item-13 procedure
into a single safe command for a monthly cron.

Sequence (apply mode):

  preflight    — refuse to run unless ``venv`` and the populated ``data``
                 submodule are present (i.e. running from the MAIN checkout,
                 not a git worktree — ``archive-memories.py`` mutates the
                 main tree's submodule regardless of where this lives).
  1. flush     — ``daily-sync.sh`` commits/pulls/pushes pending appends and
                 clears the dirty-protected-files state the bulk guard blocks
                 on (the item-13 run needed this first).
  2. sync PG   — ``sync-to-postgres.py`` so PG reflects the flushed JSONL
                 (item-22 self-heals the cursor on the shrink the apply causes).
  3. dry-run   — ``archive-memories.py`` (no --apply); SANITY-gate the count
                 (refuse an absurd/oversized sweep — a corrupt config must not
                 nuke the corpus).
  4. snapshot  — record the current monthly partition's record ids, so the
                 records THIS run archives can be isolated afterwards.
  5. apply     — ``archive-memories.py --apply`` (rewrites JSONL, appends the
                 monthly partition, sets PG ``is_active=FALSE``, commits the
                 data submodule).
  6. INVARIANCE— independently verify EVERY archived record is genuinely
                 past-decay at a single pinned ``as_of`` (a different code path
                 from the tool, immune to live-``NOW()`` drift). Any in-window,
                 permanent-category, or unparseable record ⇒ recall regression
                 ⇒ HALT before push (the data commit is local + revertable).
  7. PG drift  — confirm the archived ids now read ``is_active=FALSE`` in PG;
                 if PG was unreachable during the apply they would not, and the
                 tool exits 0 anyway — HALT rather than push on known drift.
  8. re-sync   — ``sync-to-postgres.py``.
  9. push      — ``daily-sync.sh``; then VERIFY the data submodule is level with
                 upstream and, if daily-sync left the archival commit unpushed
                 (it skips the data push on a clean tree), ``git -C data push`` it
                 directly so an unattended cron run is self-contained.

Mutual exclusion: the corpus rewrite is serialised by the bulk-rewrite guard
(``daily-sync.lock``) and a JSONL flock taken INSIDE ``archive-memories.py``;
the 5-minute sync cron serialises on a PG advisory lock. This wrapper's own
flock only prevents two ``monthly-archive`` runs from overlapping.

Safe by default: with no ``--apply`` the wrapper performs NO mutation.

Usage:
    python3 scripts/monthly-archive.py              # dry-run: report only
    python3 scripts/monthly-archive.py --apply      # the full guarded sweep
    python3 scripts/monthly-archive.py --apply --no-push   # apply, skip push

NOTE: run from the MAIN checkout (``~/personal-assistant``), never a worktree.
Its first ``--apply`` must be Shawn-watched (per the item-13 protocol); only
cron-enable it after a watched run validates it.

Exit codes:
    0  success (incl. dry-run, and apply with nothing to archive)
    1  another monthly-archive instance holds the lock
    2  preflight or a prerequisite step (flush / sync / dry-run) failed
    3  the dry-run SANITY gate refused the sweep (aborted before mutating)
    4  the INVARIANCE gate failed AFTER apply — recall regression; needs a human
    5  the apply itself crashed — corpus may be partially mutated; needs a human
    6  PG drift after apply (is_active not flipped) — do not trust PG; needs a human
    7  uncaught exception (possibly after a committed apply) — verify state by hand

Known limitation: the invariance gate verifies the records this run *appended*
to the cold partition. In the rare case where a partial prior run left a
past-decay record's id already in the partition, the tool evicts it from the
hot corpus without re-appending (idempotent dedup), so that one eviction is not
re-verified here — but evicting a genuinely past-decay record is the correct
outcome, so this fails safe.
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PA_DIR = Path(__file__).resolve().parent.parent
VENV_PY = PA_DIR / "venv" / "bin" / "python3"
ARCHIVE_TOOL = PA_DIR / "scripts" / "archive-memories.py"
DAILY_SYNC = PA_DIR / "scripts" / "daily-sync.sh"
SYNC_PG = PA_DIR / "scripts" / "sync-to-postgres.py"
DATA_DIR = PA_DIR / "data"
CORPUS = DATA_DIR / "memories" / "memories.jsonl"
ARCHIVE_GLOB = str(DATA_DIR / "memories" / "archive" / "memories-archive-*.jsonl")
LOCK_PATH = PA_DIR / "logs" / "monthly-archive.lock"
LOG_PATH = PA_DIR / "logs" / "monthly-archive.log"
DB_NAME = "claude_memories"

# Categories that are NEVER archived (guidance-bearing) — mirrors
# archive-memories.py PERMANENT_OVERRIDES. If one of these is ever in the
# archived set, that is itself a regression.
PERMANENT_CATEGORIES = {"gotcha", "pattern"}

# Dry-run sanity gate: never let a corrupt category_config or a logic error
# auto-archive an absurd amount. Either bound trips the gate.
SANITY_ABS_CAP = 10_000  # absolute ceiling on records archived in one run
SANITY_FRACTION_CAP = 0.25  # nor more than this fraction of the active corpus

# Module-level lock handle: keeping the flock fd referenced for the whole
# process lifetime is what holds the lock (LOW-1 — make it structural, not
# incidental to a local's scope).
_LOCK_FH = None


# ===========================================================================
# Pure, testable helpers
# ===========================================================================


def parse_category_counts(psql_out: str) -> dict[str, int]:
    """Parse ``category|count`` lines (psql ``-t -A -F'|'``) into a dict."""
    counts: dict[str, int] = {}
    for line in psql_out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cat, _, num = line.rpartition("|")
        try:
            counts[cat.strip()] = int(num.strip())
        except ValueError:
            continue
    return counts


def parse_category_config(psql_out: str) -> dict[str, int | None]:
    """Parse ``category|decay_days`` rows; an empty/NULL decay_days → ``None``."""
    config: dict[str, int | None] = {}
    for line in psql_out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cat, _, days = line.rpartition("|")
        cat, days = cat.strip(), days.strip()
        if not cat:
            continue
        if days == "":
            config[cat] = None
        else:
            try:
                config[cat] = int(days)
            except ValueError:
                continue
    return config


def parse_archive_count(report: str) -> int | None:
    """Extract the ``Records to archive: **N**`` count from a report.

    Returns ``None`` if the marker is absent (caller treats that as a failure,
    never as "zero to archive").
    """
    m = re.search(r"Records to archive:\s*\*\*(\d+)\*\*", report)
    return int(m.group(1)) if m else None


def parse_partition_path(stderr: str) -> str | None:
    """Extract the partition path from ``archived N records → <path>``."""
    m = re.search(r"archived\s+\d+\s+records\s+→\s+(\S+)", stderr)
    return m.group(1) if m else None


def parse_jsonl_records(text: str) -> list[dict]:
    """Parse JSONL text into a list of dict records (skips blank/bad lines)."""
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def sanity_verdict(n_archive: int, total_active: int) -> tuple[bool, str]:
    """Decide whether a proposed archive count is safe to apply.

    Refuses a negative count, a count above the absolute cap, or a count
    exceeding the fraction cap of the active corpus. ``n_archive == 0`` is
    allowed (caller treats it as nothing-to-do).
    """
    if n_archive < 0:
        return False, f"negative archive count {n_archive}"
    if n_archive > SANITY_ABS_CAP:
        return False, f"{n_archive} exceeds absolute cap {SANITY_ABS_CAP}"
    if total_active > 0 and (n_archive / total_active) > SANITY_FRACTION_CAP:
        pct = 100 * n_archive / total_active
        return False, (
            f"{n_archive} is {pct:.1f}% of {total_active} active "
            f"(cap {SANITY_FRACTION_CAP:.0%})"
        )
    return True, f"{n_archive} within sanity bounds"


def record_age_days(record: dict, as_of: datetime) -> float | None:
    """Age of a record in days at ``as_of`` (matches the active_memories view).

    Standard categories age from ``created_at``; ``commitment`` ages from
    ``COALESCE(deadline_at, created_at)``. Returns ``None`` if the relevant
    timestamp is missing or unparseable (caller treats that as un-verifiable
    ⇒ a regression, never as "safe").
    """
    field = "created_at"
    if record.get("category") == "commitment" and record.get("deadline_at"):
        field = "deadline_at"
    raw = record.get(field)
    if not raw:
        return None
    # Mirror archive-memories.py's parse_iso: normalise a trailing Z so the two
    # code paths parse identically on every interpreter (native Z support is
    # Python 3.11+; the corpus contains Z-stamped timestamps).
    raw = str(raw).replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (as_of - ts).total_seconds() / 86400.0


def verify_all_past_decay(
    archived: list[dict],
    decay_days: dict[str, int | None],
    as_of: datetime,
    permanent: set[str] = PERMANENT_CATEGORIES,
) -> tuple[bool, list[str]]:
    """Recall-invariance gate: confirm every archived record was archivable.

    Independently re-derives the decay decision (a DIFFERENT code path from
    ``archive-memories.py``) at a single pinned ``as_of`` — so it is immune to
    the live-``NOW()`` drift that broke the aggregate-count approach, and it
    inspects the ACTUAL archived records (closing the false-pass hole where a
    boundary error left the view counts unchanged).

    A record is a violation (recall regression) if it is in a permanent
    category, in a no-decay (``decay_days IS NULL``) category, has an
    unparseable/missing age, or is NOT strictly past its decay window
    (``age_days > decay_days``). Returns ``(ok, offenders)`` where offenders
    is a list of ``"<id>: <reason>"`` strings.
    """
    offenders: list[str] = []
    for r in archived:
        rid = str(r.get("id", "<no-id>"))
        cat = r.get("category", "<no-category>")
        if cat in permanent:
            offenders.append(f"{rid}: permanent category '{cat}' archived")
            continue
        dd = decay_days.get(cat)
        if dd is None:
            offenders.append(f"{rid}: no-decay category '{cat}' archived")
            continue
        age = record_age_days(r, as_of)
        if age is None:
            offenders.append(f"{rid}: unparseable/missing age (category '{cat}')")
            continue
        if not (age > dd):
            offenders.append(f"{rid}: age {age:.2f}d not past decay {dd}d (category '{cat}')")
    return (not offenders), offenders


# ===========================================================================
# Orchestration (subprocess + PG driven; logic lives in the pure helpers)
# ===========================================================================


def _log(msg: str) -> None:
    """Append a timestamped line to the cadence log and echo to stderr."""
    stamp = datetime.now(timezone.utc).isoformat()
    line = f"{stamp}\t{msg}"
    print(line, file=sys.stderr)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 — logging must never abort a run
        pass


def _preflight() -> str | None:
    """Return an error message if the environment is unsafe to run in, else None.

    The wrapped tool (``archive-memories.py``) hard-codes the MAIN tree's
    corpus, so this wrapper MUST run from the main checkout — otherwise its
    lock/log/snapshot paths resolve into a different tree than the one being
    mutated, silently breaking mutual exclusion. Pin to the main root, don't
    merely check that *some* corpus/venv exists.
    """
    main_root = (Path.home() / "personal-assistant").resolve()
    if PA_DIR.resolve() != main_root:
        return (f"running from {PA_DIR} but the corpus tool always operates on "
                f"{main_root} — run monthly-archive.py from the MAIN checkout, "
                "never a worktree or copy")
    if not VENV_PY.exists():
        return f"venv python missing at {VENV_PY}"
    if not CORPUS.exists():
        return f"corpus missing at {CORPUS} — data submodule not populated"
    return None


def _run(cmd: list[str], *, label: str) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing output; log its label and exit code."""
    _log(f"RUN {label}: {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    _log(f"  -> {label} exit={proc.returncode}")
    return proc


def _psql(sql: str) -> str:
    """Run a read-only query via psql and return stdout (raises on failure)."""
    proc = _run(
        ["psql", "-d", DB_NAME, "-t", "-A", "-F", "|", "-c", sql],
        label="psql",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed: {proc.stderr.strip()}")
    return proc.stdout


def _pg_active_category_counts() -> dict[str, int]:
    return parse_category_counts(
        _psql("SELECT category, COUNT(*) FROM active_memories GROUP BY category ORDER BY category")
    )


def _pg_category_config() -> dict[str, int | None]:
    return parse_category_config(_psql("SELECT category, decay_days FROM category_config"))


def _pg_still_active_count(ids: list[str]) -> int:
    """How many of *ids* still read is_active=TRUE in PG (drift detector)."""
    if not ids:
        return 0
    # Build a SQL array literal of single-quoted ids; ids are app-generated
    # ``YYYY-MM-DD-<hex>`` slugs (no quotes), but escape defensively anyway.
    arr = ",".join("'" + i.replace("'", "''") + "'" for i in ids)
    out = _psql(f"SELECT COUNT(*) FROM memories WHERE is_active=TRUE AND id IN ({arr})")
    try:
        return int(out.strip().splitlines()[0])
    except (ValueError, IndexError):
        raise RuntimeError("could not parse is_active drift count")


def _partition_record_ids(path: str) -> set[str]:
    """Ids currently in a partition file (empty set if it does not exist)."""
    p = Path(path)
    if not p.exists():
        return set()
    return {str(r["id"]) for r in parse_jsonl_records(p.read_text(encoding="utf-8"))
            if r.get("id")}


def _snapshot_partition_ids() -> dict[str, set[str]]:
    """Map each existing archive partition to its current id-set (pre-apply)."""
    return {path: _partition_record_ids(path) for path in glob.glob(ARCHIVE_GLOB)}


def _archived_records_since(partition_path: str, before_ids: set[str]) -> list[dict]:
    """Records in *partition_path* whose id was not present before the apply."""
    p = Path(partition_path)
    if not p.exists():
        return []
    return [r for r in parse_jsonl_records(p.read_text(encoding="utf-8"))
            if str(r.get("id", "")) not in before_ids]


def _archive_dryrun_count(category: str | None) -> int | None:
    cmd = [str(VENV_PY), str(ARCHIVE_TOOL)]
    if category:
        cmd += ["--category", category]
    proc = _run(cmd, label="archive dry-run")
    if proc.returncode != 0:
        _log(f"  dry-run stderr: {proc.stderr.strip()[:400]}")
        return None
    return parse_archive_count(proc.stdout)


def _data_submodule_ahead() -> int | None:
    """Commits the data submodule is ahead of its upstream (None if unknown)."""
    proc = _run(["git", "-C", str(DATA_DIR), "rev-list", "--count", "@{u}..HEAD"],
                label="data ahead-count")
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def _dry_run(category: str | None) -> int:
    """Read-only path: report the plan + sanity verdict, mutate nothing."""
    try:
        active = _pg_active_category_counts()
    except RuntimeError as exc:
        _log(f"WARN could not read active_memories ({exc}); reporting tool-only")
        active = {}
    total_active = sum(active.values())
    n = _archive_dryrun_count(category)
    if n is None:
        _log("dry-run FAILED to produce a count — see log")
        return 2
    ok, why = sanity_verdict(n, total_active)
    _log(f"DRY-RUN: would archive {n} record(s); active={total_active}; "
         f"sanity={'OK' if ok else 'FAIL'} ({why})")
    _log("dry-run only — no changes made. Re-run with --apply (Shawn-watched first time).")
    return 0


def _apply(category: str | None, no_push: bool) -> int:
    """Mutating path: the full guarded sweep. See the module docstring."""
    # 1. flush
    if _run(["bash", str(DAILY_SYNC)], label="flush (daily-sync)").returncode != 0:
        _log("flush failed — aborting before any archive")
        return 2
    # 2. sync PG
    if _run([str(VENV_PY), str(SYNC_PG)], label="sync PG (pre)").returncode != 0:
        _log("pre-apply PG sync failed — aborting")
        return 2
    # config + active total for the sanity gate
    try:
        decay_days = _pg_category_config()
        total_active = sum(_pg_active_category_counts().values())
    except RuntimeError as exc:
        _log(f"could not read PG config/active ({exc}) — aborting")
        return 2
    # 3. dry-run + sanity gate
    n = _archive_dryrun_count(category)
    if n is None:
        _log("dry-run failed pre-apply — aborting")
        return 2
    if n == 0:
        _log("nothing past decay to archive — clean no-op")
        return 0
    ok, why = sanity_verdict(n, total_active)
    if not ok:
        _log(f"SANITY GATE TRIPPED ({why}) — refusing to apply. Investigate category_config.")
        return 3
    _log(f"sanity OK ({why}); applying")
    # 4. snapshot partitions (to isolate what THIS run archives)
    before = _snapshot_partition_ids()
    # Pin the invariance reference IMMEDIATELY before the apply, so as_of is at
    # or just before the tool's own decision time. as_of <= tool_now means the
    # gate can only ever be *stricter* than the tool (a borderline record reads
    # as "not yet past decay" here) — i.e. a boundary mismatch fails as a HALT
    # before push (safe + revertable), never as a false pass that archives a
    # still-recallable record. The window is now sub-second.
    as_of = datetime.now(timezone.utc)
    # 5. apply
    apply_cmd = [str(VENV_PY), str(ARCHIVE_TOOL), "--apply"]
    if category:
        apply_cmd += ["--category", category]
    proc = _run(apply_cmd, label="archive --apply")
    if proc.returncode != 0:
        _log("APPLY FAILED — corpus may be partially mutated; do NOT push. Investigate.")
        return 5
    partition = parse_partition_path(proc.stderr)
    if not partition:
        # The tool legitimately archives nothing if its in-lock re-read finds the
        # candidates already gone (synced away between the dry-run and the apply);
        # it prints "nothing to archive" and exits 0 with no partition line. That
        # is a clean no-op, NOT an invariance failure.
        if "nothing to archive" in proc.stderr.lower():
            _log("apply found nothing to archive at lock time — clean no-op")
            return 0
        _log("could not determine the partition the apply wrote — HALT before push")
        return 4
    archived = _archived_records_since(partition, before.get(partition, set()))
    archived_ids = [str(r["id"]) for r in archived if r.get("id")]
    _log(f"apply wrote {len(archived)} new record(s) to {partition}")
    # post-apply sanity re-check against REALITY (MED-2): the apply count can
    # differ from the dry-run estimate; re-gate it before trusting/pushing.
    ok, why = sanity_verdict(len(archived), total_active)
    if not ok:
        _log(f"POST-APPLY SANITY FAIL ({why}) — HALT before push; investigate.")
        return 4
    # 6. INVARIANCE gate — every archived record genuinely past-decay at as_of
    inv_ok, offenders = verify_all_past_decay(archived, decay_days, as_of)
    if not inv_ok:
        _log(f"INVARIANCE GATE FAILED — {len(offenders)} record(s) should not have "
             f"been archived: {offenders[:10]}")
        _log("HALTING before push. The archival commit is local in the data submodule; "
             "review and `git -C data revert` if it is a real regression.")
        return 4
    _log(f"INVARIANCE OK: all {len(archived)} archived records verified past-decay at {as_of.isoformat()}")
    # 7. PG-drift gate — archived ids must now read is_active=FALSE
    try:
        still_active = _pg_still_active_count(archived_ids)
    except RuntimeError as exc:
        _log(f"could not check PG drift ({exc}) — HALT before push")
        return 6
    if still_active:
        _log(f"PG DRIFT: {still_active} archived id(s) still is_active=TRUE in PG "
             "(was PG unreachable during apply?) — HALT before push; reconcile PG.")
        return 6
    _log("PG drift check OK: archived ids are is_active=FALSE")
    # 8. re-sync PG (item-22 self-heals the shrunk cursor)
    _run([str(VENV_PY), str(SYNC_PG)], label="sync PG (post)")
    # 9. push + verify it landed
    if no_push:
        _log("--no-push: archival committed locally in data submodule, not pushed")
    else:
        _run(["bash", str(DAILY_SYNC)], label="push (daily-sync)")
        ahead = _data_submodule_ahead()
        if ahead is None:
            _log("WARN could not verify the data submodule push (no upstream?) — check manually")
        elif ahead > 0:
            # daily-sync only pushes the data submodule after committing dirty
            # changes; the archival commit is already clean-committed by the
            # tool, so daily-sync leaves it unpushed (verified live 2026-06-04).
            # Push it directly so an unattended cron run is self-contained.
            _log(f"data submodule {ahead} commit(s) ahead after daily-sync — pushing directly")
            _run(["git", "-C", str(DATA_DIR), "push"], label="push data submodule")
            ahead = _data_submodule_ahead()
            if ahead and ahead > 0:
                _log(f"WARN data submodule STILL {ahead} ahead after a direct push — the "
                     "archival is committed locally and durable, but the remote did not "
                     "accept it (behind upstream / push rejected?); the next sync will retry. "
                     "Investigate `git -C data status`.")
            else:
                _log("push verified: data submodule level with upstream (direct push)")
        else:
            _log("push verified: data submodule level with upstream")
    _log(f"DONE: archived {len(archived)} record(s); recall invariant held")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Drive the guarded cadence; see the module docstring for the sequence."""
    global _LOCK_FH
    ap = argparse.ArgumentParser(description="Recurring archival cadence (item 13 / P2).")
    ap.add_argument("--apply", action="store_true",
                    help="Actually mutate (default: dry-run report only).")
    ap.add_argument("--category", default=None,
                    help="Restrict to one category (passed through to the tool).")
    ap.add_argument("--no-push", action="store_true",
                    help="In apply mode, skip the final daily-sync push.")
    args = ap.parse_args(argv)

    err = _preflight()
    if err:
        _log(f"PREFLIGHT FAILED: {err}")
        return 2

    # Single-instance lock, held for the whole process via a module global.
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_FH = LOCK_PATH.open("w")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _log("another monthly-archive instance holds the lock — exiting")
        return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    _log(f"=== monthly-archive start ({mode}) ===")
    try:
        rc = _apply(args.category, args.no_push) if args.apply else _dry_run(args.category)
    except Exception as exc:  # noqa: BLE001 — always end cleanly with a marker
        _log(f"UNCAUGHT EXCEPTION: {exc!r} — if this fired AFTER the apply, the "
             "archival may be committed locally in the data submodule; verify the "
             "corpus and `git -C data log` before assuming the sweep failed.")
        rc = 7
    _log(f"=== monthly-archive end ({mode}, rc={rc}) ===")
    return rc


if __name__ == "__main__":
    sys.exit(main())
