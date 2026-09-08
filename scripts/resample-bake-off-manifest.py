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
6. Stratified random selection with a seeded RNG (``--seed``, default 42).

Output
------
The manifest path is an explicit ``--out`` argument with no default. It used
to be a module constant pointing straight at the canonical manifest in the
private data submodule, which meant *any* invocation — from any copy of the
script, from any working directory — overwrote the manifest the committed
bake-off responses were generated against. The write is now temp-plus-replace
and refuses an existing file unless ``--force`` is given.

Usage
-----
::

    venv/bin/python3 scripts/resample-bake-off-manifest.py --dry-run
    venv/bin/python3 scripts/resample-bake-off-manifest.py \\
        --out /path/to/sample-manifest.json --seed 42

``--dry-run`` enumerates, scores, samples, and prints the plan without
writing anything. ``--archive-root`` and ``--live-root`` (both defaulting to
``Path.home()``) relocate the two candidate pools, which is what makes the
script testable against a synthetic tree.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import importlib.util
import json
import os
import random
import re
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Derived from ``__file__`` rather than hardcoded: a copy of the repository
# (a git worktree, a clone on another machine) must resolve its OWN sibling
# scripts, not the operator's checkout.
PA_DIR = Path(__file__).resolve().parent.parent

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

DEFAULT_RNG_SEED = 42

# Git-LFS pointer stubs start with this line; we detect them and skip.
LFS_POINTER_RE = re.compile(rb"^version https://git-lfs\.github\.com/spec/")

# Glob patterns are stored RELATIVE to a root so the two pools can be
# redirected (``--live-root`` / ``--archive-root``). Both default to
# ``Path.home()``, which reproduces the previous hardcoded absolute paths on
# the operator's machine while letting a test point them at a tmp tree.
#
# Live transcripts have no meta.json. Sub-agent transcripts live one level
# deeper: ``.claude/projects/<proj>/<session-id>/subagents/<agent>.jsonl``.
LIVE_GLOB_TEMPLATES = (
    ".claude/projects/*/*.jsonl",
    ".claude/projects/*/*/subagents/*.jsonl",
)

# Archive patterns (these typically have a session.meta.json sibling).
ARCHIVE_GLOB_TEMPLATES = (
    "cc-archives/*/*/session.jsonl",
    "cc-archives/*/*/session.jsonl.gz",
    "Code/*/archive/cc-sessions/*/*/session.jsonl",
    "Code/*/archive/cc-sessions/*/*/session.jsonl.gz",
    "personal-assistant/archive/cc-sessions/*/*/session.jsonl",
    "personal-assistant/archive/cc-sessions/*/*/session.jsonl.gz",
)


def archive_globs(root: Path) -> list[str]:
    """Return the archive glob patterns rooted at ``root``."""
    return [str(root / template) for template in ARCHIVE_GLOB_TEMPLATES]


def live_globs(root: Path) -> list[str]:
    """Return the live-transcript glob patterns rooted at ``root``."""
    return [str(root / template) for template in LIVE_GLOB_TEMPLATES]


class ManifestExistsError(RuntimeError):
    """The requested ``--out`` path already holds a manifest."""


# ---------------------------------------------------------------------------
# Extractor import
# ---------------------------------------------------------------------------


def _load_extractor():
    """Import the sibling scripts/extract-transcript-text.py as a module."""
    path = Path(__file__).with_name("extract-transcript-text.py")
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


def enumerate_archive_candidates(patterns: list[str]) -> list[Candidate]:
    """Walk the given archive globs; one Candidate per non-LFS transcript.

    ``glob.glob`` returns filesystem-order results, which differ across
    machines, so each call is wrapped in ``sorted(...)`` to make the
    enumeration order deterministic. This matters because the downstream
    seeded shuffle is only reproducible if the input list is identical
    across runs.

    Args:
        patterns: absolute glob patterns, normally from ``archive_globs``.
    """
    seen_paths: set[str] = set()
    out: list[Candidate] = []
    for pattern in patterns:
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


def enumerate_live_candidates(patterns: list[str]) -> list[Candidate]:
    """Walk the given live-transcript globs (normally under ``.claude/``).

    Wraps ``glob.glob`` in ``sorted(...)`` for deterministic order across
    machines — see ``enumerate_archive_candidates`` for the rationale.

    Args:
        patterns: absolute glob patterns, normally from ``live_globs``.
    """
    seen_paths: set[str] = set()
    out: list[Candidate] = []
    for pattern in patterns:
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
# Deduplication
# ---------------------------------------------------------------------------

