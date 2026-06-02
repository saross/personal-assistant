#!/usr/bin/env python3
"""Log a manual ``/recall`` invocation to the tier-2 retrieval log.

Vector 2 §8 instrumentation, measurement (2). The autonomous depth-fetch
path (``scripts/fetch-memories.py``) already appends one tab-separated
line per call to ``data/logs/fetch-memories.log`` via its
``_log_invocation`` helper. The manual ``/recall`` command, however,
reads ``memories.jsonl`` directly (see ``commands/recall.md``) and never
shells out to ``fetch-memories.py`` — so until now manual depth-fetches
were invisible to the observation-window apparatus.

This helper closes that blind spot. ``commands/recall.md`` calls it as a
mandatory final step so that the same log captures *both* retrieval
paths. Lines written here carry a ``source=recall`` field; lines without
a ``source=`` field are, by convention, the older autonomous
``fetch-memories.py`` invocations (which predate this field). The
2026-06-13 review parser keys on ``source=`` and treats its absence as
``source=fetch``.

The line format intentionally mirrors
``scripts/fetch-memories.py:_log_invocation`` so a single parser reads
the whole file. If that format ever changes, change it here too.

PRIVACY: the ``--selectors`` value records selector *names* only
(``query``, ``category:decision``, ``tag:ethics``, ``recent``,
``none``), never the user's search text — matching the deliberate
privacy choice in ``fetch-memories.py`` (which logs the selector name
``query``, never the query string).

Best-effort by contract: any failure is swallowed so instrumentation can
never degrade the ``/recall`` path itself.

Usage:
    python3 scripts/log-recall.py --selectors "query" --results 7
    python3 scripts/log-recall.py --selectors "category:decision;query" --results 3
    python3 scripts/log-recall.py --selectors "tag:ethics" --results 10 --limit 10
    python3 scripts/log-recall.py --selectors "none" --results 0
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

# Repository root: this file is ``<root>/scripts/log-recall.py``. The
# ``logs`` symlink at the root resolves to ``data/logs``.
PA_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = PA_DIR / "logs" / "fetch-memories.log"


def format_line(
    selectors: str,
    limit: object,
    results: int,
    source: str,
    *,
    now: datetime,
) -> str:
    """Format one tab-separated retrieval-log line (pure; no I/O).

    Mirrors ``fetch-memories.py:_log_invocation`` and appends a
    ``source`` field. ``limit`` is accepted as ``object`` because the
    autonomous path logs ``'?'`` when no limit applies; ``/recall``
    passes its fixed top-10 default.
    """
    selectors = selectors.strip() or "none"
    return (
        f"{now.isoformat()}\t"
        f"selectors={selectors}\t"
        f"limit={limit}\t"
        f"results={int(results)}\t"
        f"source={source}\n"
    )


def log_recall(
    selectors: str,
    *,
    results: int = 0,
    limit: object = 10,
    source: str = "recall",
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> bool:
    """Append one ``/recall`` record to the retrieval log (best-effort).

    Returns ``True`` on a successful write, ``False`` if anything went
    wrong. Never raises — a logging failure must not break ``/recall``.
    """
    try:
        stamp = now or datetime.now(timezone.utc)
        line = format_line(selectors, limit, results, source, now=stamp)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    except Exception:  # noqa: BLE001 — instrumentation must never raise
        return False


def main() -> None:
    """Parse arguments and append a single ``source=recall`` log line."""
    parser = argparse.ArgumentParser(
        description="Log a manual /recall invocation (Vector 2 §8 instrumentation).",
    )
    parser.add_argument(
        "--selectors",
        default="none",
        help=(
            "Selector NAMES only, never the search text — e.g. 'query', "
            "'category:decision;query', 'tag:ethics', 'recent', 'none'."
        ),
    )
    parser.add_argument(
        "--results",
        type=int,
        default=0,
        help="Number of memories returned by the recall.",
    )
    parser.add_argument(
        "--limit",
        default=10,
        help="Result cap applied (default 10 — /recall returns top 10).",
    )
    parser.add_argument(
        "--source",
        default="recall",
        help="Retrieval path tag (default 'recall'; overridable for reuse).",
    )
    args = parser.parse_args()
    log_recall(
        args.selectors,
        results=args.results,
        limit=args.limit,
        source=args.source,
    )


if __name__ == "__main__":
    main()
