#!/usr/bin/env python3
"""Per-memory surfacing logger — earned-utility instrumentation (item 16).

Stage 1 of the earned-utility value signal
(``wiki/planning/earned-utility-value-signal-proposal.md``). The three
paths by which a memory reaches a session — the session-start **digest**,
the autonomous **fetch**-memories depth-fetch, and the ``/recall``
command — already log *invocations* (counts) to ``digest.log`` and
``fetch-memories.log``, but none of them records *which* memory was
surfaced. Without per-ID attribution there is no behavioural value
signal: we cannot tell which memories actually earn their keep.

This module closes that gap. It appends one tab-separated line per
surfaced memory ID to ``data/logs/surfaced.log``::

    <iso-timestamp>\tid=<memory-id>\tpath=digest|fetch|recall\trank=<n>\tsession=<id>

so that an offline aggregator (``scripts/surfacing_stats.py``) can later
build per-memory ``{active_retrievals, digest_exposures, last_active_at}``
counts. **Stage 1 is instrumentation only** — it changes nothing about
what any path surfaces, and there is no consumption logic. The consuming
"stay-of-execution on archival" design (Stage 2) waits until months of
data have accrued (see the proposal §5–§6).

Design choices (from the proposal §4):

- **Append-only side-log, NOT a record field.** Writing a
  ``surfaced_count`` onto the memory record would be invisible to the
  PostgreSQL-reading recall paths (the INSERT-only sync bug, plan P8) and
  would rewrite the hot ``memories.jsonl`` on every session start. A side
  log aggregated on demand mirrors ``confab-flags.log`` / ``digest.log``
  and sidesteps both problems.
- **Path is recorded** so the aggregator can weight *active* retrieval
  (``fetch`` / ``recall`` — intent-driven, can return any memory) far
  above *passive* ``digest`` exposure (drawn only from the verified-true
  pool, so it largely re-derives the anchor signal).
- **Best-effort by contract.** Every write swallows its own failures so
  instrumentation can never degrade a surfacing path (the
  ``log-recall.py`` / ``_log_invocation`` contract).

PRIVACY: a logged value is a memory **ID** (e.g. ``2026-06-05-ab12cd34``)
— metadata about Shawn's *own* record, which already appears throughout
the corpus and PostgreSQL. It is never the user's search text. This
matches the deliberate posture of the sibling logs, which record selector
*names* (``query``) never the query string.

The ``session`` column is **reserved** for forward-compatibility but is
currently always ``-``: the standalone ``fetch-memories.py`` / ``/recall``
paths have no session id in hand, and the digest fires once per session
(so a digest line already ≈ one session-exposure). Reserving the column
now keeps the line format stable if a session id is ever threaded
through, so the aggregator's parser does not break mid-accrual.

Usage (CLI — for the ``/recall`` command, which knows the served IDs):
    python3 scripts/surfacing_log.py --path recall --ids "2026-06-05-ab12 2026-06-04-cd34"
    python3 scripts/surfacing_log.py --path recall --ids "id1,id2,id3"

Usage (import — for the hook and ``fetch-memories.py``):
    import surfacing_log
    surfacing_log.log_surfaced(result.entries, "digest")
    surfacing_log.log_surfaced(results, "fetch")

The destination is resolved at call time by :func:`default_log_path`:
``PA_SURFACED_LOG`` first, then nothing at all under pytest (audit S22 —
a test exercising a surfacing path must not append to the operator's real
log), then the shipped ``<root>/logs/surfaced.log``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

# Repository root: this file is ``<root>/scripts/surfacing_log.py``. The
# ``logs`` symlink at the root resolves to ``data/logs`` — the same
# directory ``digest.log`` and ``fetch-memories.log`` live in.
PA_DIR = Path(__file__).resolve().parent.parent

#: Environment variable that pins the log destination. Honoured ahead of
#: everything else, so an operator (or a test that wants the production
#: resolution exercised) can point the writer somewhere harmless without
#: touching the call sites.
LOG_PATH_ENV = "PA_SURFACED_LOG"

#: The shipped destination, derived from ``__file__`` rather than ``HOME``.
#: Resolve through :func:`default_log_path` rather than reading this: the
#: destination is deliberately absent under pytest, and this constant knows
#: nothing about that.
SHIPPED_LOG_PATH = PA_DIR / "logs" / "surfaced.log"


def default_log_path() -> Path | None:
    """Where an unpinned :func:`log_surfaced` call writes, or ``None``.

    Resolved at CALL time, never at import: nothing here opens, creates,
    or even stats a file until a surfacing path actually logs something.

    The rules, in order:

    1. ``PA_SURFACED_LOG`` wins whenever it is set to a non-empty value.
    2. Under pytest there is NO destination — the caller gets ``None`` and
       :func:`log_surfaced` writes nothing at all.
    3. Otherwise :data:`SHIPPED_LOG_PATH`, the production destination.

    Rule 2 is audit finding S22 (2026-09-08), whose third member this was.
    ``SHIPPED_LOG_PATH`` comes from ``__file__``, so it points at the
    operator's own checkout no matter where the suite's ``HOME`` is
    pinned, and it runs through the ``logs`` symlink into the private
    ``data`` submodule. Exercising the session-start retrieval hook in a
    test therefore appended live-looking rows to the operator's real
    ``surfaced.log`` — and this log is the earned-utility evidence base
    (``wiki/planning/earned-utility-value-signal-proposal.md``), so
    fabricated rows do not merely litter: they inflate the retrieval
    counts a future archival decision will be made on. A test that wants
    the writer exercised pins ``log_path=`` or sets the variable above.
    """
    override = os.environ.get(LOG_PATH_ENV)
    if override:
        return Path(override)
    if "pytest" in sys.modules:
        return None
    return SHIPPED_LOG_PATH

# The three surfacing paths (proposal §2). The writer does not *reject* an
# unknown label (best-effort logging must not drop data), but the CLI
# validates against this set so a typo is caught at the call site.
VALID_PATHS = ("digest", "fetch", "recall")

# Splits a CLI ``--ids`` value on commas and/or whitespace so callers may
# pass either separator (or a mix).
_ID_SPLIT = re.compile(r"[\s,]+")


def _clean(value: object) -> str:
    """Collapse all whitespace in a field so it cannot forge a column.

    A tab or newline embedded in an id/path/session value would otherwise
    split the tab-separated record or inject a spurious line. Mirrors the
    sanitisation in ``log-recall.py:format_line``. ``None`` collapses to the
    empty string (not the literal ``"None"``) so the caller's ``or "-"``
    placeholder fires for an absent field.
    """
    if value is None:
        return ""
    return " ".join(str(value).split())


def format_surfacing_line(
    memory_id: str,
    path: str,
    rank: object,
    session: object,
    *,
    now: datetime,
) -> str:
    """Format one tab-separated ``surfaced.log`` line (pure; no I/O).

    ``rank`` is the 1-based position of the memory in the surfaced list
    (rank 1 = top-ranked / first returned). ``session`` is the reserved
    session column (pass ``None`` or ``""`` for the current always-``-``
    behaviour). All free-form fields are whitespace-collapsed so none can
    forge a column.
    """
    mem_id = _clean(memory_id) or "-"
    path_clean = _clean(path) or "-"
    sess = _clean(session) or "-"
    # ``rank`` is coerced to int where possible; a non-numeric rank degrades
    # to ``-`` rather than raising (best-effort).
    try:
        rank_str = str(int(rank))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        rank_str = "-"
    return (
        f"{now.isoformat()}\t"
        f"id={mem_id}\t"
        f"path={path_clean}\t"
        f"rank={rank_str}\t"
        f"session={sess}\n"
    )


def iter_surfacing_lines(
    memories: Iterable[dict] | None,
    path: str,
    *,
    session: object = None,
    now: datetime,
) -> list[str]:
    """Build the per-ID log lines for a surfaced list (pure; no I/O).

    Each memory dict contributes one line, ranked by its position in the
    iterable (1-based). Entries without a usable ``id`` are skipped (they
    cannot be attributed). Returns an empty list for ``None``/empty input.
    """
    if not memories:
        return []
    lines: list[str] = []
    rank = 0
    for mem in memories:
        # Rank tracks *position in the surfaced list*, so it advances only
        # for entries we actually emit a line for; an id-less entry is
        # skipped without consuming a rank slot.
        mem_id = mem.get("id") if isinstance(mem, dict) else None
        if not mem_id:
            continue
        rank += 1
        lines.append(
            format_surfacing_line(mem_id, path, rank, session, now=now)
        )
    return lines


def log_surfaced(
    memories: Iterable[dict] | None,
    path: str,
    *,
    session: object = None,
    log_path: Path | None = None,
    now: datetime | None = None,
) -> int:
    """Append one ``surfaced.log`` line per surfaced memory (best-effort).

    Returns the number of lines written (0 for empty input or on any
    failure). **Never raises** — a logging failure must not break the
    surfacing path that called it. Opens the log once and writes all lines
    in a single handle to minimise session-start I/O.

    ``log_path`` resolves through :func:`default_log_path` when ``None`` —
    at call time, not as a bound default argument, so the production
    callers stay path-agnostic. When that resolution yields ``None``
    (under pytest with nothing pinned) this writes NOTHING and returns 0:
    a surfacing path exercised by a test must not append to the
    operator's real log (audit S22).
    """
    try:
        stamp = now or datetime.now(timezone.utc)
        lines = iter_surfacing_lines(memories, path, session=session, now=stamp)
        if not lines:
            return 0
        target = log_path if log_path is not None else default_log_path()
        if target is None:
            return 0
        # The mkdir is inside the resolution branch, not above it, so an
        # unpinned call under pytest creates no directory either — the
        # ``logs`` symlink runs into the private data submodule, where a
        # bare mkdir is itself a write to the operator's state.
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.writelines(lines)
        return len(lines)
    except Exception:  # noqa: BLE001 — instrumentation must never raise
        return 0


def main() -> None:
    """Append surfacing lines for explicit IDs (the ``/recall`` path).

    ``/recall`` reads ``memories.jsonl`` directly and knows the IDs it just
    served, so it shells out here with ``--ids`` rather than importing this
    module. ``--ids`` accepts a comma- and/or whitespace-separated list.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Log per-memory surfacing for the earned-utility signal "
            "(item 16). Best-effort; never alters recall output."
        ),
    )
    parser.add_argument(
        "--path",
        default="recall",
        choices=VALID_PATHS,
        help="Surfacing path that returned these memories (default 'recall').",
    )
    parser.add_argument(
        "--ids",
        default="",
        help=(
            "The surfaced memory IDs, comma- and/or whitespace-separated. "
            "These are the user's own record IDs, never search text."
        ),
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Reserved session id (optional; currently unused).",
    )
    args = parser.parse_args()
    ids = [i for i in _ID_SPLIT.split(args.ids.strip()) if i]
    log_surfaced(
        [{"id": i} for i in ids],
        args.path,
        session=args.session,
    )


if __name__ == "__main__":
    main()