#: Which copy of a dual-resident session wins. The archive tier is first
#: because it is the only tier that ships a ``session.meta.json``, and that
#: file is where ``started_at``, the authoritative project name, and the
#: ``three_ps`` state come from. A sub-agent transcript is last: Shawn's spec
#: flags those as "typically less substantive".
SOURCE_PREFERENCE: dict[str, int] = {"archive": 0, "live": 1, "subagent": 2}


def deduplicate_candidates(
    candidates: list[Candidate],
) -> tuple[list[Candidate], int]:
    """Keep one Candidate per session id, preferring the archived copy.

    The previous sort key was ``(session_id, transcript_path)``, which put
    ``/home/shawn/.claude/...`` before ``/home/shawn/cc-archives/...``
    because ``'.' < 'c'``. Every session resident in both pools therefore
    entered the sample as ``source="live"`` with ``meta_path=None`` and
    ``three_ps_state="unknown"`` — the opposite of the documented intent,
    and enough to drop it out of both the empty and the populated tier of
    the stratified sampler.

    Sorting by ``(session_id, source_rank, transcript_path)`` is also what
    makes the downstream seeded shuffle reproducible: neither dict insertion
    order nor filesystem traversal order can reach it.

    Args:
        candidates: the combined archive and live pools, in any order.

    Returns:
        ``(unique_candidates, n_removed)``.
    """
    ordered = sorted(
        candidates,
        key=lambda c: (
            c.session_id or "",
            SOURCE_PREFERENCE.get(c.source, len(SOURCE_PREFERENCE)),
            c.transcript_path,
        ),
    )
    seen_keys: set[str] = set()
    unique: list[Candidate] = []
    for candidate in ordered:
        # A session_id of None or empty string falls back to a path-based
        # key, so duplicate paths are still collapsed.
        key = candidate.session_id or candidate.transcript_path
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(candidate)
    return unique, len(ordered) - len(unique)


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


def stratified_sample(
    scored: list[Scored], *, seed: int = DEFAULT_RNG_SEED
) -> list[Scored]:
    """Pick TARGET_COUNTS per bin, prioritising empty-state archived sessions.

    Within each bin, the selection prefers:
      1. Sessions whose meta marks three_ps as ``empty`` (best-effort empty
         inclusion per the spec — at least 1–2 empties wanted overall).
      2. Then everything else (populated archive + live + subagent), randomly.

    This is deliberately not pure random across the whole bin — Shawn asked
    for best-effort empty inclusion, and empties are rarer in the live pool.

    Args:
        scored: every scored candidate, in any order.
        seed: the RNG seed, recorded in the manifest so a run is repeatable.
    """
    rng = random.Random(seed)
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


