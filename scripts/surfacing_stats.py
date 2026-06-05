#!/usr/bin/env python3
"""Aggregate ``surfaced.log`` into per-memory earned-utility stats (read-only).

Stage 1 reader for the earned-utility value signal (item 16;
``wiki/planning/earned-utility-value-signal-proposal.md``). Reads the
append-only log written by ``surfacing_log.py`` and produces, per memory
ID:

- ``active_retrievals`` — count of ``fetch`` + ``recall`` lines. The
  intent-driven signal: the model or Shawn *chose* to fetch this memory.
- ``digest_exposures`` — count of ``digest`` lines. Passive exposure,
  drawn only from the verified-true pool, so it largely re-derives the
  anchor signal (proposal §3.2) — reported separately and weighted below
  active retrieval, never pooled with it.
- ``last_active_at`` — most recent ``fetch``/``recall`` timestamp (the
  stay-of-execution clock for the eventual Stage-2 archival override).
- ``last_any_at`` — most recent timestamp on any path.

**This module mutates nothing** — no locks, no PostgreSQL writes, no
record changes — so it is safe to run during concurrent extraction, the
same posture as ``memory-health-report.py``. The consuming
"stay-of-execution on archival" logic is deferred to Stage 2 (the
proposal §5); this reader only makes the accruing log legible.

It is importable (``aggregate_surfacing``) so the memory-health report can
fold in a surfacing section later without duplicating the parser.

Usage:
    python3 scripts/surfacing_stats.py                # human summary
    python3 scripts/surfacing_stats.py --top 20       # top-N most retrieved
    python3 scripts/surfacing_stats.py --json         # machine output
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

PA_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = PA_DIR / "logs" / "surfaced.log"

# Paths that count as *active* (intent-driven) retrieval, as opposed to
# passive ``digest`` exposure. Kept as a set so the weighting is explicit
# and testable rather than buried in a string comparison.
ACTIVE_PATHS = frozenset({"fetch", "recall"})


def parse_surfacing_line(line: str) -> dict | None:
    """Parse one ``surfaced.log`` line into a dict (pure; tolerant).

    Returns ``{"timestamp", "id", "path", "rank", "session"}`` or ``None``
    if the line is blank or lacks the required ``id``/``path`` fields. A
    malformed line is skipped rather than raised on — the log is
    append-only operational data, and a single bad line must never abort
    an aggregation over months of history.
    """
    line = line.strip()
    if not line:
        return None
    parts = line.split("\t")
    if not parts:
        return None
    record: dict[str, str] = {"timestamp": parts[0]}
    for field in parts[1:]:
        key, sep, value = field.partition("=")
        if sep:
            record[key] = value
    # ``id`` and ``path`` are the minimum needed to attribute a surfacing.
    if "id" not in record or "path" not in record:
        return None
    return record


def aggregate_surfacing(source: Iterable[str] | Path) -> dict[str, dict]:
    """Aggregate surfacing lines into per-memory stats (pure over input).

    ``source`` may be an iterable of raw log lines or a ``Path`` to read.
    A missing log path yields an empty result (the log is created lazily
    on the first surfacing, so its absence is normal pre-accrual).
    """
    if isinstance(source, Path):
        try:
            lines: Iterable[str] = source.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
    else:
        lines = source

    # Timestamps are compared as strings: ``surfacing_log`` always emits
    # ``datetime.now(timezone.utc).isoformat()`` (fixed UTC ``+00:00``
    # offset), for which lexical order equals chronological order. This
    # holds only because the writer's format is uniform — it is not a
    # general ISO-8601 comparison.
    stats: dict[str, dict] = {}
    for raw in lines:
        rec = parse_surfacing_line(raw)
        if rec is None:
            continue
        mem_id = rec["id"]
        path = rec["path"]
        ts = rec["timestamp"]
        entry = stats.setdefault(
            mem_id,
            {
                "active_retrievals": 0,
                "digest_exposures": 0,
                "last_active_at": None,
                "last_any_at": None,
            },
        )
        if path in ACTIVE_PATHS:
            entry["active_retrievals"] += 1
            if entry["last_active_at"] is None or ts > entry["last_active_at"]:
                entry["last_active_at"] = ts
        elif path == "digest":
            entry["digest_exposures"] += 1
        # ``last_any_at`` tracks the most recent surfacing on *any* path.
        if entry["last_any_at"] is None or ts > entry["last_any_at"]:
            entry["last_any_at"] = ts
    return stats


def summarise(stats: dict[str, dict]) -> dict:
    """Roll per-memory stats up into corpus-level totals (pure)."""
    total_active = sum(s["active_retrievals"] for s in stats.values())
    total_digest = sum(s["digest_exposures"] for s in stats.values())
    ever_active = sum(1 for s in stats.values() if s["active_retrievals"] > 0)
    return {
        "distinct_memories_surfaced": len(stats),
        "memories_ever_actively_retrieved": ever_active,
        "total_active_retrievals": total_active,
        "total_digest_exposures": total_digest,
    }


def _render_human(stats: dict[str, dict], top: int) -> str:
    """Render a short human-readable summary + top-N actively-retrieved."""
    summary = summarise(stats)
    lines = [
        "# Memory surfacing — earned-utility stats (item 16, Stage 1)",
        "",
        f"Distinct memories surfaced:        {summary['distinct_memories_surfaced']}",
        f"Ever actively retrieved (fetch/recall): "
        f"{summary['memories_ever_actively_retrieved']}",
        f"Total active retrievals:           {summary['total_active_retrievals']}",
        f"Total digest exposures (passive):  {summary['total_digest_exposures']}",
        "",
        "NOTE: this measures earned *retrieval* (a memory was returned), a "
        "proxy — not earned *use* (it informed the response). Active "
        "retrieval is weighted above passive digest exposure, which is "
        "drawn only from the verified-true pool.",
    ]
    # Rank by active retrievals first (the value signal), then by digest
    # exposure as a tiebreak, then recency.
    ranked = sorted(
        stats.items(),
        key=lambda kv: (
            kv[1]["active_retrievals"],
            kv[1]["digest_exposures"],
            kv[1]["last_any_at"] or "",
        ),
        reverse=True,
    )
    if ranked:
        lines += ["", f"## Top {min(top, len(ranked))} most actively retrieved", ""]
        for mem_id, s in ranked[:top]:
            lines.append(
                f"  {mem_id}  active={s['active_retrievals']} "
                f"digest={s['digest_exposures']} "
                f"last_active={s['last_active_at'] or '-'}"
            )
    return "\n".join(lines)


def main() -> None:
    """Print a human or JSON summary of the surfacing log (read-only)."""
    parser = argparse.ArgumentParser(
        description="Aggregate surfaced.log into per-memory earned-utility stats.",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="Path to surfaced.log (default: data/logs/surfaced.log).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="How many top actively-retrieved memories to list (default 20).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (per-memory stats + summary).",
    )
    args = parser.parse_args()
    stats = aggregate_surfacing(args.log_path)
    if args.json:
        print(json.dumps({"summary": summarise(stats), "memories": stats}, indent=2))
    else:
        print(_render_human(stats, args.top))


if __name__ == "__main__":
    main()
