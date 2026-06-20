#!/usr/bin/env python3
"""Generate an LLM-use disclosure inventory for a project's paper submission.

Reads the enriched session-metadata sidecars written by the Claude Code session
archive (``~/cc-archives/<project>/<session>/session.meta.json``) and emits a
Markdown inventory suitable as the supporting half of a Methods "use of large
language models" disclosure.

Design philosophy — **governance leads, counts support**. A Methods reviewer
reads "N prompts / M subagents" as evidence of *interaction*, not *oversight*.
The control claim must rest on the project's governance apparatus
(preregistration + amendments, a decisions register, pre-launch sign-off gates,
adversarial verification, author review). This script therefore emits the
governance section as a **stub for the human to fill** (it cannot be derived
from session metadata) and places the quantitative inventory *after* it, as
corroborating texture.

Honesty rules baked in (do not "improve" them away):
  * Session *type* is auto-proposed from a keyword heuristic and ALWAYS marked
    "(proposed — confirm)". Supply ``--types-map`` to override. A mislabelled
    type in a disclosure is worse than an unlabelled one.
  * Subagent ``subagent_type`` is frequently ``unspecified`` in the metadata;
    the breakdown reports what is actually recorded, including that bucket.
  * Cumulative wall-clock duration is NOT human effort (it includes overnight
    and long-running agent windows); it is reported only with that caveat.
  * The archive's notional token cost is NOT actual expenditure (work runs
    under a flat-rate subscription); it is omitted by default.
  * Output-token counts exclude reasoning/"thinking" traces, which the archive
    tracks separately and flags research-only.

Usage::

    python scripts/llm-use-inventory.py --project inscriptions \\
        --out ~/Code/inscriptions/reports/llm-use-inventory.md \\
        [--types-map session-types.json] [--archive-root ~/cc-archives]

``--project`` is the *archive* sub-directory name (which may differ from the
repository directory name, e.g. ``2026-mq-llm-dh-judgement-paper-b``).

Author: personal-assistant hub. UK/Australian English throughout.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any

# --- Display helpers ---------------------------------------------------------

# Friendly names for known model IDs. Unknown IDs fall back to the raw string,
# so newer models surface verbatim rather than being silently dropped.
MODEL_DISPLAY: dict[str, str] = {
    "claude-opus-4-8": "Opus 4.8",
    "claude-opus-4-7": "Opus 4.7",
    "claude-fable-5": "Fable 5",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-4-5": "Haiku 4.5",
}

# Session-type taxonomy. Order matters: the first bucket whose keywords match
# the (lower-cased) session label wins; ``analysis`` is the default.
# Keep the admin keywords distinctive — note "preregistered" (an analysis word)
# must NOT match, only "preregistration"/"osf"/"lodge"/"amendment".
TYPE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("dissemination", ("rac trac", "rac-trac", "conference", "talk", "deck",
                        "slide", "poster", "seminar", "present")),
    ("prereg-admin", ("preregistration", "osf", "lodge", "amendment", "ethics")),
    ("infra", ("dependency", "stack", "pymc", "sapphire", "tempfile",
               "resource exhaust", "cleanup", "environment")),
]
DEFAULT_TYPE = "analysis"

TYPE_ORDER = ["analysis", "prereg-admin", "dissemination", "infra"]


@dataclass
class Session:
    """One archived Claude Code session, reduced to disclosure-relevant fields."""

    directory: str
    session_id: str
    date: str  # YYYY-MM-DD
    label: str
    model_id: str
    turns: int
    tool_calls: int
    subagent_count: int
    subagent_types: dict[str, int]
    output_tokens: int
    thinking_blocks: int
    duration_minutes: int
    proposed_type: str
    type_source: str = "proposed"  # "proposed" | "override"
    extra: dict[str, Any] = field(default_factory=dict)


# --- Extraction --------------------------------------------------------------

def _clean_label(directory: str) -> str:
    """Turn an archive directory name into a readable session label.

    Strips the leading ``<timestamp>_`` prefix, replaces hyphens with spaces,
    drops a trailing collision suffix (``_<hex>``) and a trailing " and", and
    falls back to an explicit placeholder when nothing readable remains (some
    archive directories are bare hashes).
    """
    slug = directory.split("_", 1)[1] if "_" in directory else directory
    # Drop a trailing collision suffix like "..._2dc7fc5b".
    parts = slug.rsplit("_", 1)
    if len(parts) == 2 and all(c in "0123456789abcdef" for c in parts[1]) \
            and len(parts[1]) >= 6:
        slug = parts[0]
    slug = slug.replace("-", " ").strip()
    if slug.endswith(" and"):
        slug = slug[:-4]
    # Bare-hash directory names leave nothing meaningful.
    compact = slug.replace(" ", "")
    if not slug or (len(compact) >= 6 and all(c in "0123456789abcdef" for c in compact)):
        return "(untitled session — see transcript)"
    return slug


def _propose_type(label: str, tags: list[str]) -> str:
    """Heuristically propose a session type. Always treat the result as a guess."""
    haystack = (label + " " + " ".join(tags)).lower()
    for type_name, keywords in TYPE_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return type_name
    return DEFAULT_TYPE


def load_sessions(project_dir: pathlib.Path,
                  types_map: dict[str, str]) -> list[Session]:
    """Load and reduce every ``session.meta.json`` under ``project_dir``."""
    sessions: list[Session] = []
    for meta_path in sorted(project_dir.glob("*/session.meta.json")):
        meta = json.loads(meta_path.read_text())
        directory = meta_path.parent.name
        sess = meta.get("session", {}) or {}
        stats = meta.get("statistics", {}) or {}
        model = meta.get("model", {}) or {}
        sub_summary = stats.get("subagents_summary", {}) or {}
        thinking = meta.get("thinking_blocks", {}) or {}
        tags = meta.get("tags", []) or []

        label = _clean_label(directory)
        if directory in types_map:
            proposed, source = types_map[directory], "override"
        else:
            proposed, source = _propose_type(label, tags), "proposed"

        sessions.append(Session(
            directory=directory,
            session_id=sess.get("id", ""),
            date=(sess.get("started_at") or "")[:10],
            label=label,
            model_id=model.get("model_id", "(unknown)"),
            turns=int(stats.get("turns") or stats.get("human_messages") or 0),
            tool_calls=int((stats.get("tool_calls") or {}).get("total", 0)),
            subagent_count=int(sub_summary.get("count", len(meta.get("subagents") or []))),
            subagent_types=dict(sub_summary.get("by_type", {}) or {}),
            output_tokens=int((stats.get("tokens") or {}).get("output", 0)),
            thinking_blocks=int(thinking.get("count", 0)
                                if isinstance(thinking, dict) else 0),
            duration_minutes=int(sess.get("duration_minutes") or 0),
            proposed_type=proposed,
            type_source=source,
        ))
    return sessions


# --- Rendering ---------------------------------------------------------------

def _fmt(n: int) -> str:
    """Thousands-separated integer."""
    return f"{n:,}"


def render(project: str, sessions: list[Session], generated: str) -> str:
    """Render the full governance-leads Markdown inventory."""
    if not sessions:
        return f"# LLM-Use Inventory — {project}\n\n_No archived sessions found._\n"

    sessions = sorted(sessions, key=lambda s: s.date)
    n = len(sessions)
    span = f"{sessions[0].date} – {sessions[-1].date}"

    models = collections.Counter(s.model_id for s in sessions)
    types = collections.Counter(s.proposed_type for s in sessions)
    sub_types: collections.Counter = collections.Counter()
    for s in sessions:
        sub_types.update(s.subagent_types)

    tot_turns = sum(s.turns for s in sessions)
    tot_tools = sum(s.tool_calls for s in sessions)
    tot_subs = sum(s.subagent_count for s in sessions)
    tot_out = sum(s.output_tokens for s in sessions)
    tot_think = sum(s.thinking_blocks for s in sessions)
    tot_hours = sum(s.duration_minutes for s in sessions) / 60

    any_override = any(s.type_source == "override" for s in sessions)
    type_flag = "" if any_override else " *(all auto-proposed — confirm before use)*"

    def model_label(mid: str) -> str:
        return MODEL_DISPLAY.get(mid, mid)

    # Model progression (date -> model, only at changes).
    prog, prev = [], None
    for s in sessions:
        if s.model_id != prev:
            prog.append(f"{s.date}: {model_label(s.model_id)} (`{s.model_id}`)")
            prev = s.model_id

    models_line = ", ".join(
        f"{model_label(mid)} (`{mid}`, {cnt} session{'s' if cnt != 1 else ''})"
        for mid, cnt in models.most_common())

    types_line = ", ".join(f"{types[t]} {t}" for t in TYPE_ORDER if types[t])

    sub_role_rows = "\n".join(
        f"| {role} | {_fmt(cnt)} |" for role, cnt in sub_types.most_common())

    type_methods = "; ".join(
        f"{types[t]} {t}" for t in TYPE_ORDER if types[t] and t != "analysis")
    analysis_n = types.get("analysis", 0)

    table_rows = "\n".join(
        f"| {i + 1} | {s.date} | {s.label} | {s.proposed_type}"
        f"{'*' if s.type_source == 'proposed' else ''} | {model_label(s.model_id)} "
        f"| {_fmt(s.turns)} | {_fmt(s.tool_calls)} | {s.subagent_count} |"
        for i, s in enumerate(sessions))

    return f"""---