def write_json_atomic(path: Path, payload: dict) -> None:
    """Serialise ``payload`` to a sibling temp file, then ``os.replace`` it.

    A crash (or a full disk) part-way through a plain ``write_text`` leaves a
    truncated manifest where a valid one used to be. Writing beside the
    target and renaming makes the replacement atomic on POSIX: readers see
    either the old file or the new one, never half of either.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def build_manifest(
    picks: list[Scored],
    pool_stats: dict,
    *,
    seed: int,
    generated_at: datetime.datetime,
) -> dict:
    """Assemble the manifest object without touching the filesystem.

    Split out from the writer so a dry run can print exactly what a real run
    would have persisted, and so a test can compare two runs byte for byte.

    Args:
        picks: the sampled sessions, in selection order.
        pool_stats: the candidate-pool counts recorded in the header.
        seed: the RNG seed actually used, recorded for reproducibility.
        generated_at: a single timestamp used for both the ``generated_at``
            field and the date in ``notes`` — one clock reading, so a run
            that straddles midnight cannot disagree with itself.
    """
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
        "generated_at": generated_at.isoformat(),
        "rng_seed": seed,
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
            f"Re-sampled {generated_at.date().isoformat()} "
            "to cap distilled-text tokens at 190K so "
            "every session fits Haiku 4.5's 200K context window (200K minus "
            "~3K for prompt + header + output budget, plus safety buffer for "
            "the chars/4 heuristic's known under-counting of dense content). "
            f"Stratified random with random.seed({seed}); >1,000-token floor "
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

    return manifest


def write_manifest(
    picks: list[Scored],
    pool_stats: dict,
    out_path: Path,
    *,
    seed: int,
    generated_at: datetime.datetime,
    force: bool = False,
) -> dict:
    """Build the manifest and persist it to ``out_path``; return the object.

    Raises:
        ManifestExistsError: ``out_path`` exists and ``force`` is False. The
            committed bake-off responses were generated against a particular
            manifest, so silently replacing one destroys the only link
            between those responses and the sessions that produced them.
    """
    if out_path.exists() and not force:
        raise ManifestExistsError(
            f"{out_path} already exists. Re-sampling would break the link "
            "between the existing manifest and any responses generated "
            "against it; pass --force to replace it deliberately."
        )
    manifest = build_manifest(
        picks, pool_stats, seed=seed, generated_at=generated_at
    )
    write_json_atomic(out_path, manifest)
    return manifest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_as_of(value: str) -> datetime.datetime:
    """Parse ``--as-of`` as an ISO date or datetime; naive values are UTC.

    Raises:
        argparse.ArgumentTypeError: the value is not ISO 8601.
    """
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--as-of must be an ISO 8601 date or datetime, not {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    """Return the command-line parser.

    ``--out`` deliberately has no default: the previous module-level constant
    pointed at the canonical manifest, so running the script at all — even
    from a scratch copy, even to see what it would pick — destroyed it.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Re-sample the bake-off manifest with a 190K-token, "
            "Haiku-compatible cap."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Where to write the manifest JSON. Required unless --dry-run; "
            "refuses to replace an existing file unless --force."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate, score, and sample, then print the plan. Writes nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow --out to replace an existing manifest.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RNG_SEED,
        help=(
            f"RNG seed for the stratified sample (default {DEFAULT_RNG_SEED}); "
            "recorded in the manifest as rng_seed."
        ),
    )
    parser.add_argument(
        "--as-of",
        type=parse_as_of,
        default=None,
        help=(
            "Pin the generation timestamp (ISO date or datetime, UTC when "
            "naive) instead of reading the clock. With the same --seed and "
            "the same candidate pool, two runs then produce byte-identical "
            "manifests, which is what makes a re-sample auditable."
        ),
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path.home(),
        help="Root the archive globs are resolved against (default: ~).",
    )
    parser.add_argument(
        "--live-root",
        type=Path,
        default=Path.home(),
        help="Root the live-transcript globs are resolved against (default: ~).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Enumerate, score, sample, and either print the plan or write it."""
    args = build_arg_parser().parse_args(argv)
    if args.out is None and not args.dry_run:
        print(
            "--out is required unless --dry-run is given (there is no default "
            "output path: the previous default overwrote the canonical "
            "manifest on every run).",
            file=sys.stderr,
        )
        return 2

    extractor = _load_extractor()

    print("Enumerating archive candidates …")
    arch = enumerate_archive_candidates(archive_globs(args.archive_root))
    print(f"  archive transcripts (non-LFS): {len(arch)}")

    print("Enumerating live candidates …")
    live = enumerate_live_candidates(live_globs(args.live_root))
    print(f"  live transcripts (non-LFS): {len(live)}")
    n_subagent = sum(1 for c in live if c.source == "subagent")
    n_main = len(live) - n_subagent
    print(f"    main: {n_main}   sub-agent: {n_subagent}")

    all_candidates, n_dedup_removed = deduplicate_candidates(arch + live)
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
    picks = stratified_sample(scored, seed=args.seed)
    print(f"  selected {len(picks)} sessions")

    # One clock reading for the whole manifest — see ``build_manifest`` —
    # or the pinned value, which makes the whole run reproducible.
    generated_at = args.as_of or datetime.datetime.now(tz=datetime.timezone.utc)
    if args.dry_run:
        manifest = build_manifest(
            picks, pool_stats, seed=args.seed, generated_at=generated_at
        )
        print(
            f"\nDRY RUN — nothing written. A real run would write "
            f"{len(manifest['sessions'])} sessions "
            f"({manifest['totals']['content_tokens']:,} distilled tokens) "
            f"to {args.out if args.out else '<--out>'}."
        )
    else:
        try:
            write_manifest(
                picks, pool_stats, args.out,
                seed=args.seed, generated_at=generated_at, force=args.force,
            )
        except ManifestExistsError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 2
        print(f"\nManifest written to {args.out}")

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
