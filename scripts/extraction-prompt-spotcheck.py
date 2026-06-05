#!/usr/bin/env python3
"""
Spot-check harness: OLD vs NEW extraction prompt, on the real Haiku path.

Validates the P3 extraction-selectivity prompt change (write-path plan item 14)
by replaying the *current* production extraction path twice over a sample of
real ≤30-message transcript windows — once with the live prompt, once with the
proposed prompt — and comparing the per-run memory counts, the empty-return
rate, and the confidence mix.

Faithfulness: it imports `hooks/extraction-hook.py` and calls its own
`parse_transcript` + `extract_memories`, swapping only the prompt globals
(`EXTRACTION_PROMPT`, `CATEGORIES_REFERENCE`). So the conversation framing, the
Haiku model/params, the markdown-fence handling and the JSON parse are all the
exact production code. Windows are non-overlapping 30-message tiles of recent
transcripts — an approximation of the hook's incremental firing, but the unit
(a ≤30-message excerpt) is exactly what the prompt operates on.

SAFETY: dry-run by default — no API calls, no writes. Dry-run prints the exact
call count + token/cost estimate (the API-gate figures). `--run` makes the
Haiku calls (read-only otherwise — it never writes to memories.jsonl). Results
go to a report file under reports/; nothing in the corpus is touched.

Usage:
    venv/bin/python3 scripts/extraction-prompt-spotcheck.py            # dry-run (plan + cost)
    venv/bin/python3 scripts/extraction-prompt-spotcheck.py --windows 50
    venv/bin/python3 scripts/extraction-prompt-spotcheck.py --run      # fire (after approval)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PA = Path.home() / "personal-assistant"
HOOK_PATH = PA / "hooks" / "extraction-hook.py"
TRANSCRIPT_GLOB = "*/*.jsonl"
TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
REPORT_DIR = PA / "reports"

# Haiku 4.5 price estimate (USD per 1M tokens). ESTIMATE — the dry run prints
# raw token counts so the figure can be recomputed if the rate differs.
PRICE_IN_PER_MTOK = 1.00
PRICE_OUT_PER_MTOK = 5.00
EST_OUTPUT_TOKENS_PER_CALL = 1500   # cap is max_tokens=2000; old runs ~3 memories

# ---------------------------------------------------------------------------
# Import the live extraction hook (hyphenated filename → importlib)
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location("extraction_hook", HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
sys.modules["extraction_hook"] = hook
_spec.loader.exec_module(hook)


# ---------------------------------------------------------------------------
# NEW prompt — derived from the live prompt by replacing two regions, so it
# stays in sync with any other edits and fails loudly if the anchors move.
# ---------------------------------------------------------------------------

NEW_GUIDELINES = """## Extraction Guidelines

You are shown ONE EXCERPT of an ongoing session (the most recent messages), and \
you are run repeatedly across a session — so judge only THIS excerpt, and expect \
that most excerpts contribute little or nothing.

