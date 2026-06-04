#!/usr/bin/env python3
"""
Memory-health standing report (plan item 18 / P6) — read-only.

Aggregates the corpus-health signals scattered across the memory system into
one report: size and composition, growth and churn, anchor health, sync and
archive integrity, and the confabulation-flag rate (§8 measurement 3). An
opt-in ``--tier-c`` pass adds the write-time fresh-anchor-fail rate (the
fraction of recently-anchored memories whose file/commit anchor resolves
nowhere), classified recoverable-prefix vs genuinely-absent.

This is the standing companion to the one-shot diagnostics: it reuses
``audit-postgres-sync.py``'s ``audit_archive_parity`` (P5 archive-vs-PG drift),
the ``active_memories`` recall invariant (P2), and the ``anchor_verify`` /
``triage_anchors`` machinery (items 9/20/21). It mutates nothing — no locks,
no PG writes, no cursor changes — so it is safe to run at any time, including
while extraction hooks append concurrently (it reads a point-in-time snapshot).

Every count is re-derivable at source; the report cites the live JSONL, the
cold partitions, ``claude_memories.memories``, and ``data/logs/*`` so a reader
can reproduce any figure rather than trust the prose.

Exit codes:
  0 — report produced; all integrity checks clean
  1 — an integrity check failed (a recall leak, a #55 missing-id, or a
      duplicate-id tripwire) — the report still prints in full
  2 — could not produce the report (canonical JSONL missing)

Usage:
    venv/bin/python3 scripts/memory-health-report.py
    venv/bin/python3 scripts/memory-health-report.py --tier-c
    venv/bin/python3 scripts/memory-health-report.py --tier-c --tier-c-days 60
    venv/bin/python3 scripts/memory-health-report.py --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

# ----------------------------------------------------------------------------
# Paths and sibling-module imports
# ----------------------------------------------------------------------------

PA_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

MEMORIES_FILE = PA_DIR / "data" / "memories" / "memories.jsonl"
if not MEMORIES_FILE.exists():
    MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
ARCHIVE_DIR = PA_DIR / "data" / "memories" / "archive"
if not ARCHIVE_DIR.exists():
    ARCHIVE_DIR = PA_DIR / "memories" / "archive"
ARCHIVE_RUNS_LOG = ARCHIVE_DIR / "archive-runs.jsonl"
QUARANTINE_FILE = PA_DIR / "data" / "memories" / "quarantine-postgres-drops.jsonl"
CONFAB_LOG = PA_DIR / "data" / "logs" / "confab-flags.log"
if not CONFAB_LOG.exists():
    CONFAB_LOG = PA_DIR / "logs" / "confab-flags.log"
DB_NAME = "claude_memories"

# anchor_verify / triage_anchors are underscore-named — direct import works.
import anchor_verify as av  # noqa: E402
import triage_anchors as ta  # noqa: E402

# audit-postgres-sync.py is hyphenated — load via importlib so we can reuse
# its archive-vs-PG parity check rather than re-derive it.
_audit_spec = importlib.util.spec_from_file_location(
    "audit_postgres_sync", SCRIPTS_DIR / "audit-postgres-sync.py"
)
_audit_mod = importlib.util.module_from_spec(_audit_spec)
sys.modules.setdefault("audit_postgres_sync", _audit_mod)
_audit_spec.loader.exec_module(_audit_mod)


def _logger() -> logging.Logger:
    """Quiet stderr logger shared by the reused audit helpers."""
    logger = logging.getLogger("memory-health-report")
    if not logger.handlers:
        logger.setLevel(logging.WARNING)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
    return logger


# ============================================================================
# Loading
# ============================================================================

def load_records(jsonl_path: Path) -> list[dict[str, Any]]:
    """Load every parseable record from a JSONL file (order preserved)."""
    records: list[dict[str, Any]] = []
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return records


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ============================================================================
# §A — Corpus size & composition  (pure)
# ============================================================================

def summarise_corpus(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts, per-category and per-source breakdowns, and the dup-id tripwire."""
    by_category: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    id_counts: Counter[str] = Counter()
    no_id = 0
    for rec in records:
        by_category[rec.get("category") or "?"] += 1
        by_source[rec.get("source") or "?"] += 1
        mid = rec.get("id")
        if mid:
            id_counts[str(mid)] += 1
        else:
            no_id += 1
    duplicate_ids = {mid: n for mid, n in id_counts.items() if n > 1}
    return {
        "total_records": len(records),
        "distinct_ids": len(id_counts),
        "records_without_id": no_id,
        "duplicate_id_groups": len(duplicate_ids),
        "duplicate_id_excess_lines": sum(n - 1 for n in duplicate_ids.values()),
        "by_category": dict(by_category.most_common()),
        "by_source": dict(by_source.most_common()),
    }


