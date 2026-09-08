#!/usr/bin/env python3
"""
Vector 2 — session-start digest dry-run harness (before/after proof).

Loads the LIVE memory corpus, reproduces the current ~16 KB recall dump
exactly as ``hooks/session-start-retrieval.py`` would emit it, builds the
proposed Stage 1 digest via the pure :mod:`digest` selector, and prints a
side-by-side byte comparison plus the actual digest text.

This is the deliverable a human reviews before the live cutover (PASS 2):
it changes NOTHING about session-start behaviour — it only reads the
corpus and reports. It also appends one demonstration line to
``data/logs/digest-preview.log`` — its OWN file, marked ``preview=true``,
never the live ``digest.log`` (audit R17).

Usage::

    python3 scripts/digest-preview.py                 # PA hub (all projects)
    python3 scripts/digest-preview.py --cwd /home/shawn/Code/inscriptions
    python3 scripts/digest-preview.py --budget 1500 --window-days 7
    python3 scripts/digest-preview.py --show-digest    # also print the text
    python3 scripts/digest-preview.py --no-log          # skip the preview log

The recall-dump reproduction calls the hook's own ``retrieve_*`` and
``format_context`` functions, so the "before" number tracks the real
hook rather than a stale persisted measurement.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PA_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PA_DIR / "scripts"
HOOK_PATH = PA_DIR / "hooks" / "session-start-retrieval.py"

#: Environment variable pinning this harness's log (audit R17).
LOG_PATH_ENV = "PA_DIGEST_PREVIEW_LOG"

#: Its OWN file, not ``digest.log`` (audit R17). A dry run is not a session:
#: writing demonstration rows into the live digest instrumentation made a
#: preview indistinguishable from a real session digest in the very log the
#: Vector 2 measurements are read from. Every line here also carries
#: ``preview=true`` so a mis-pointed run is still self-identifying.
SHIPPED_LOG_PATH = PA_DIR / "data" / "logs" / "digest-preview.log"

#: Marker appended to every line this harness writes.
PREVIEW_MARKER = "preview=true"


def default_log_path() -> Path | None:
    """Where an unpinned preview line goes, or ``None`` for "write nothing".

    Resolved at CALL time, never bound as a default argument (audit S22,
    extended here by R17): ``PA_DIGEST_PREVIEW_LOG`` first, then nothing at
    all under pytest, then :data:`SHIPPED_LOG_PATH`. The shipped path comes
    from ``__file__``, so it points into the operator's private data
    submodule however the suite pins ``HOME``.
    """
    override = os.environ.get(LOG_PATH_ENV)
    if override:
        return Path(override)
    if "pytest" in sys.modules:
        return None
    return SHIPPED_LOG_PATH


def preview_log_line(result, *, now: datetime) -> str:
    """The digest's own log line, marked as a preview (pure; no I/O)."""
    return f"{digest.digest_log_line(result, now=now)}\t{PREVIEW_MARKER}"

sys.path.insert(0, str(SCRIPTS_DIR))
import digest  # noqa: E402  (pure selector module)