- **Most excerpts are worth ZERO memories — return `[]` freely.** Persist only \
what a FUTURE session would genuinely need. Never invent or pad to hit a count.
- **Do NOT persist:** status updates / progress narration, micro-decisions, \
one-off procedural picks ("used X to do Y"), plans for later today, restatements \
of what just happened, or anything recoverable from the repo / git / files.
- A **durable** memory stands alone (understandable without context) and carries \
lasting cross-session value: an explicit decision WITH rationale, a hard-won \
gotcha, a methodological choice, a genuine error AND its correction, a key \
source insight.
- Prefer one excellent memory over five mediocre ones.
- For decisions: include the rationale, not just the choice. For source_insight: \
what was learned, not bibliographic details. For error_mode: what went wrong AND \
the correction."""

OLD_DECISION = "- `decision` — Explicit choices with rationale (permanent)"
NEW_DECISION = (
    "- `decision` — An explicit, DURABLE choice with lasting rationale — NOT a "
    "plan, a task-management pick, or a one-off procedural choice (permanent)"
)


def derive_new_globals() -> tuple[str, str]:
    """Return (new_prompt, new_categories), or raise if an anchor moved."""
    prompt = hook.EXTRACTION_PROMPT
    start_marker = "## Extraction Guidelines"
    end_marker = "## Self-correction handling"
    if start_marker not in prompt or end_marker not in prompt:
        raise SystemExit(
            "ANCHOR MISS: the Extraction Guidelines / Self-correction markers "
            "are not where the harness expects. The live prompt changed — "
            "update this harness before trusting the comparison."
        )
    start = prompt.index(start_marker)
    end = prompt.index(end_marker)
    new_prompt = prompt[:start] + NEW_GUIDELINES + "\n\n" + prompt[end:]

    categories = hook.CATEGORIES_REFERENCE
    if OLD_DECISION not in categories:
        raise SystemExit(
            "ANCHOR MISS: the `decision` category line changed — update the "
            "harness OLD_DECISION before trusting the comparison."
        )
    new_categories = categories.replace(OLD_DECISION, NEW_DECISION)
    return new_prompt, new_categories


# ---------------------------------------------------------------------------
# Window sampling
# ---------------------------------------------------------------------------

def sample_windows(n_windows: int, max_transcripts: int) -> list[dict]:
    """
    Tile recent transcripts into non-overlapping ≤MAX_EXCHANGES-message windows
    and return up to ``n_windows`` of them (evenly strided across the pool for
    diversity). Each window: {transcript, idx, messages, conv_chars}.

    Only windows whose conversation_text ≥ MIN_CONTENT_LENGTH are kept — those
    are the windows the hook would actually send to Haiku.
    """
    transcripts = sorted(
        TRANSCRIPT_ROOT.glob(TRANSCRIPT_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_transcripts]

    pool: list[dict] = []
    win = hook.MAX_EXCHANGES
    for tpath in transcripts:
        try:
            messages, _ = hook.parse_transcript(str(tpath), None)
        except Exception:
            continue
        # Non-overlapping consecutive tiles of `win` messages.
        for i in range(0, len(messages), win):
            chunk = messages[i:i + win]
            conv = "\n\n".join(
                f"[{m['role'].upper()}]: {m['content']}" for m in chunk
            )
            if len(conv) < hook.MIN_CONTENT_LENGTH:
                continue
            pool.append({
                "transcript": tpath.name,
                "idx": i // win,
                "messages": chunk,
                "conv_chars": len(conv),
            })

    if len(pool) <= n_windows:
        return pool
    # Even stride so we span many transcripts rather than the first few.
    stride = len(pool) / n_windows
    return [pool[int(k * stride)] for k in range(n_windows)]


# ---------------------------------------------------------------------------
# Prompt building (mirrors extract_memories' .format call) for cost estimate
# ---------------------------------------------------------------------------

def _build_prompt(prompt_tpl: str, categories: str, conv: str) -> str:
    seed_tags = ", ".join(hook.load_seed_tags()[:30])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year = datetime.now(timezone.utc).strftime("%Y")
    return prompt_tpl.format(
        categories=categories, seed_tags=seed_tags,
        conversation=conv, today=today, year=year,
    )


def _est_tokens(text: str) -> int:
    """Coarse token estimate (~4 chars/token)."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# Extraction via the real hook path, with a temporary prompt swap
# ---------------------------------------------------------------------------

def _extract_with(messages, sid, prompt_tpl, categories):
    """Run the hook's real extract_memories with the given prompt globals."""
    saved_p, saved_c = hook.EXTRACTION_PROMPT, hook.CATEGORIES_REFERENCE
    hook.EXTRACTION_PROMPT, hook.CATEGORIES_REFERENCE = prompt_tpl, categories
    try:
        return hook.extract_memories(messages, sid)
    finally:
        hook.EXTRACTION_PROMPT, hook.CATEGORIES_REFERENCE = saved_p, saved_c