title: "LLM-Use Inventory — {project}"
purpose: "Supporting record for a Methods disclosure of large-language-model use"
generated: {generated}
source: "~/cc-archives/{project}/ (session.meta.json across {n} archived sessions)"
status: draft
---

# LLM-Use Inventory — {project}

**Generated {generated}** by `scripts/llm-use-inventory.py` from the local
Claude Code session archive. This is the **supporting (quantitative) half** of a
Methods disclosure; the **governance section below leads** and must be completed
by the author — see `notes/llm-use-disclosure-standard.md` for the full standard.
This is a **draft working record** — verify and adapt before submission.

## 1. Governance and author control (author to complete — this leads the disclosure)

> The control claim rests here, not on the interaction counts in §3. A reviewer
> reads prompt and subagent counts as evidence of *interaction*, not *oversight*.
> Fill the apparatus that actually evidences author control, for example:

- [ ] **Preregistration** lodged (OSF link / DOI) + amendment history.
- [ ] **Decisions register** — the numbered analytical decisions and who made them.
- [ ] **Pre-launch sign-off gates** — review before committing compute/API spend.
- [ ] **Adversarial / independent verification** — verifier passes, accuracy audits.
- [ ] **Author review** — what the author read, checked, and signed off.
- [ ] **What remained strictly under author control** — design, interpretation, claims.