def _load_hook():
    """Import the hyphenated session-start hook module by file path.

    The module name contains hyphens, so a plain ``import`` is
    impossible; load it from its path like the test-suite does.
    """
    spec = importlib.util.spec_from_file_location("session_start_retrieval", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def reproduce_recall_dump(hook, memories, current_project, project_tags) -> str:
    """Rebuild the current recall dump using the hook's own functions.

    Mirrors ``hooks/session-start-retrieval.py:main()`` exactly so the
    "before" figure is the real recall dump, not an approximation.
    Scratchpad is deliberately excluded — Vector 2 covers the recall
    dump only (design §1a); scratchpad is the out-of-scope "Vector 2b".
    """
    cutoff = datetime.now(timezone.utc) - hook.timedelta(days=hook.RECENT_DAYS)
    recent = hook.retrieve_recent(memories, cutoff, current_project, project_tags)
    recent_ids = {m.get("id") for m in recent if m.get("id")}
    permanent = hook.retrieve_permanent(
        memories, recent_ids, current_project, project_tags
    )
    taken_ids = recent_ids | {m.get("id") for m in permanent if m.get("id")}
    middle_aged = hook.retrieve_middle_aged(
        memories, taken_ids, current_project, project_tags
    )
    all_ids = taken_ids | {m.get("id") for m in middle_aged if m.get("id")}
    constraints = hook.retrieve_constraints(
        memories, all_ids, current_project, project_tags
    )
    return hook.format_context(recent, permanent, constraints, middle_aged)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cwd",
        default=str(PA_DIR),
        help="Working directory to derive the project from (default: PA hub).",
    )
    p.add_argument("--budget", type=int, default=digest.DEFAULT_BYTE_BUDGET)
    p.add_argument("--window-days", type=int, default=digest.DEFAULT_WINDOW_DAYS)
    p.add_argument(
        "--show-digest",
        action="store_true",
        help="Also print the full rendered digest text.",
    )
    p.add_argument(
        "--no-log",
        action="store_true",
        help="Do not append a demonstration line to data/logs/digest-preview.log.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    hook = _load_hook()
    now = datetime.now(timezone.utc)

    # Project derivation — mirror the hook's main(): the PA hub maps to
    # current_project=None so it sees all projects.
    current_project = hook.derive_project(args.cwd)
    pa_project = hook.encode_project_id(str(PA_DIR))
    hub_mode = current_project == pa_project
    if hub_mode:
        current_project = None

    memories = hook.load_all_memories()
    project_tags = hook.collect_project_tags(memories, current_project)

    # BEFORE — the real recall dump (no scratchpad; out of scope).
    recall_dump = reproduce_recall_dump(
        hook, memories, current_project, project_tags
    )
    before = _byte_len(recall_dump)

    # AFTER — the Stage 1 digest.
    result = digest.build_digest(
        memories,
        now=now,
        project_tags=project_tags,
        byte_budget=args.budget,
        window_days=args.window_days,
    )
    after = result.rendered_bytes

    # Report.
    cut = (1 - after / before) * 100 if before else 0.0
    print("=" * 72)
    print("Vector 2 — session-start digest dry-run (before / after)")
    print("=" * 72)
    print(f"  cwd            : {args.cwd}")
    print(f"  mode           : {'PA hub (all projects)' if hub_mode else 'project-scoped'}")
    print(f"  corpus loaded  : {len(memories):,} memories (newest-first, capped)")
    print(f"  project tags   : {len(project_tags):,} in profile")
    print(f"  window         : {args.window_days} days   budget: {args.budget} B")
    print("-" * 72)
    print(f"  BEFORE recall dump : {before:>7,} B")
    print(f"  AFTER  digest      : {after:>7,} B   (<= budget: {after <= args.budget})")
    print(f"  reduction          : {cut:>6.1f}%   ({before - after:,} B saved)")
    print("-" * 72)
    c = result.counter
    # Use the digest's own category formatter so this summary line matches
    # the capped breakdown that actually appears in the rendered digest
    # (not the full uncapped histogram).
    cats = digest._format_categories(c["categories"])
    print(f"  what-changed   : {c['new']} new ({cats}), "
          f"{c['updated']} updated, {c['forgotten']} forgotten")
    print(f"  verified avail : {result.verified_available} "
          f"(in last {args.window_days} d)   shown: {len(result.entries)}")
    print(f"  used fallback  : {result.used_fallback}")
    print("=" * 72)

    # The honest aggregate (per the global 'compute aggregate implications'
    # rule): the recall dump is only part of the session-start payload.
    print("\nNote: scratchpad (~29 KB, design-out-of-scope 'Vector 2b') is")
    print("untouched, so the TOTAL session-start payload drops by less than")
    print("the recall-dump reduction shown above. This proof covers the")
    print("recall dump only.")

    if args.show_digest:
        print("\n" + "-" * 72)
        print("RENDERED DIGEST:")
        print("-" * 72)
        print(result.text)

    # Instrumentation demonstration (design §9 pre-step). Its own file, and
    # its own marker, so a dry run can never be mistaken for a live session
    # in the digest measurements.
    target = default_log_path()
    if not args.no_log and target is not None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(preview_log_line(result, now=now) + "\n")
            print(f"\n[logged demonstration line to {target}]")
        except OSError as exc:  # best-effort; never fail the preview
            print(f"\n[warn: could not write {target}: {exc}]", file=sys.stderr)


if __name__ == "__main__":
    main()