def _summarise(mems) -> dict:
    if mems is None:
        return {"count": None, "conf": {}}   # transient API failure
    return {
        "count": len(mems),
        "conf": dict(Counter((m.get("confidence") or "?") for m in mems)),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--windows", type=int, default=50,
                    help="number of windows to sample (default 50)")
    ap.add_argument("--max-transcripts", type=int, default=40,
                    help="newest N transcripts to tile (default 40)")
    ap.add_argument("--run", action="store_true",
                    help="actually call Haiku (default: dry-run, no API)")
    args = ap.parse_args()

    new_prompt, new_categories = derive_new_globals()
    windows = sample_windows(args.windows, args.max_transcripts)
    if not windows:
        print("No eligible windows found — check transcript root.")
        return 1

    # Exact call count + cost estimate (the API-gate figures).
    in_tokens = 0
    for w in windows:
        conv = "\n\n".join(
            f"[{m['role'].upper()}]: {m['content']}" for m in w["messages"]
        )
        in_tokens += _est_tokens(_build_prompt(hook.EXTRACTION_PROMPT,
                                                hook.CATEGORIES_REFERENCE, conv))
        in_tokens += _est_tokens(_build_prompt(new_prompt, new_categories, conv))
    n_calls = 2 * len(windows)
    out_tokens = n_calls * EST_OUTPUT_TOKENS_PER_CALL
    cost = (in_tokens / 1e6) * PRICE_IN_PER_MTOK + (out_tokens / 1e6) * PRICE_OUT_PER_MTOK

    print(f"=== extraction-prompt spot-check ({'RUN' if args.run else 'DRY-RUN'}) ===")
    print(f"  windows sampled        : {len(windows)} (from {args.max_transcripts} newest transcripts)")
    print(f"  calls (old+new × win)  : {n_calls}")
    print(f"  est input tokens       : {in_tokens:,}")
    print(f"  est output tokens      : {out_tokens:,} (@ {EST_OUTPUT_TOKENS_PER_CALL}/call)")
    print(f"  EST COST               : ${cost:.2f}  "
          f"(@ ${PRICE_IN_PER_MTOK}/Mtok in, ${PRICE_OUT_PER_MTOK}/Mtok out — verify rate)")
    print(f"  model                  : {hook.HAIKU_MODEL} (real-time)")

    if not args.run:
        print("\nDRY-RUN — no API calls made. Re-run with --run to execute.")
        return 0

    # --- Live run ---
    hook.load_env()   # populate ANTHROPIC_API_KEY from .env
    rows = []
    old_counts, new_counts = [], []
    old_total = new_total = 0
    old_empty = new_empty = 0
    failures = 0
    for i, w in enumerate(windows):
        sid = f"spotcheck-{w['transcript'][:8]}-{w['idx']}"
        old = _summarise(_extract_with(w["messages"], sid,
                                       hook.EXTRACTION_PROMPT, hook.CATEGORIES_REFERENCE))
        new = _summarise(_extract_with(w["messages"], sid, new_prompt, new_categories))
        if old["count"] is None or new["count"] is None:
            failures += 1
        else:
            old_counts.append(old["count"]); new_counts.append(new["count"])
            old_total += old["count"]; new_total += new["count"]
            old_empty += (old["count"] == 0); new_empty += (new["count"] == 0)
        rows.append({"window": sid, "conv_chars": w["conv_chars"], "old": old, "new": new})
        print(f"  [{i+1}/{len(windows)}] {sid}: old={old['count']} new={new['count']}")

    def stats(xs):
        xs = sorted(xs)
        if not xs:
            return {}
        return {"n": len(xs), "median": statistics.median(xs),
                "mean": round(statistics.mean(xs), 2), "max": max(xs),
                "p90": xs[min(int(0.9 * len(xs)), len(xs) - 1)]}

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": hook.HAIKU_MODEL,
        "windows": len(windows), "failures": failures,
        "old_per_run": stats(old_counts), "new_per_run": stats(new_counts),
        "old_total": old_total, "new_total": new_total,
        "reduction_pct": round(100 * (1 - new_total / old_total), 1) if old_total else None,
        "old_empty_windows": old_empty, "new_empty_windows": new_empty,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORT_DIR / f"extraction-spotcheck-{stamp}.json"
    report_path.write_text(json.dumps({"summary": summary, "rows": rows},
                                       indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== RESULT ===")
    print(f"  old per-run: {summary['old_per_run']}")
    print(f"  new per-run: {summary['new_per_run']}")
    print(f"  total memories old→new: {old_total} → {new_total} "
          f"({summary['reduction_pct']}% reduction)")
    print(f"  empty-window rate old→new: {old_empty}/{len(old_counts)} → "
          f"{new_empty}/{len(new_counts)}")
    print(f"  transient failures: {failures}")
    print(f"  full report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