*(Cross-reference the project's paper-writing brief / governance section so the
qualitative frame and this quantitative inventory are one disclosure, two halves.)*

## 2. Tools and models

| Field | Value |
|---|---|
| Tool | Claude Code (Anthropic agentic command-line interface) |
| Access method | `claude-code-cli` |
| Models used (exact IDs) | {models_line} |
| Archived sessions | {n} |
| Period | {span} |

**Model progression.** {' → '.join(prog)}.

## 3. Interaction summary (supporting texture — read the caveats)

| Field | Value |
|---|---|
| Sessions by type{type_flag} | {types_line} |
| Human turns (prompts) | {_fmt(tot_turns)} |
| Tool calls (code / file / search actions) | {_fmt(tot_tools)} |
| Delegated subagent runs | {_fmt(tot_subs)} |
| LLM output volume | ≈{tot_out / 1e6:.1f} M tokens |

**Subagent runs by recorded type** (the metadata's `subagent_type`; `unspecified`
means the type was not captured, not that no role existed):

| Subagent type | Runs |
|---|---|
{sub_role_rows}

**Caveats — read before quoting any figure.**

- *Session type* is auto-proposed by keyword heuristic (rows marked `*` in §4);
  **confirm or override** (`--types-map`) before relying on the split.
- *Output tokens* are generated output as recorded; **reasoning/"thinking"
  traces are tracked separately** ({_fmt(tot_think)} thinking blocks across the
  run, flagged research-only) and are **not** included in this figure.