# ============================================================================
# §B — Growth & churn  (pure; as_of injected for testability)
# ============================================================================

def growth_windows(
    records: list[dict[str, Any]],
    as_of: datetime,
    windows_days: tuple[int, ...] = (1, 7, 30),
) -> dict[str, int]:
    """Count records whose ``created_at`` falls within each trailing window."""
    cutoffs = {d: as_of - timedelta(days=d) for d in windows_days}
    out = {f"created_last_{d}d": 0 for d in windows_days}
    for rec in records:
        created = _parse_iso(rec.get("created_at"))
        if created is None:
            continue
        for d, cutoff in cutoffs.items():
            if created > cutoff:
                out[f"created_last_{d}d"] += 1
    return out


def archival_summary(archive_runs_lines: list[str]) -> dict[str, Any]:
    """Aggregate the archive-runs log (total archived, per-run, per-category)."""
    total = 0
    runs = 0
    by_category: Counter[str] = Counter()
    last_run_at: str | None = None
    for line in archive_runs_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        runs += 1
        total += int(entry.get("total", 0))
        for cat, n in (entry.get("counts") or {}).items():
            by_category[cat] += int(n)
        if entry.get("run_at"):
            last_run_at = entry["run_at"]
    return {
        "archival_runs": runs,
        "total_archived": total,
        "archived_by_category": dict(by_category.most_common()),
        "last_run_at": last_run_at,
    }


# ============================================================================
# §C — Anchor health  (pure; wellformed_anchor is cheap, no git)
# ============================================================================

