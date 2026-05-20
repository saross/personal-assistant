#!/usr/bin/env python3
"""
Re-sample the bake-off manifest with a 190K-token Haiku-compatible cap.

Background
----------
The original manifest (sample-manifest.json, generated 2026-05-17) drew its
"long" bin from 200K–500K distilled tokens. After confirming Haiku 4.5's
context window is 200K tokens, those three long-bin sessions cannot fit.
This script regenerates the manifest:

1. Enumerates a broader candidate pool across:
   - Archived sessions at ``~/cc-archives/*/*/session.jsonl(.gz)``
   - Per-project archives at ``~/Code/*/archive/cc-sessions/*/*/session.jsonl(.gz)``
   - Live transcripts at ``~/.claude/projects/*/<session-id>.jsonl``
   - Live sub-agent transcripts at ``~/.claude/projects/*/subagents/*.jsonl``
2. Skips git-LFS pointer stubs and transcripts that distil to fewer than 100
   tokens (matching the original >100-token floor).
3. Estimates distilled-text token count using the existing extractor
   (``scripts/extract-transcript-text.py``).
4. Caps inclusion at **190,000 distilled tokens** — 200K Haiku window minus
   ~3K for prompt + session header + 350-token output budget; safety buffer
   for the chars/4 heuristic's known under-counting of dense JSON.
5. Stratifies into three bins within the Haiku-compatible range:
   - short:  <50,000 tokens     (target n=4)
   - medium: 50K–119,999 tokens (target n=3)
   - long:   120K–190,000 tokens (target n=3)
6. Stratified random selection with ``random.seed(42)``.

Output
------
Overwrites ``data/experiments/bake-off-metadata-2026-05-18/sample-manifest.json``.
"""

from __future__ import annotations

import datetime
import glob
import importlib.util
import json
import random
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PA_DIR = Path("/home/shawn/personal-assistant")
MANIFEST_PATH = (
    PA_DIR
    / "data/experiments/bake-off-metadata-2026-05-18/sample-manifest.json"
)

# Token floor — raised from the original >100 to >1,000 per Shawn's
# suggestion ("raise to 1,000 if it helps weed out noise"). The live
# sub-agent pool is dominated by tiny prompts (median <1K tokens) that would
# crowd out substantive sessions in the short bin.
MIN_TOKENS = 1000

# Haiku-compatible cap: 200K window - prompt(~2K) - header(~150) - output(350)
# minus a safety buffer for chars/4 under-counting dense content.
HAIKU_CAP_TOKENS = 190_000

# Bin definitions (within Haiku-compatible range).
BINS = {
    "short":  (MIN_TOKENS,  49_999),
    "medium": (50_000,     119_999),
    "long":   (120_000,    HAIKU_CAP_TOKENS),
}
TARGET_COUNTS = {"short": 4, "medium": 3, "long": 3}

RNG_SEED = 42

# Git-LFS pointer stubs start with this line; we detect them and skip.
LFS_POINTER_RE = re.compile(rb"^version https://git-lfs\.github\.com/spec/")

# Live-transcript glob patterns (live transcripts have no meta.json).
# Note: sub-agent transcripts live at depth 4
# (~/.claude/projects/<proj>/<session-id>/subagents/<agent>.jsonl).
LIVE_GLOBS = [
    "/home/shawn/.claude/projects/*/*.jsonl",
    "/home/shawn/.claude/projects/*/*/subagents/*.jsonl",
]

# Archive glob patterns (these typically have a session.meta.json sibling).
ARCHIVE_GLOBS = [
    "/home/shawn/cc-archives/*/*/session.jsonl",
    "/home/shawn/cc-archives/*/*/session.jsonl.gz",
    "/home/shawn/Code/*/archive/cc-sessions/*/*/session.jsonl",
    "/home/shawn/Code/*/archive/cc-sessions/*/*/session.jsonl.gz",
    "/home/shawn/personal-assistant/archive/cc-sessions/*/*/session.jsonl",
    "/home/shawn/personal-assistant/archive/cc-sessions/*/*/session.jsonl.gz",
]


# ---------------------------------------------------------------------------
# Extractor import
# ---------------------------------------------------------------------------