- *Wall-clock duration* across the run is ≈{tot_hours:,.0f} hours, but this is
  elapsed open-to-close time **dominated by overnight/long-running agent windows
  — not human effort.** Actual human time lives in the personal time-log.
- *Cost* — the archive's notional list-price token cost is **not actual
  expenditure** (flat-rate subscription) and is omitted here by design.

## 4. Draft Methods paragraph (example — adapt to the venue's policy)

> Statistical analysis and analysis-code development for this study were carried
> out with the assistance of Claude Code (Anthropic), an agentic
> large-language-model coding environment, across {analysis_n} analysis sessions
> (plus {type_methods or 'other supporting work'}) between {sessions[0].date} and
> {sessions[-1].date}. The models used are listed in §2 by exact identifier. The
> analytical apparatus that governed this work — preregistration and amendments,
> a numbered decisions register, pre-launch sign-off gates, and independent
> verification (see §1) — kept design, analytical choices, and interpretation
> under author control; the model executed code, edited project files, and ran
> delegated sub-tasks under that governance ({_fmt(tot_subs)} subagent runs;
> {_fmt(tot_tools)} tool invocations; ≈{_fmt(tot_turns)} author prompts). Complete
> session transcripts are retained and available on request.

## 5. Per-session inventory (appendix)

Rows marked `*` in the *Type* column are auto-proposed and unconfirmed.

| # | Date | Session focus | Type | Model | Turns | Tool calls | Subagents |
|---|------|---------------|------|-------|-------|------------|-----------|
{table_rows}

## 6. Provenance and regeneration

- **Source:** `~/cc-archives/{project}/<session>/session.meta.json`; full
  transcripts (`session.jsonl.gz`, SHA-256-hashed) + nested subagent transcripts
  are retained per session.
- **Regenerate:** `python ~/personal-assistant/scripts/llm-use-inventory.py
  --project {project} --out <repo>/reports/llm-use-inventory.md`
  (add `--types-map` once session types are confirmed). Re-run after any new
  session is archived (archives are written at session close).
"""


# --- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True,
                        help="Archive sub-directory name under the archive root "
                             "(e.g. 'inscriptions').")
    parser.add_argument("--archive-root", default="~/cc-archives",
                        help="Root of the session archive (default: ~/cc-archives).")
    parser.add_argument("--out", default=None,
                        help="Output Markdown path (default: stdout).")
    parser.add_argument("--types-map", default=None,
                        help="Optional JSON file mapping archive directory name "
                             "to a confirmed session type, overriding the heuristic.")
    parser.add_argument("--generated", default=None,
                        help="Date stamp for the report (YYYY-MM-DD). Defaults to "
                             "today; pass explicitly for reproducible output.")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.archive_root).expanduser()
    project_dir = root / args.project
    if not project_dir.is_dir():
        parser.error(f"project directory not found: {project_dir}")

    types_map: dict[str, str] = {}
    if args.types_map:
        types_map = json.loads(pathlib.Path(args.types_map).expanduser().read_text())

    generated = args.generated
    if generated is None:
        # Imported lazily so the deterministic --generated path needs no clock.
        import datetime
        generated = datetime.date.today().isoformat()

    sessions = load_sessions(project_dir, types_map)
    markdown = render(args.project, sessions, generated)

    if args.out:
        out_path = pathlib.Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown)
        print(f"Wrote {out_path} ({len(sessions)} sessions).", file=sys.stderr)
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