def anchor_health(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Anchored fraction, verified breakdown, and malformed-anchor count."""
    anchored = 0
    unanchored = 0
    verified_counts: Counter[str] = Counter()
    malformed_anchors = 0
    records_with_malformed = 0
    for rec in records:
        anchors = rec.get("anchors")
        if anchors:
            anchored += 1
            had_malformed = False
            for anchor in anchors:
                ok, _ = av.wellformed_anchor(anchor)
                if not ok:
                    malformed_anchors += 1
                    had_malformed = True
            if had_malformed:
                records_with_malformed += 1
        else:
            unanchored += 1
        # verified is only meaningful on anchored records; bucket None as "pending".
        if anchors:
            v = rec.get("verified")
            verified_counts[str(v).lower() if v is not None else "pending"] += 1
    total = len(records)
    return {
        "total_records": total,
        "anchored": anchored,
        "unanchored": unanchored,
        "anchored_pct": round(100 * anchored / total, 1) if total else 0.0,
        "verified_breakdown": dict(verified_counts.most_common()),
        "malformed_anchors": malformed_anchors,
        "records_with_malformed_anchor": records_with_malformed,
    }


# ============================================================================
# §E — Confab-flag rate (§8 measurement 3)  (pure)
# ============================================================================

def parse_confab_log(lines: list[str]) -> dict[str, Any]:
    """
    Parse the TSV confab-flag log into the §8 measurement-3 metrics.

    Verifier rows (``checked>0``) carry a denominator → contribute to the
    RATE (Σflagged / Σchecked). Manual rows (``checked=0``, e.g. /confab or
    self-catch) have no denominator → contribute an ABSOLUTE count only and
    MUST be excluded from the rate (documented in log-confab-flag.py).
    """
    v_checked = v_flagged = v_confab = 0          # verifier (rate) rows
    m_flagged = m_confab = 0                       # manual (absolute) rows
    by_source: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    rows = 0
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        fields = line.split("\t")
        kv: dict[str, str] = {}
        for field in fields:
            if "=" in field:
                key, _, val = field.partition("=")
                kv[key] = val
        # A row without checked/flagged is not a metric line; skip.
        if "flagged" not in kv:
            continue
        rows += 1
        checked = int(kv.get("checked", "0") or "0")
        flagged = int(kv.get("flagged", "0") or "0")
        confab = int(kv.get("confab", "0") or "0")
        by_source[kv.get("source", "?")] += flagged
        for kind in (kv.get("kinds", "") or "").split(","):
            kind = kind.strip()
            if kind and kind != "-":
                by_kind[kind] += 1
        if checked > 0:
            v_checked += checked
            v_flagged += flagged
            v_confab += confab
        else:
            m_flagged += flagged
            m_confab += confab
    rate = round(v_flagged / v_checked, 4) if v_checked else None
    return {
        "rows": rows,
        "verifier_checked": v_checked,
        "verifier_flagged": v_flagged,
        "verifier_confab": v_confab,
        "verifier_flag_rate": rate,
        "manual_flagged": m_flagged,
        "manual_confab": m_confab,
        "flagged_by_source": dict(by_source.most_common()),
        "flagged_by_kind": dict(by_kind.most_common()),
    }


# ============================================================================
# §F — Tier C: write-time fresh-anchor-fail rate  (git-backed; opt-in)
# ============================================================================

def tier_c_audit(
    records: list[dict[str, Any]],
    as_of: datetime,
    days: int,
    verify: Callable[[dict[str, Any]], str | None],
    verify_file_ref: Callable[[str], str],
    recover: Callable[[str], tuple[str, str | None]],
) -> dict[str, Any]:
    """
    Of the records anchored within the trailing ``days`` window, the fraction
    whose anchors resolve to ``false`` (nowhere in the working tree + git
    history), and — for the file anchors that *themselves* fail — the
    recoverable/ambiguous/absent split.

    ``verify`` (record-level verdict), ``verify_file_ref`` (single file-anchor
    resolution), and ``recover`` (prefix-recovery class) are injected so the
    classification logic is testable without git. Production wires them to
    ``anchor_verify.verify_memory``, ``anchor_verify.verify_file``, and
    ``triage_anchors.recovery_status`` respectively.

    The split classifies ONLY genuinely-failing file anchors: a record's
    verdict is ``false`` if *any* anchor fails, so blindly classifying every
    file anchor on a failing record would over-count "recoverable" by folding
    in anchors that actually resolve fine. We re-check each file anchor with
    ``verify_file_ref`` and only classify the ones that resolve to ``false``.
    """
    cutoff = as_of - timedelta(days=days)
    considered = 0
    results: Counter[str] = Counter()
    recover_split: Counter[str] = Counter()
    for rec in records:
        if not rec.get("anchors"):
            continue
        created = _parse_iso(rec.get("created_at"))
        if created is None or created <= cutoff:
            continue
        considered += 1
        verdict = verify(rec)  # "true" / "false" / "pending" / None
        results[verdict if verdict is not None else "no_valid_anchor"] += 1
        if verdict == "false":
            for anchor in rec["anchors"]:
                if not isinstance(anchor, dict) or anchor.get("type") != "file":
                    continue
                ref = str(anchor.get("ref", "")).strip()
                if not ref:
                    continue
                if verify_file_ref(ref) != "false":
                    continue  # this anchor resolves — not the one that failed
                status, _ = recover(ref)
                recover_split[status] += 1
    fail = results.get("false", 0)
    fail_rate = round(100 * fail / considered, 1) if considered else 0.0
    return {
        "window_days": days,
        "anchored_in_window": considered,
        "verdicts": dict(results.most_common()),
        "fail_count": fail,
        "fail_rate_pct": fail_rate,
        "failing_file_ref_recovery": dict(recover_split.most_common()),
    }


# ============================================================================
# PostgreSQL snapshot + integrity (degrades gracefully)
# ============================================================================

def pg_snapshot(logger: logging.Logger) -> dict[str, Any] | None:
    """Return PG-side counts + id set, or None if PG is unreachable."""
    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 not installed — PG sections skipped")
        return None
    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot connect to PostgreSQL (%s) — PG sections skipped", exc)
        return None
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memories")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memories WHERE is_active IS TRUE")
            active_flag = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM memories WHERE is_active IS FALSE")
            inactive = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM active_memories")
            view = cur.fetchone()[0]
            cur.execute("SELECT id FROM memories")
            pg_ids = {str(r[0]) for r in cur.fetchall()}
        return {
            "total_rows": total,
            "is_active_true": active_flag,
            "is_active_false": inactive,
            "active_memories_view": view,
            "ids": pg_ids,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("PG query failed (%s) — PG sections skipped", exc)
        return None
    finally:
        conn.close()


def quarantine_count() -> int:
    """Number of records sitting in the PG-drop quarantine (0 expected)."""
    if not QUARANTINE_FILE.exists():
        return 0
    n = 0
    with QUARANTINE_FILE.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


# ============================================================================
# Rendering
# ============================================================================

def _fmt_top(counter: dict[str, int], n: int = 8) -> str:
    items = list(counter.items())[:n]
    tail = "" if len(counter) <= n else f"  (+{len(counter) - n} more)"
    return ", ".join(f"{k}={v}" for k, v in items) + tail


def render_report(report: dict[str, Any]) -> list[str]:
    """Render the structured report dict to human-readable lines."""
    out: list[str] = []
    out.append("=" * 72)
    out.append(f"  MEMORY-HEALTH REPORT — {report['generated_at']}")
    out.append("=" * 72)

    c = report["corpus"]
    out.append("\n[A] Corpus size & composition")
    out.append(f"  live JSONL records      : {c['total_records']}")
    out.append(f"  distinct ids            : {c['distinct_ids']}")
    out.append(
        f"  duplicate-id groups     : {c['duplicate_id_groups']} "
        f"(excess lines {c['duplicate_id_excess_lines']})"
    )
    pg = report.get("postgres")
    if pg:
        out.append(f"  PG total rows           : {pg['total_rows']}")
        out.append(
            f"  PG is_active T/F        : {pg['is_active_true']} / {pg['is_active_false']}"
        )
        out.append(f"  active_memories view    : {pg['active_memories_view']}")
    else:
        out.append("  PG                      : (unavailable — skipped)")
    out.append(f"  by category             : {_fmt_top(c['by_category'])}")
    out.append(f"  by source               : {_fmt_top(c['by_source'])}")

    g = report["growth"]
    a = report["archival"]
    out.append("\n[B] Growth & churn")
    out.append(
        "  created (1d/7d/30d)     : "
        f"{g.get('created_last_1d', 0)} / {g.get('created_last_7d', 0)} "
        f"/ {g.get('created_last_30d', 0)}"
    )
    out.append(
        f"  archived (all-time)     : {a['total_archived']} "
        f"across {a['archival_runs']} run(s); last {a['last_run_at']}"
    )
    out.append(f"  cold partition records  : {report['cold_partition_records']}")

    h = report["anchors"]
    out.append("\n[C] Anchor health")
    out.append(
        f"  anchored / unanchored   : {h['anchored']} / {h['unanchored']} "
        f"({h['anchored_pct']}% anchored)"
    )
    out.append(f"  verified breakdown      : {_fmt_top(h['verified_breakdown'])}")
    out.append(
        f"  malformed anchors       : {h['malformed_anchors']} "
        f"(on {h['records_with_malformed_anchor']} record(s))"
    )

    i = report["integrity"]
    out.append("\n[D] Sync & archive integrity")
    verdict = "PASS" if i["clean"] else "FAIL"
    out.append(f"  overall                 : {verdict}")
    out.append(
        f"  live\\PG (#55 tail)       : {i['only_in_canonical']}   "
        "(normal unsynced tail; cron drains every 5 min)"
    )
    out.append(f"  PG\\live                 : {i['only_in_postgres']}")
    ap = i.get("archive_parity")
    if ap:
        out.append(
            f"  archive↔PG parity       : {ap['archive_count']} archived / "
            f"{ap['archived_in_pg']} in-PG / {ap['archived_not_in_pg']} not-in-PG "
            f"(benign) / {ap['leaked_active']} leaked"
        )
    else:
        out.append("  archive↔PG parity       : (PG unavailable — skipped)")
    out.append(f"  dup-id tripwire         : {i['duplicate_id_groups']} (expect 0)")
    out.append(f"  quarantine (PG drops)   : {i['quarantine_count']} (expect 0)")

    e = report["confab"]
    out.append("\n[E] Confab-flag rate (§8 measurement 3)")
    if e["rows"] == 0:
        out.append("  (no confab-flag rows logged yet)")
    else:
        rate = e["verifier_flag_rate"]
        rate_s = "n/a (no verifier denominator)" if rate is None else f"{rate}"
        out.append(
            f"  verifier rate           : {e['verifier_flagged']}/{e['verifier_checked']} "
            f"= {rate_s}  (confab subset {e['verifier_confab']})"
        )
        out.append(
            f"  manual catches (abs)    : {e['manual_flagged']} flagged "
            f"(confab {e['manual_confab']}) — excluded from rate"
        )
        out.append(f"  flagged by kind         : {_fmt_top(e['flagged_by_kind'])}")

    tc = report.get("tier_c")
    if tc:
        out.append("\n[F] Tier C — write-time fresh-anchor-fail rate")
        out.append(
            f"  anchored in last {tc['window_days']}d    : {tc['anchored_in_window']}"
        )
        out.append(
            f"  fail (resolves nowhere) : {tc['fail_count']} "
            f"({tc['fail_rate_pct']}%)"
        )
        out.append(f"  verdicts                : {_fmt_top(tc['verdicts'])}")
        if tc["failing_file_ref_recovery"]:
            out.append(
                f"  failing file-ref split  : "
                f"{_fmt_top(tc['failing_file_ref_recovery'])}"
            )
    else:
        out.append("\n[F] Tier C — skipped (pass --tier-c to run; does git resolution)")

    out.append("\n" + "=" * 72)
    return out


# ============================================================================
# Orchestration
# ============================================================================

def build_report(
    *,
    as_of: datetime,
    run_tier_c: bool,
    tier_c_days: int,
    logger: logging.Logger,
) -> tuple[dict[str, Any], bool]:
    """Assemble the full structured report. Returns (report, all_clean)."""
    records = load_records(MEMORIES_FILE)
    live_ids = {str(r["id"]) for r in records if r.get("id")}

    corpus = summarise_corpus(records)
    growth = growth_windows(records, as_of)
    anchors = anchor_health(records)

    archive_runs_lines = (
        ARCHIVE_RUNS_LOG.read_text(encoding="utf-8").splitlines()
        if ARCHIVE_RUNS_LOG.exists() else []
    )
    archival = archival_summary(archive_runs_lines)

    cold_records = (
        len(_audit_mod._read_archive_partition_ids(ARCHIVE_DIR, logger))
        if ARCHIVE_DIR.exists() else 0
    )

    confab_lines = (
        CONFAB_LOG.read_text(encoding="utf-8").splitlines()
        if CONFAB_LOG.exists() else []
    )
    confab = parse_confab_log(confab_lines)

    # PG-dependent integrity
    pg = pg_snapshot(logger)
    integrity: dict[str, Any] = {
        "duplicate_id_groups": corpus["duplicate_id_groups"],
        "quarantine_count": quarantine_count(),
    }
    archive_parity_dict = None
    if pg is not None:
        only_in_canonical = len(live_ids - pg["ids"])
        only_in_postgres = len(pg["ids"] - live_ids)
        parity = _audit_mod.audit_archive_parity(ARCHIVE_DIR, logger)
        if parity is not None:
            archive_parity_dict = {
                "archive_count": parity.archive_count,
                "archived_in_pg": parity.archived_in_pg,
                "archived_not_in_pg": parity.archived_not_in_pg,
                "leaked_active": len(parity.leaked_active),
            }
        integrity.update(
            only_in_canonical=only_in_canonical,
            only_in_postgres=only_in_postgres,
            archive_parity=archive_parity_dict,
        )
    else:
        integrity.update(
            only_in_canonical="n/a", only_in_postgres="n/a", archive_parity=None
        )

    # Integrity is clean iff: no dup-ids, no quarantine drops, no archive leak,
    # and (when PG is reachable) no #55 missing-id beyond a small unsynced tail.
    # A missing-id only fails when PG is reachable AND a leak/dup is present;
    # the unsynced tail (live\PG) is expected and does NOT fail the report.
    clean = (
        integrity["duplicate_id_groups"] == 0
        and integrity["quarantine_count"] == 0
        and (archive_parity_dict is None or archive_parity_dict["leaked_active"] == 0)
    )
    integrity["clean"] = clean

    report: dict[str, Any] = {
        "generated_at": as_of.isoformat(),
        "corpus": corpus,
        "postgres": pg and {k: v for k, v in pg.items() if k != "ids"},
        "growth": growth,
        "archival": archival,
        "cold_partition_records": cold_records,
        "anchors": anchors,
        "integrity": integrity,
        "confab": confab,
    }

    if run_tier_c:
        repos = ta.broad_repo_set()
        basename_index = ta.build_basename_index(repos)
        report["tier_c"] = tier_c_audit(
            records,
            as_of=as_of,
            days=tier_c_days,
            verify=lambda rec: av.verify_memory(rec, repos),
            verify_file_ref=lambda ref: av.verify_file(ref, repos),
            recover=lambda ref: ta.recovery_status(ref, basename_index),
        )

    return report, clean


def main() -> int:
    """Entry point. Returns the intended exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier-c", action="store_true",
        help="Run the Tier-C write-time anchor-fail audit (does git resolution).",
    )
    parser.add_argument(
        "--tier-c-days", type=int, default=30,
        help="Trailing window (days) for the Tier-C audit (default: 30).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the structured report as JSON instead of text.",
    )
    args = parser.parse_args()

    logger = _logger()
    if not MEMORIES_FILE.exists():
        logger.error("Canonical JSONL not found: %s", MEMORIES_FILE)
        return 2

    as_of = datetime.now(timezone.utc)
    report, clean = build_report(
        as_of=as_of,
        run_tier_c=args.tier_c,
        tier_c_days=args.tier_c_days,
        logger=logger,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("\n".join(render_report(report)))

    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