def _load_extractor():
    """Import scripts/extract-transcript-text.py as a module."""
    path = PA_DIR / "scripts" / "extract-transcript-text.py"
    spec = importlib.util.spec_from_file_location(
        "extract_transcript_text", str(path)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load extractor from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Candidate enumeration
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One transcript candidate, pre-extraction."""

    source: str  # "archive" or "live" or "subagent"
    transcript_path: str
    meta_path: Optional[str]  # None for live transcripts
    project: str  # Best-effort project label.
    session_id: str
    started_at: Optional[str]  # None when unknown.


def _is_lfs_pointer(path: Path) -> bool:
    """Cheap check: read the first 60 bytes; LFS pointers are tiny text."""
    try:
        with open(path, "rb") as f:
            head = f.read(60)
        return bool(LFS_POINTER_RE.match(head))
    except OSError:
        return False


def _project_from_archive_path(p: str) -> str:
    """Pull the project name out of an archive path.

    Forms:
      /home/shawn/cc-archives/<project>/<timestamp_dir>/session.jsonl(.gz)
      /home/shawn/Code/<project>/archive/cc-sessions/<subdir>/<timestamp_dir>/session.jsonl(.gz)
      /home/shawn/personal-assistant/archive/cc-sessions/<project>/<timestamp_dir>/session.jsonl(.gz)
    """
    parts = Path(p).parts
    if "cc-archives" in parts:
        idx = parts.index("cc-archives")
        return parts[idx + 1]
    if "cc-sessions" in parts:
        idx = parts.index("cc-sessions")
        # Either Code/<project>/archive/cc-sessions/<sub> or .../cc-sessions/<project>/...
        if "Code" in parts:
            cidx = parts.index("Code")
            return parts[cidx + 1]
        return parts[idx + 1]
    return "unknown"


def _project_from_live_dir(p: str) -> str:
    """Recover project name from a live transcript path.

    Live transcript dirs look like:
      /home/shawn/.claude/projects/-home-shawn-Code-voice-assistant/<sid>.jsonl
    Map by stripping the leading '-home-shawn-' and replacing remaining '-'
    with '/' to reconstruct the working-directory hint, then take the basename.
    """
    parts = Path(p).parts
    try:
        dir_name = parts[parts.index("projects") + 1]
    except (ValueError, IndexError):
        return "unknown"
    # Strip the leading marker.
    s = dir_name
    for prefix in ("-home-shawn-Code-", "-home-shawn-"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s or dir_name


def _load_meta(meta_path: Path) -> Optional[dict]:
    """Read session.meta.json; return parsed dict or None on failure."""
    try:
        return json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _meta_session_id(meta: dict) -> Optional[str]:
    """Pull the authoritative session_id from a parsed meta dict."""
    session = meta.get("session") or {}
    return session.get("id")


def _meta_started_at(meta: dict) -> Optional[str]:
    """Pull started_at from a parsed meta dict."""
    session = meta.get("session") or {}
    return session.get("started_at")


def _meta_project_name(meta: dict) -> Optional[str]:
    """Pull the authoritative project name from a parsed meta dict."""
    project = meta.get("project") or {}
    return project.get("name")


def enumerate_archive_candidates() -> list[Candidate]:
    """Walk all archive globs; return one Candidate per non-LFS transcript.

    ``glob.glob`` returns filesystem-order results, which differ across
    machines, so each call is wrapped in ``sorted(...)`` to make the
    enumeration order deterministic. This matters because the downstream
    ``random.seed(42)`` shuffle is only reproducible if the input list
    is identical across runs.
    """
    seen_paths: set[str] = set()
    out: list[Candidate] = []
    for pattern in ARCHIVE_GLOBS:
        for path_str in sorted(glob.glob(pattern)):
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)
            p = Path(path_str)
            if _is_lfs_pointer(p):
                continue
            project = _project_from_archive_path(path_str)
            meta_path = p.parent / "session.meta.json"
            session_id = p.parent.name  # fallback if no meta
            started_at = None
            meta_str: Optional[str] = None
            if meta_path.exists():
                meta = _load_meta(meta_path)
                if meta:
                    # Meta is authoritative — its session.id and project.name
                    # may disagree with the directory layout (some legacy
                    # archives stored sessions under the wrong project name).
                    session_id = _meta_session_id(meta) or session_id
                    started_at = _meta_started_at(meta)
                    project = _meta_project_name(meta) or project
                    meta_str = str(meta_path)
            out.append(Candidate(
                source="archive",
                transcript_path=str(p),
                meta_path=meta_str,
                project=project,
                session_id=session_id,
                started_at=started_at,
            ))
    return out


def enumerate_live_candidates() -> list[Candidate]:
    """Walk live globs under ~/.claude/projects/.

    Wraps ``glob.glob`` in ``sorted(...)`` for deterministic order across
    machines — see ``enumerate_archive_candidates`` for the rationale.
    """
    seen_paths: set[str] = set()
    out: list[Candidate] = []
    for pattern in LIVE_GLOBS:
        is_subagent = "/subagents/" in pattern
        for path_str in sorted(glob.glob(pattern)):
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)
            p = Path(path_str)
            if _is_lfs_pointer(p):
                continue
            project = _project_from_live_dir(path_str)
            session_id = p.stem  # filename minus .jsonl
            out.append(Candidate(
                source="subagent" if is_subagent else "live",
                transcript_path=str(p),
                meta_path=None,
                project=project,
                session_id=session_id,
                started_at=None,
            ))
    return out


# ---------------------------------------------------------------------------
# Extraction + classification
# ---------------------------------------------------------------------------


@dataclass
class Scored:
    """A candidate with its distilled token count and bin label."""

    candidate: Candidate
    content_tokens: int
    bin_label: Optional[str]  # None if outside any bin (e.g., >190K cap)
    three_ps_state: str  # "empty", "populated", or "unknown" (live has no state)


def _three_ps_state_from_meta(meta_path: Optional[str]) -> str:
    """Inspect session.meta.json for an existing three_ps.prompt_summary."""
    if not meta_path:
        return "unknown"  # Live transcript — no meta yet.
    try:
        meta = json.loads(Path(meta_path).read_text())
    except (OSError, json.JSONDecodeError):
        return "unknown"
    three_ps = meta.get("three_ps") or {}
    prompt_summary = (three_ps.get("prompt_summary") or "").strip()
    return "populated" if prompt_summary else "empty"


def classify_bin(tokens: int) -> Optional[str]:
    """Return the bin label for a token count, or None if out of range."""
    for label, (lo, hi) in BINS.items():
        if lo <= tokens <= hi:
            return label
    return None


def extract_and_score(candidates: list[Candidate], extractor) -> list[Scored]:
    """Run the extractor on each candidate; assign bin + three_ps state.

    Errors during extraction are silently skipped (logged to stderr count).
    """
    out: list[Scored] = []
    errors = 0
    for c in candidates:
        try:
            text = extractor.extract_transcript_text(c.transcript_path)
        except Exception:  # noqa: BLE001 — best-effort survey
            errors += 1
            continue
        tokens = extractor.estimate_tokens(text)
        if tokens < MIN_TOKENS:
            continue
        bin_label = classify_bin(tokens)
        state = _three_ps_state_from_meta(c.meta_path)
        out.append(Scored(
            candidate=c,
            content_tokens=tokens,
            bin_label=bin_label,
            three_ps_state=state,
        ))
    if errors:
        print(f"  (skipped {errors} candidates due to extractor errors)",
              file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Stratified sampling
# ---------------------------------------------------------------------------


def stratified_sample(scored: list[Scored]) -> list[Scored]:
    """Pick TARGET_COUNTS per bin, prioritising empty-state archived sessions.

    Within each bin, the selection prefers:
      1. Sessions whose meta marks three_ps as ``empty`` (best-effort empty
         inclusion per the spec — at least 1–2 empties wanted overall).
      2. Then everything else (populated archive + live + subagent), randomly.

    This is deliberately not pure random across the whole bin — Shawn asked
    for best-effort empty inclusion, and empties are rarer in the live pool.
    """
    rng = random.Random(RNG_SEED)
    picks: list[Scored] = []

    # Bucket by bin.
    by_bin: dict[str, list[Scored]] = {b: [] for b in BINS}
    for s in scored:
        if s.bin_label in by_bin:
            by_bin[s.bin_label].append(s)

    for bin_label, target in TARGET_COUNTS.items():
        pool = by_bin[bin_label]
        if not pool:
            print(f"  WARNING: bin {bin_label} has 0 candidates")
            continue

        # Within a bin, build a per-bin mix that balances:
        #   - 1 empty archive (production-style use case: no existing
        #     three_ps yet — we want to see what the bake-off produces).
        #   - 1 populated archive (baseline-comparator use case: an
        #     existing three_ps from the old sampled-input prompt to
        #     contrast against the new full-transcript output).
        #   - rest from non-subagent live + remaining archive, randomly
        #     (so a representative slice of recent real work appears).
        # Sub-agent transcripts are last-resort filler — Shawn's spec
        # flags them as "typically less substantive".
        # If a tier is empty (e.g., no populated longs sometimes), we
        # fall through to the next preference tier.
        empties = [
            s for s in pool
            if s.three_ps_state == "empty"
            and s.candidate.source == "archive"
        ]
        populated = [
            s for s in pool
            if s.three_ps_state == "populated"
            and s.candidate.source == "archive"
        ]
        main_live = [
            s for s in pool if s.candidate.source == "live"
        ]
        subagent = [s for s in pool if s.candidate.source == "subagent"]
        rng.shuffle(empties)
        rng.shuffle(populated)
        rng.shuffle(main_live)
        rng.shuffle(subagent)

        bin_picks: list[Scored] = []
        if empties:
            bin_picks.append(empties.pop(0))
        if populated and len(bin_picks) < target:
            bin_picks.append(populated.pop(0))

        # Fill remainder from a unified preference order:
        #   main-live → remaining empties → remaining populated → subagent
        remaining = main_live + empties + populated + subagent
        while len(bin_picks) < target and remaining:
            bin_picks.append(remaining.pop(0))

        picks.extend(bin_picks)

    return picks


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------


def write_manifest(picks: list[Scored], pool_stats: dict) -> dict:
    """Write the manifest JSON and return the in-memory object."""
    sessions_out = []
    for s in picks:
        c = s.candidate
        sessions_out.append({
            "session_id": c.session_id,
            "project": c.project,
            "transcript_path": c.transcript_path,
            "meta_path": c.meta_path,  # None becomes JSON null
            "content_tokens": s.content_tokens,
            "bin": s.bin_label,
            "current_three_ps_state": s.three_ps_state,
            "source": c.source,
            "started_at": c.started_at,
        })

    # Bin stats for the manifest header.
    bin_counts: dict[str, int] = {b: 0 for b in BINS}
    state_counts: dict[str, int] = {"empty": 0, "populated": 0, "unknown": 0}
    total_tokens = 0
    for s in picks:
        bin_counts[s.bin_label] = bin_counts.get(s.bin_label, 0) + 1
        state_counts[s.three_ps_state] += 1
        total_tokens += s.content_tokens

    manifest = {
        # Stamp the moment of generation. Hardcoding a date (the previous
        # value was "2026-05-17") makes the provenance trail dishonest the
        # next time the script runs.
        "generated_at": datetime.datetime.now(
            tz=datetime.timezone.utc
        ).isoformat(),
        "rng_seed": RNG_SEED,
        "extractor": "scripts/extract-transcript-text.py",
        "token_estimator": "chars / 4",
        "haiku_context_cap_tokens": HAIKU_CAP_TOKENS,
        "bins": {
            "short":  {"min": MIN_TOKENS,  "max": BINS["short"][1],  "count": bin_counts["short"]},
            "medium": {"min": BINS["medium"][0], "max": BINS["medium"][1], "count": bin_counts["medium"]},
            "long":   {"min": BINS["long"][0],   "max": BINS["long"][1],   "count": bin_counts["long"]},
        },
        "totals": {
            "sessions": len(picks),
            "content_tokens": total_tokens,
            "empty_state": state_counts["empty"],
            "populated_state": state_counts["populated"],
            "unknown_state_live": state_counts["unknown"],
        },
        "pool_stats": pool_stats,
        "notes": (
            f"Re-sampled "
            f"{datetime.datetime.now(tz=datetime.timezone.utc).date().isoformat()} "
            "to cap distilled-text tokens at 190K so "
            "every session fits Haiku 4.5's 200K context window (200K minus "
            "~3K for prompt + header + output budget, plus safety buffer for "
            "the chars/4 heuristic's known under-counting of dense content). "
            "Stratified random with random.seed(42); >1,000-token floor "
            "applied (raised from the original >100 floor to weed out tiny "
            "live sub-agent invocations). Within each bin the algorithm "
            "first takes one archived empty-state session (best-effort empty "
            "inclusion), then one archived populated session (baseline "
            "comparator value — its existing three_ps was produced by the "
            "old sampled-input prompt and serves as a contrast for the new "
            "full-transcript outputs), then fills the remainder from a "
            "preference order of main-live → remaining empties → remaining "
            "populated → sub-agent. Sub-agent transcripts (flagged via "
            "source='subagent') are included only as last-resort filler "
            "because they tend to be less substantive. Live transcripts "
            "have no session.meta.json yet so their three_ps state is "
            "'unknown' — they become bake-off inputs without a baseline "
            "comparator. Sessions are deduplicated by session_id across "
            "archive and live pools; archive copies (which carry meta) "
            "preferred when both exist."
        ),
        "sessions": sessions_out,
    }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    extractor = _load_extractor()

    print("Enumerating archive candidates …")
    arch = enumerate_archive_candidates()
    print(f"  archive transcripts (non-LFS): {len(arch)}")

    print("Enumerating live candidates …")
    live = enumerate_live_candidates()
    print(f"  live transcripts (non-LFS): {len(live)}")
    n_subagent = sum(1 for c in live if c.source == "subagent")
    n_main = len(live) - n_subagent
    print(f"    main: {n_main}   sub-agent: {n_subagent}")

    # Deduplicate by session_id. When the same session_id appears in both
    # the archive and the live pool (or any other duplication), keep the
    # archived copy first because it ships with a session.meta.json. Falling
    # back to the live copy only if no archive copy exists.
    #
    # Sort the combined list by (session_id, transcript_path) before
    # bucketing so the ``random.seed(42)`` shuffle downstream is
    # reproducible regardless of dict-key insertion order or filesystem
    # traversal order across machines.
    raw_combined = sorted(
        arch + live,
        key=lambda c: (c.session_id or "", c.transcript_path),
    )
    n_before_dedup = len(raw_combined)
    seen_ids: set[str] = set()
    all_candidates: list[Candidate] = []
    for c in raw_combined:
        # session_id of None or empty string falls back to a path-based key
        # so we still dedup duplicate paths.
        key = c.session_id or c.transcript_path
        if key in seen_ids:
            continue
        seen_ids.add(key)
        all_candidates.append(c)
    n_dedup_removed = n_before_dedup - len(all_candidates)
    total_pool = len(all_candidates)
    print(f"  deduplicated by session_id (removed {n_dedup_removed} copies)")
    print(f"Total unique candidate pool: {total_pool}")

    print("Extracting and scoring (this may take a few minutes) …")
    scored = extract_and_score(all_candidates, extractor)
    n_passed_floor = len(scored)
    print(f"  passed >{MIN_TOKENS}-token floor: {n_passed_floor}")

    n_in_haiku_range = sum(1 for s in scored if s.bin_label is not None)
    n_over_cap = sum(
        1 for s in scored if s.content_tokens > HAIKU_CAP_TOKENS
    )
    print(f"  fit under {HAIKU_CAP_TOKENS:,}-token cap: {n_in_haiku_range}")
    print(f"  over cap (excluded): {n_over_cap}")

    # Per-bin pool sizes.
    by_bin: dict[str, int] = {b: 0 for b in BINS}
    for s in scored:
        if s.bin_label:
            by_bin[s.bin_label] += 1
    print("  per-bin pool sizes:")
    for b in ("short", "medium", "long"):
        print(f"    {b}: {by_bin[b]}")

    # Empty pool sizes (archived only).
    empty_by_bin: dict[str, int] = {b: 0 for b in BINS}
    for s in scored:
        if s.bin_label and s.three_ps_state == "empty":
            empty_by_bin[s.bin_label] += 1
    print("  per-bin archived-empty pool sizes:")
    for b in ("short", "medium", "long"):
        print(f"    {b}: {empty_by_bin[b]}")

    pool_stats = {
        "total_candidate_paths": total_pool,
        "archive_paths": len(arch),
        "live_paths_main": n_main,
        "live_paths_subagent": n_subagent,
        "passed_token_floor": n_passed_floor,
        "fit_under_haiku_cap": n_in_haiku_range,
        "over_haiku_cap": n_over_cap,
        "per_bin_pool": by_bin,
        "per_bin_empty_archived": empty_by_bin,
    }

    print("\nStratified sampling …")
    picks = stratified_sample(scored)
    print(f"  selected {len(picks)} sessions")

    manifest = write_manifest(picks, pool_stats)
    print(f"\nManifest written to {MANIFEST_PATH}")

    print("\nSelected sessions:")
    for s in picks:
        c = s.candidate
        print(
            f"  [{s.bin_label}] {s.content_tokens:>7,}t  "
            f"{c.source:<8}  {s.three_ps_state:<10}  "
            f"{c.project[:30]:<30}  {c.session_id[:8]}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
