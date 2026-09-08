#!/usr/bin/env python3
"""Log a verifier-agent confabulation-flag tally to ``confab-flags.log``.

Vector 2 §8 instrumentation, measurement (3): "the output verifier
already runs against important deliverables — compare the count of
confabulation-flagged items pre- vs post-ship". No general output
verifier runs every session, so the cheap, automatable signal comes from
the three adversarial verifier agents that already re-check a
deliverable's claims against authoritative sources and classify each
failure:

  - lit-scout-verifier        (DOIs vs CrossRef / Semantic Scholar / OpenAlex)
  - prior-art-scout-verifier  (repos / packages / models vs GitHub / PyPI / npm / HF)
  - data-profile-verifier     (numeric claims vs the source dataset)

Each emits a per-claim ``corrections.jsonl`` whose records carry a
``status`` (pass / partial / fail / unverifiable / documentation_defect)
and, on failures, a ``failure_type`` that includes a first-class
``confabulation`` class. This helper records, per verifier run, how many
claims were checked, how many FAILED, how many of those failures were
specifically ``confabulation``, and the spread of failure kinds — one
tab-separated line per run appended to ``data/logs/confab-flags.log``.

Forward-only: there is no pre-ship data, so this does NOT serve the
2026-06-13 review's pre/post comparison — it is a standing capability
that feeds the memory-health standing report (write-path plan item 18).

Two input modes (use whichever the caller has to hand):
  1. ``--corrections PATH`` — parse a ``corrections.jsonl`` and auto-tally.
  2. ``--checked / --flagged / --confab / --kinds`` — explicit counts,
     used by the verifier agents (which have just classified every claim).
Explicit counts, when given, override the parsed tally.

Best-effort by contract: any failure is swallowed so instrumentation can
never degrade a verifier run.

PRIVACY: ``--deliverable`` is a short label only (a topic slug or run
id), never claim contents or search text.

Manual entries (Tier B — the ``/confab`` command, ``commands/confab.md``)
share this log with a non-verifier ``source`` (``user-correction`` /
``self-catch``), a ``--detail`` note, and ``--checked 0``. A manual catch
has no denominator — you only ever log the catches, never the clean
cases — so manual rows are **absolute-count-only**: a consumer computing
the verifier *rate* (Σflagged / Σchecked) MUST restrict to verifier-agent
sources (equivalently ``checked > 0``) and count manual rows separately.

Usage:
    python3 scripts/log-confab-flag.py --source lit-scout-verifier \\
        --checked 42 --flagged 3 --confab 2 --kinds confabulation,stale_count \\
        --deliverable "llm-history-lit-2026-06"
    python3 scripts/log-confab-flag.py --source data-profile-verifier \\
        --corrections /path/to/corrections.jsonl --deliverable "lire-profile"
    python3 scripts/log-confab-flag.py --source user-correction \\
        --checked 0 --flagged 1 --confab 1 --kinds path \\
        --deliverable "inscriptions" --detail "claimed scripts/foo.py, actually scripts/bar/foo.py"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Repository root: this file is ``<root>/scripts/log-confab-flag.py``. The
# ``logs`` symlink at the root resolves to ``data/logs``.
PA_DIR = Path(__file__).resolve().parent.parent

#: Environment variable pinning the destination (audit R17).
LOG_PATH_ENV = "PA_CONFAB_LOG"

#: The shipped destination, derived from ``__file__`` rather than ``HOME``.
SHIPPED_LOG_PATH = PA_DIR / "logs" / "confab-flags.log"

def default_log_path() -> Path | None:
    """Where an unpinned write goes, or ``None`` for "write nothing".

    Resolved at CALL time, never bound as a default argument: nothing here
    touches the filesystem until something actually logs. The rules, in
    order (audit S22, extended to this script by audit R17):

    1. ``PA_CONFAB_LOG`` wins whenever it is set to a non-empty value.
    2. Under pytest there is NO destination — the caller gets ``None`` and
       writes nothing at all.
    3. Otherwise :data:`SHIPPED_LOG_PATH`.

    Rule 2 matters because ``SHIPPED_LOG_PATH`` comes from ``__file__``,
    not from ``HOME``: it points at the operator's own checkout wherever
    the suite pins ``HOME``, and runs through the ``logs`` symlink into the
    private data submodule. A test exercising this path would otherwise
    append live-looking rows to the operator's real instrumentation.
    """
    override = os.environ.get(LOG_PATH_ENV)
    if override:
        return Path(override)
    if "pytest" in sys.modules:
        return None
    return SHIPPED_LOG_PATH


# A failing claim has this status; a confabulation failure has this
# failure_type. Both strings are shared verbatim across all three
# verifier-agent contracts (agents/*-verifier.md).
FAIL_STATUS = "fail"
CONFABULATION = "confabulation"


def tally_corrections(records: list[dict]) -> dict[str, object]:
    """Tally a list of ``corrections.jsonl`` records (pure; no I/O).

    Returns ``checked`` (claims verified), ``flagged`` (claims whose
    ``status`` is ``fail``), ``confab`` (flagged claims whose
    ``failure_type`` is ``confabulation``), and ``kinds`` (the sorted
    distinct ``failure_type`` values among flagged claims).
    """
    fails = [r for r in records if str(r.get("status", "")).strip().lower() == FAIL_STATUS]
    failure_types = [
        str(r.get("failure_type")).strip().lower()
        for r in fails
        if r.get("failure_type")
    ]
    return {
        "checked": len(records),
        "flagged": len(fails),
        "confab": sum(1 for t in failure_types if t == CONFABULATION),
        "kinds": sorted(set(failure_types)),
    }


def load_corrections(path: Path) -> list[dict]:
    """Read a ``corrections.jsonl`` file into a list of dicts.

    Blank and unparseable lines are skipped — the file is treated as
    advisory input, never trusted to be perfectly formed.
    """
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
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


def format_line(
    source: str,
    deliverable: str,
    checked: int,
    flagged: int,
    confab: int,
    kinds: list[str],
    *,
    now: datetime,
    detail: str = "",
) -> str:
    """Format one tab-separated ``confab-flags.log`` line (pure; no I/O).

    ``detail`` is an optional short free-text note (used by manual
    ``/confab`` entries, e.g. "claimed X, actually Y"). It is whitespace-
    collapsed and truncated so it can never break the tab-separated
    schema; empty for verifier-tally rows.
    """
    # Collapse all whitespace (incl. tabs/newlines) in EVERY field so no value
    # — agent-supplied source, free-text deliverable/detail, or kind labels —
    # can forge a column or split the record; detail is also length-bounded.
    def _clean(value: object) -> str:
        return " ".join(str(value).split())

    source = _clean(source) or "-"
    deliverable = _clean(deliverable) or "-"
    kinds_field = ",".join(c for c in (_clean(k) for k in kinds) if c) or "none"
    detail_field = _clean(detail)[:200] or "-"
    return (
        f"{now.isoformat()}\t"
        f"source={source}\t"
        f"deliverable={deliverable}\t"
        f"checked={int(checked)}\t"
        f"flagged={int(flagged)}\t"
        f"confab={int(confab)}\t"
        f"kinds={kinds_field}\t"
        f"detail={detail_field}\n"
    )


def log_confab_flag(
    source: str,
    *,
    checked: int,
    flagged: int,
    confab: int,
    kinds: list[str] | None = None,
    deliverable: str = "",
    detail: str = "",
    log_path: Path | None = None,
    now: datetime | None = None,
) -> bool:
    """Append one confab-flag record to the log (best-effort).

    Returns ``True`` on a successful write, ``False`` if anything went
    wrong or if there is no destination. Never raises — a logging failure
    must not break the verifier. ``log_path`` resolves through
    :func:`default_log_path` when ``None``, at call time.
    """
    try:
        target = log_path if log_path is not None else default_log_path()
        if target is None:
            return False
        stamp = now or datetime.now(timezone.utc)
        line = format_line(
            source, deliverable, checked, flagged, confab, kinds or [],
            now=stamp, detail=detail,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    except Exception:  # noqa: BLE001 — instrumentation must never raise
        return False


def main(argv: list[str] | None = None) -> None:
    """Parse arguments (either input mode) and append one log line."""
    parser = argparse.ArgumentParser(
        description="Log a verifier confab-flag tally (Vector 2 §8 instrumentation).",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Verifier name, e.g. lit-scout-verifier / prior-art-scout-verifier / "
        "data-profile-verifier.",
    )
    parser.add_argument(
        "--deliverable",
        default="",
        help="Short label only (topic slug / run id) — never claim contents.",
    )
    parser.add_argument(
        "--corrections",
        type=Path,
        default=None,
        help="Path to a corrections.jsonl to auto-tally (mode 1).",
    )
    parser.add_argument("--checked", type=int, default=None, help="Claims verified (mode 2).")
    parser.add_argument("--flagged", type=int, default=None, help="Claims that FAILED (mode 2).")
    parser.add_argument(
        "--confab",
        type=int,
        default=None,
        help="Failed claims with failure_type=confabulation (mode 2).",
    )
    parser.add_argument(
        "--kinds",
        default="",
        help="Comma-separated failure_type values among fails (mode 2).",
    )
    parser.add_argument(
        "--detail",
        default="",
        help="Optional short note (manual /confab entries) — whitespace-collapsed "
        "and truncated to 200 chars.",
    )
    args = parser.parse_args(argv)

    # Start from a parsed corrections file when supplied, then let any
    # explicit count override the corresponding parsed field.
    tally: dict[str, object] = {"checked": 0, "flagged": 0, "confab": 0, "kinds": []}
    if args.corrections is not None:
        try:
            tally = tally_corrections(load_corrections(args.corrections))
        except Exception:  # noqa: BLE001 — bad path/file must not raise
            tally = {"checked": 0, "flagged": 0, "confab": 0, "kinds": []}

    checked = args.checked if args.checked is not None else int(tally["checked"])
    flagged = args.flagged if args.flagged is not None else int(tally["flagged"])
    confab = args.confab if args.confab is not None else int(tally["confab"])
    if args.kinds.strip():
        kinds = [k.strip().lower() for k in args.kinds.split(",") if k.strip()]
    else:
        kinds = list(tally["kinds"])  # type: ignore[arg-type]
    # Per-field overrides can otherwise produce a logically impossible row
    # (a confabulation is by definition a flagged failure): keep confab a
    # subset of flagged so the item-18 rate consumer can never see confab>flagged.
    confab = min(confab, flagged)

    log_confab_flag(
        args.source,
        checked=checked,
        flagged=flagged,
        confab=confab,
        kinds=kinds,
        deliverable=args.deliverable,
        detail=args.detail,
    )


if __name__ == "__main__":
    main()
