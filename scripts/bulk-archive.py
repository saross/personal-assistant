#!/usr/bin/env python3
"""
Bulk archive historical Claude Code sessions.

Phase 2 of the progressive disclosure system. Archives unarchived sessions
from ~/.claude/projects/ into ~/cc-archives/, optionally enriches them
with Haiku-generated metadata via the Anthropic Batch API, and verifies
archive integrity.

Usage:
    python3 scripts/bulk-archive.py discover [--min-content-chars N]
    python3 scripts/bulk-archive.py archive [--dry-run] [--limit N] [--force]
    python3 scripts/bulk-archive.py enrich --batch-submit [--limit N]
    python3 scripts/bulk-archive.py enrich --batch-apply BATCH_ID
    python3 scripts/bulk-archive.py subagents [--dry-run]
    python3 scripts/bulk-archive.py verify [--fix-catalogue]

Modes:
    discover        Scan for unarchived sessions, build manifest, report stats
    archive         Compress and archive sessions (no API calls)
    enrich          Generate metadata via Terra or the Haiku Batch API
    subagents       Backfill orphan subagent transcripts into their parents
    verify          Integrity checks and catalogue rebuild

``archive`` resumes from its checkpoint by default — there is no --resume
flag, and the docstring claimed one until 2026-09-08 (audit finding AR19).
Entries the checkpoint claims are re-verified against disk before they are
skipped; see cmd_archive.
"""

import argparse
import fcntl
import gzip
import importlib.util
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Per-machine OpenAI key resolution (2026-08-22): paid keys are issued per
# machine, so the variable name carries a host suffix.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _openai_key import resolve_openai_key  # noqa: E402
from _log_dir import ensure_log_dir  # noqa: E402
from _batch_state import load_state, save_state  # noqa: E402
# The ONE substantive-session predicate, shared with check-archive-drift.py so
# that the drift gate's remediation command archives exactly what it reported
# (audit 2026-09-08, finding AR1). See scripts/_archive_substance.py.
from _archive_substance import (  # noqa: E402
    GRACE_HOURS,
    MIN_CONTENT_CHARS,
    is_substantive,
    session_content_chars,
    within_grace,
)

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PA_DIR / ".env"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "bulk-archive.log"
MANIFEST_FILE = LOG_DIR / "bulk-archive-manifest.json"
CHECKPOINT_FILE = LOG_DIR / "bulk-archive-progress.json"
BATCH_STATE_FILE = LOG_DIR / "bulk-enrich-batch-state.json"
# One state file per batch id (audit AR18): the Batch API takes up to 24
# hours, so a second submit before the first is applied used to overwrite the
# only map that says which archive entry each reply belongs to.
BATCH_STATE_DIR = LOG_DIR / "bulk-enrich-batch-state"

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_ARCHIVE_ROOT = Path.home() / "cc-archives"
CATALOGUE_FILE = DEFAULT_ARCHIVE_ROOT / "CATALOG.json"

HAIKU_MODEL = "claude-haiku-4-5-20251001"

# OpenAI GPT-5.6 Terra, chosen 2026-07-28 after a blinded five-arm bake-off
# (Terra 38/60 overall, 27/30 on long sessions — and the corpus is long).
# Prices are USD per million tokens, verified 2026-07-28 against
# https://developers.openai.com/api/docs/pricing. The Flex service tier is
# -50% on both input and output, and this adapter always requests Flex, so
# the effective rates are half the numbers below.
TERRA_MODEL = "gpt-5.6-terra"
TERRA_INPUT_PRICE_PER_MTOK = 2.50
TERRA_OUTPUT_PRICE_PER_MTOK = 15.00
TERRA_FLEX_DISCOUNT = 0.50

# Substance floor below which a session carries no metadata worth generating.
# Sessions under it are `/clear`- or `/exit`-only invocations, aborted starts,
# or two-turn trivia: verified by inspection 2026-07-28, where a recurring
# *exact* 64-token extract turned out to be the local-command caveat
# boilerplate and nothing else. This is now the SAME floor discovery and the
# drift gate use — `MIN_CONTENT_CHARS` from `_archive_substance`, quoted in
# tokens here because the enrich help text and cost projections speak tokens.
MIN_CONTENT_TOKENS = MIN_CONTENT_CHARS // 4

# Estimated tokens per lightweight enrichment request.
# Based on progressive-disclosure-plan.md: ~12M tokens total / 603 sessions.
EST_TOKENS_PER_SESSION = 20_000

# Cost per million tokens (Haiku input, batch pricing = 50% of standard).
# Standard: $0.80/M input, $4/M output.  Batch: $0.40/M input, $2/M output.
BATCH_INPUT_COST_PER_M = 0.40
BATCH_OUTPUT_COST_PER_M = 2.00
EST_OUTPUT_TOKENS_PER_SESSION = 200


# ============================================================================
# Environment and logging
# ============================================================================


def load_env() -> None:
    """Load environment variables from the project .env file."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def setup_logging() -> logging.Logger:
    """Configure file and console logging."""
    ensure_log_dir(LOG_DIR)
    logger = logging.getLogger("bulk-archive")
    logger.setLevel(logging.INFO)

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    return logger


# ============================================================================
# Project mapping — resolve encoded project dirs to real paths
# ============================================================================


def ensure_toolkit_on_path() -> Path:
    """Put ``cc_session_toolkit``'s source on ``sys.path`` and return it.

    Four call sites used to carry their own copy of these three lines, and
    ``_enrich_terra`` carried none — it worked only because
    ``_make_token_counter`` happened to run first and had already done it, a
    dependency nothing stated and nothing tested (audit round 4c-2, finding
    15; AR15 was the same defect, one call site over).
    """
    toolkit_src = Path.home() / "Code" / "cc-session-toolkit" / "src"
    if str(toolkit_src) not in sys.path:
        sys.path.insert(0, str(toolkit_src))
    return toolkit_src


def _extract_cwd_from_jsonl(session_path: Path) -> str | None:
    """
    Extract the working directory from the first entries of a session JSONL.

    Reads up to 200 lines looking for a ``cwd`` field in the message
    entries. Returns the first ``cwd`` found, or None.
    """
    try:
        with open(session_path, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= 200:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # cwd can appear at top level or inside message
                cwd = entry.get("cwd")
                if cwd:
                    return cwd
    except (OSError, UnicodeDecodeError):
        pass
    return None


def _reconstruct_path_from_encoded(encoded: str) -> Path | None:
    """
    Attempt to reconstruct a real path from the encoded project dir name.

    The encoding replaces '/' with '-', so '-home-shawn-Code-map-reader-llm'
    becomes '/home/shawn/Code/map-reader-llm'. Since hyphens appear in real
    directory names, we try progressively splitting and checking existence.
    """
    # Simple approach: replace leading dash, then try splitting at each dash
    # and checking if the resulting path exists
    if not encoded.startswith("-"):
        return None

    # Direct reconstruction: replace - with /
    candidate = Path("/" + encoded[1:].replace("-", "/"))
    if candidate.is_dir():
        return candidate

    # Try common patterns — the encoded name is the full path with / → -
    # For names with hyphens in dirs, we need to be smarter
    parts = encoded[1:].split("-")
    # Build path incrementally, trying to match existing directories
    current = Path("/")
    remaining = parts[:]

    while remaining:
        # Try joining progressively more parts with hyphens
        found = False
        for end in range(len(remaining), 0, -1):
            segment = "-".join(remaining[:end])
            candidate = current / segment
            if candidate.is_dir():
                current = candidate
                remaining = remaining[end:]
                found = True
                break
        if not found:
            # Can't resolve further
            return None

    return current if current != Path("/") else None


def _make_token_counter(logger: logging.Logger):
    """Return a ``Path -> int`` distilled-token counter, or ``None``.

    Reuses ``scripts/extract-transcript-text.py`` — the same distiller the
    metadata prompt is fed from — so the discovery floor is measured on
    exactly the text the extractor model will see, not on raw JSONL bytes.
    Raw bytes are a bad proxy: an aborted session carrying one 55 KB injected
    attachment distils to 256 characters of boilerplate.

    Token estimator is ``chars / 4``, matching the bake-off manifests. It runs
    ~11% under a real tokenizer (measured against the 2026-07-28 Terra usage
    records), which is the safe direction for a floor.
    """
    extractor_path = Path(__file__).with_name("extract-transcript-text.py")
    try:
        spec = importlib.util.spec_from_file_location(
            "extract_transcript_text", str(extractor_path)
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {extractor_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.error(
            "Could not load transcript extractor (%s): %s", extractor_path, exc
        )
        sys.exit(1)

    def count(jsonl_file: Path) -> int:
        try:
            return max(1, len(module.extract_transcript_text(str(jsonl_file))) // 4)
        except Exception as exc:
            logger.warning("Distillation failed for %s: %s", jsonl_file, exc)
            return 0

    return count


def _source_machine_of(jsonl_file: Path) -> str:
    """Best-effort label for which machine's store a transcript came from.

    In the merged-snapshot layout the machine name is the grandparent
    directory (``<root>/<machine>/<cwd-key>/x.jsonl``). In the live layout
    there is no machine level, so report ``"local"``.
    """
    parts = jsonl_file.parts
    if len(parts) >= 3 and parts[-2].startswith("-"):
        candidate = parts[-3]
        return "local" if candidate == "projects" else candidate
    return "local"


#: A directory named like a session UUID is a session's own subdirectory
#: (holding ``subagents/``), never a project key or a machine name.
_UUID_DIR_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def detect_source_layout(
    source_root: Path,
    logger: logging.Logger,
    layout: str = "auto",
) -> str:
    """Return ``"live"`` or ``"snapshot"`` for *source_root*, or exit.

    The old probe was a single negation: "no child holds ``*.jsonl`` at scan
    time, therefore this is a merged snapshot". That is false in the one case
    it matters — a live store whose sessions happen to sit in per-session
    subdirectories, or a store scanned at a moment when no project directory
    holds a top-level transcript. Every session-UUID directory was then read
    as a *project key*, and the run proceeded silently under a completely
    wrong idea of the tree (audit 2026-09-08, finding AR10).

    So the probe now has to see positive evidence for whichever layout it
    reports, and says which:

    * **live** — some child directory holds ``*.jsonl`` directly.
    * **snapshot** — no child does, and every non-empty child holds
      project-key directories (the leading-dash encoding).

    Anything else is ambiguous, and an ambiguous store is a refusal with the
    remedy named, not a guess. ``--layout live|snapshot`` overrides the probe
    outright for the case the operator knows better.
    """
    if layout in ("live", "snapshot"):
        logger.info("Source %s: layout forced to %s", source_root, layout)
        return layout

    children = [child for child in sorted(source_root.iterdir())
                if child.is_dir()]
    if any(any(child.glob("*.jsonl")) for child in children):
        return "live"

    uuid_named = [child.name for child in children if _UUID_DIR_RE.match(child.name)]
    project_keyed = [
        child for child in children
        if any(g.is_dir() and g.name.startswith("-") for g in child.iterdir())
    ]

    # A live store whose project directories hold no top-level *.jsonl right
    # now — every session archived and its transcript rotated away — is still
    # a live store, and check-archive-drift.py reads it happily and reports
    # Clean. Refusing here while the gate says Clean is an inconsistency the
    # operator has to resolve by hand, over a tree that is in fact fine
    # (round 4c-2, finding 13). The leading-dash encoding is what makes a
    # project key recognisable, so children that all look like project keys
    # are a live store even when empty.
    if children and all(child.name.startswith("-") for child in children):
        logger.info(
            "Source %s: live layout (%d project directories, none holding a "
            "transcript right now)", source_root, len(children),
        )
        return "live"

    if uuid_named or (children and not project_keyed):
        logger.error(
            "Cannot tell what %s is: no project directory holds a "
            "transcript, and its children do not look like machine "
            "directories%s. Refusing to guess — pass --layout live or "
            "--layout snapshot.",
            source_root,
            (
                f" ({len(uuid_named)} are session-UUID directories, which are "
                "never projects)" if uuid_named else ""
            ),
        )
        sys.exit(2)
    return "snapshot"


def iter_source_project_dirs(
    source_root: Path,
    logger: logging.Logger,
    layout: str = "auto",
) -> list[tuple[str, Path]]:
    """Yield ``(encoded_cwd_key, project_dir)`` pairs from a transcript store.

    Two layouts are supported, detected rather than configured:

    **Live layout** — ``<root>/<cwd-key>/*.jsonl``, i.e. ``~/.claude/projects``.

    **Merged-snapshot layout** — ``<root>/<machine>/<cwd-key>/*.jsonl``, as
    produced by the 2026-07-28 raw containment snapshot. This matters because
    the two machines' stores are disjoint in practice: of the 77 backfillable
    sessions found on 2026-07-28, **55 existed only on zbook**, so a run against
    amd-tower's live store would have silently archived 22 of 77 and reported
    success. Retrieval is raw-first for exactly this reason.

    The same cwd-key appearing under several machines is merged, and a session
    present on both is taken from whichever copy is larger — 14 of the copies
    quarantined during the 2026-07-28 consolidation had 0-byte transcripts, so
    "largest wins" is the evidence-backed tie-break, not an arbitrary one.
    """
    if not source_root.is_dir():
        logger.warning("Source root not found: %s", source_root)
        return []

    # A live store's children hold *.jsonl directly; a snapshot's children are
    # machine directories whose grandchildren do. The probe demands positive
    # evidence either way and refuses when it has none (AR10).
    is_snapshot = detect_source_layout(source_root, logger, layout) == "snapshot"

    if not is_snapshot:
        pairs = [
            (d.name, d) for d in sorted(source_root.iterdir()) if d.is_dir()
        ]
        logger.info(
            "Source %s: live layout, %d project dirs", source_root, len(pairs)
        )
        return pairs

    merged: dict[str, list[Path]] = {}
    for machine_dir in sorted(source_root.iterdir()):
        if not machine_dir.is_dir():
            continue
        for proj_dir in sorted(machine_dir.iterdir()):
            if proj_dir.is_dir():
                merged.setdefault(proj_dir.name, []).append(proj_dir)

    logger.info(
        "Source %s: merged-snapshot layout, %d project dirs across %d machines",
        source_root, len(merged),
        len([d for d in source_root.iterdir() if d.is_dir()]),
    )
    # Return every (key, dir) pair; de-duplication by session id happens in
    # discover_sessions, which can compare file sizes across the copies.
    return [(key, d) for key, dirs in sorted(merged.items()) for d in dirs]


def archived_session_ids_on_disk(
    archive_root: Path,
    logger: logging.Logger,
) -> set[str]:
    """Collect archived session ids by walking ``session.meta.json`` on disk.

    **Why not just read CATALOG.json:** the catalogue under-reports badly. On
    2026-07-28 it held 539 entries against 728 distinct session ids present on
    disk — 189 sessions archived but uncatalogued. Deduplicating discovery
    against the catalogue alone would therefore re-archive those 189, which is
    precisely the double-archiving-with-divergent-titles defect the archive was
    just repaired for. Disk is authoritative; the catalogue is a derived index
    and is regenerated by ``verify --fix-catalogue``.
    """
    ids: set[str] = set()
    for meta_path in archive_root.rglob("session.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Unreadable metadata at %s: %s", meta_path, exc)
            continue
        session_id = (meta.get("session") or {}).get("id")
        if session_id:
            ids.add(session_id)
    logger.info("Found %d archived session ids on disk", len(ids))
    return ids


def resolve_project_mapping(
    logger: logging.Logger,
    source_pairs: list[tuple[str, Path]] | None = None,
) -> dict[str, tuple[Path | None, str]]:
    """
    Build a mapping from encoded project directory names to (project_root,
    project_name) tuples.

    Strategy: for each project dir in the source store, find a session
    JSONL and extract ``cwd``. Falls back to path reconstruction from the
    encoded name. When neither succeeds, ``project_root`` is ``None`` —
    the call site must consult ``archive_root`` instead of treating any
    fallback path as a real project directory.

    ``source_pairs`` comes from :func:`iter_source_project_dirs`; when omitted
    the live store is used, preserving the original behaviour.

    Returns:
        Dictionary mapping encoded dir name to (project_root, project_name).
        ``project_root`` may be ``None`` if it could not be resolved.
    """
    mapping: dict[str, tuple[Path | None, str]] = {}

    if source_pairs is None:
        source_pairs = iter_source_project_dirs(CLAUDE_PROJECTS_DIR, logger)
    if not source_pairs:
        return mapping

    for encoded, proj_dir in source_pairs:
        # The same cwd-key can appear once per machine in a merged snapshot;
        # the first resolution wins because cwd is a property of the key.
        if encoded in mapping and mapping[encoded][0] is not None:
            continue
        project_root: Path | None = None
        project_name: str = "unknown"

        # Strategy 1: extract cwd from a session JSONL
        for jsonl_file in proj_dir.glob("*.jsonl"):
            if jsonl_file.name.startswith("agent-"):
                continue
            cwd = _extract_cwd_from_jsonl(jsonl_file)
            if cwd:
                project_root = Path(cwd)
                break

        # Strategy 2: reconstruct from encoded name
        if project_root is None:
            project_root = _reconstruct_path_from_encoded(encoded)

        if project_root is not None:
            # Derive project name from directory basename
            project_name = project_root.name
        else:
            # Last resort: use the encoded name, cleaned up
            project_name = encoded.lstrip("-").split("-")[-1]
            logger.warning(
                "Could not resolve project root for %s — using name %r",
                encoded, project_name,
            )

        # Audit 2026-05-02 E-Medium: previous code used `Path("/tmp")` as
        # an unresolved-root sentinel. `/tmp` exists on every Unix host,
        # so the fallback masqueraded as a real project root downstream
        # (the `is_dir()` guard at line ~575 always returned True). Use
        # `None` instead and let the call site take the explicit
        # archive_root branch unambiguously.
        mapping[encoded] = (project_root, project_name)

    logger.info("Resolved %d project directories", len(mapping))
    return mapping


# ============================================================================
# Discovery
# ============================================================================


def read_catalogue_ids(
    catalogue_file: Path,
    logger: logging.Logger,
) -> set[str]:
    """Return the session ids CATALOG.json lists, reporting a corrupt file.

    The toolkit's ``get_archived_session_ids`` swallows ``JSONDecodeError``
    and ``KeyError`` and returns an empty set, so delegating to it made a
    corrupt catalogue indistinguishable from an empty one: the "unreadable"
    warning AR16 promised could never fire, and an operator watching for it
    would never learn the index needed rebuilding (audit round 4c-2,
    finding 5).

    So the parse happens here, where the failure is visible, and the toolkit
    is called only once the file is known to be readable. A corrupt
    catalogue is still not fatal — it is a derived index, and discovery
    deduplicates against disk — but it is now said out loud, with the repair
    named.
    """
    try:
        raw = catalogue_file.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "CATALOG.json cannot be read (%s) — treating it as empty; "
            "rebuild it with `verify --fix-catalogue`", exc,
        )
        return set()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "CATALOG.json is corrupt (%s) — treating it as empty; rebuild "
            "it with `verify --fix-catalogue`", exc,
        )
        return set()
    sessions = parsed.get("sessions") if isinstance(parsed, dict) else None
    if not isinstance(sessions, list):
        logger.warning(
            "CATALOG.json has no 'sessions' list (found %s) — treating it "
            "as empty; rebuild it with `verify --fix-catalogue`",
            type(sessions).__name__,
        )
        return set()
    ids = {
        entry["id"] for entry in sessions
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    malformed = len(sessions) - len(
        [e for e in sessions if isinstance(e, dict) and isinstance(e.get("id"), str)]
    )
    if malformed:
        logger.warning(
            "CATALOG.json holds %d entr%s with no usable session id — "
            "rebuild it with `verify --fix-catalogue`",
            malformed, "y" if malformed == 1 else "ies",
        )
    return ids


def discover_sessions(
    project_mapping: dict[str, tuple[Path | None, str]],
    min_turns: int,
    logger: logging.Logger,
    source_pairs: list[tuple[str, Path]] | None = None,
    min_content_tokens: int = 0,
    min_content_chars: int = MIN_CONTENT_CHARS,
) -> list[dict[str, Any]]:
    """
    Scan for unarchived sessions, filter trivials, build a manifest.

    Deduplicates against archived session ids read from disk (see
    :func:`archived_session_ids_on_disk`) rather than from CATALOG.json, and
    against itself when the same session exists on more than one machine.

    **Triviality test.** The default is the shared substance predicate
    (``_archive_substance.is_substantive``: at least ``min_content_chars``
    characters of user/assistant prose), which is the *same* rule
    ``check-archive-drift.py`` reports on. That agreement is the whole point:
    before 2026-09-08 discovery filtered on turn count while the gate filtered
    on prose, so the gate reported sessions that the command it recommended
    then refused to archive, and no run could ever clear it (audit AR1).

    Two legacy filters remain available, both off unless asked for.
    ``min_content_tokens`` measures the *distilled* transcript through the
    toolkit's extractor; ``min_turns`` counts turns. Turn count is a poor
    proxy for substance — measured on the 2026-07-28 backfill set,
    ``min_turns=5`` discarded 56 of 77 substantive sessions, including a
    205,848-token session that happened to have **two** turns — which is why
    it is no longer the default.

    Returns:
        List of session manifest entries, sorted by project then session ID.
    """
    # Add cc-session-toolkit to path BEFORE building the token counter: the
    # counter importlib-loads extract-transcript-text.py, which imports
    # cc_session_toolkit at module scope, so building it first made
    # ``--min-content-tokens`` — the preferred floor — die with "No module
    # named cc_session_toolkit" (audit 2026-09-08, finding AR15).
    ensure_toolkit_on_path()

    distilled_tokens = _make_token_counter(logger) if min_content_tokens else None

    from cc_session_toolkit.archive import (
        extract_session_stats,
        get_session_id,
        is_trivial_session,
    )

    # Load already-archived session IDs for deduplication. **Disk is the
    # only dedup key.** ``session.meta.json`` on disk is what an archived
    # session IS; CATALOG.json is a derived index, rebuilt by
    # ``verify --fix-catalogue``, and it under-reports and over-reports in
    # both directions (2026-07-28: 539 entries against 728 ids on disk).
    #
    # Until 2026-09-08 the catalogue's ids were unioned in three lines after
    # logging that some of them had no metadata on disk. That made a GHOST
    # entry — catalogued, never archived — suppress archiving of the very
    # session it named, while check-archive-drift.py (which reads metas only)
    # kept reporting it: a second permanent gate, on top of AR1's. Ghosts are
    # now counted and reported, and nothing more (audit finding AR2).
    archived_ids: set[str] = archived_session_ids_on_disk(
        DEFAULT_ARCHIVE_ROOT, logger
    )
    if CATALOGUE_FILE.exists():
        catalogued = read_catalogue_ids(CATALOGUE_FILE, logger)
        ghosts = catalogued - archived_ids
        if ghosts:
            logger.warning(
                "%d session id(s) in CATALOG.json have no metadata on disk "
                "(ghost entries — NOT treated as archived; rebuild the "
                "catalogue with `verify --fix-catalogue`)",
                len(ghosts),
            )
        logger.info(
            "Deduplicating against %d archived session ids on disk "
            "(catalogue holds %d, %d of them ghosts)",
            len(archived_ids), len(catalogued), len(ghosts),
        )

    manifest: list[dict[str, Any]] = []
    total_skipped_trivial = 0
    total_skipped_archived = 0
    total_skipped_agent = 0
    total_skipped_duplicate = 0
    total_skipped_in_grace = 0
    # session_id -> index into `manifest`, so a duplicate found on a second
    # machine can replace the first when its transcript is larger.
    seen: dict[str, int] = {}

    if source_pairs is None:
        source_pairs = [
            (encoded, CLAUDE_PROJECTS_DIR / encoded)
            for encoded in project_mapping
        ]

    for encoded, proj_dir in sorted(source_pairs):
        project_root, project_name = project_mapping.get(
            encoded, (None, "unknown")
        )

        for jsonl_file in sorted(proj_dir.glob("*.jsonl")):
            # Skip orphaned flat agent files at root level
            if jsonl_file.name.startswith("agent-"):
                total_skipped_agent += 1
                continue

            session_id = get_session_id(jsonl_file)

            # Deduplication check
            if session_id in archived_ids:
                total_skipped_archived += 1
                continue

            # Completeness guard (audit 2026-09-08, AR3). A transcript
            # written within the grace window may still be growing: the
            # session is live, or a compaction is mid-flight. Archiving a
            # growing file captures a prefix, and that prefix then becomes
            # canonical — the archive says "complete", every checker agrees,
            # and the tail of the session is gone. Wait instead; the next run
            # picks it up.
            if within_grace(jsonl_file):
                total_skipped_in_grace += 1
                continue

            # Extract stats for trivial filtering
            try:
                stats = extract_session_stats(jsonl_file)
            except Exception as exc:
                logger.warning(
                    "Failed to extract stats for %s: %s", jsonl_file, exc
                )
                continue

            # The shared substance predicate — the default filter, and the
            # one the drift gate agrees with.
            content_chars = 0
            if min_content_chars > 0:
                content_chars = session_content_chars(
                    jsonl_file, threshold=min_content_chars
                )
                if content_chars < min_content_chars:
                    total_skipped_trivial += 1
                    continue

            # Legacy filters, applied only when explicitly requested.
            content_tokens = 0
            if distilled_tokens is not None:
                content_tokens = distilled_tokens(jsonl_file)
                if content_tokens < min_content_tokens:
                    total_skipped_trivial += 1
                    continue
            elif min_turns > 0 and is_trivial_session(stats, min_turns=min_turns):
                total_skipped_trivial += 1
                continue

            # Count subagents
            subagent_dir = jsonl_file.with_suffix("") / "subagents"
            subagent_count = 0
            if subagent_dir.is_dir():
                subagent_count = len(list(subagent_dir.glob("*.jsonl")))

            # Wait — the session dir for subagents uses the session UUID
            # as a directory name (same stem as the JSONL file)
            session_dir = proj_dir / session_id
            if not subagent_dir.is_dir() and session_dir.is_dir():
                subagent_dir = session_dir / "subagents"
                if subagent_dir.is_dir():
                    subagent_count = len(list(subagent_dir.glob("*.jsonl")))

            entry = {
                "session_id": session_id,
                "session_path": str(jsonl_file),
                "encoded_dir": encoded,
                # Serialise unresolved roots as JSON null (not the string
                # "None") so the consumer can distinguish "no project
                # root" from a directory literally named ``None``.
                "project_root": (
                    str(project_root) if project_root is not None else None
                ),
                "project_name": project_name,
                "size_bytes": jsonl_file.stat().st_size,
                "turns": stats.get("turns", 0),
                "duration_minutes": stats.get("duration_minutes", 0),
                "subagent_count": subagent_count,
                "subagent_dir": str(subagent_dir) if subagent_count > 0 else None,
                "source_machine": _source_machine_of(jsonl_file),
                "content_tokens": content_tokens,
                "content_chars": content_chars,
            }

            # Same session on a second machine: keep the larger transcript.
            if session_id in seen:
                total_skipped_duplicate += 1
                incumbent = manifest[seen[session_id]]
                if entry["size_bytes"] > incumbent["size_bytes"]:
                    logger.info(
                        "Session %s: preferring %s copy (%d bytes) over "
                        "%s (%d bytes)",
                        session_id[:8], entry["source_machine"],
                        entry["size_bytes"], incumbent["source_machine"],
                        incumbent["size_bytes"],
                    )
                    manifest[seen[session_id]] = entry
                continue

            seen[session_id] = len(manifest)
            manifest.append(entry)

    logger.info(
        "Discovery complete: %d sessions to archive, "
        "%d skipped (trivial), %d skipped (already archived), "
        "%d skipped (flat agents), %d skipped (cross-machine duplicate), "
        "%d skipped (written within the %dh grace window — may still be "
        "growing)",
        len(manifest), total_skipped_trivial,
        total_skipped_archived, total_skipped_agent,
        total_skipped_duplicate, total_skipped_in_grace, GRACE_HOURS,
    )

    return manifest


def cmd_discover(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Run the discover mode: scan, filter, report, save manifest."""
    source_root = getattr(args, "source_root", CLAUDE_PROJECTS_DIR)
    source_pairs = iter_source_project_dirs(
        source_root, logger, getattr(args, "layout", "auto")
    )
    project_mapping = resolve_project_mapping(logger, source_pairs)
    manifest = discover_sessions(
        project_mapping, args.min_turns, logger, source_pairs,
        min_content_tokens=getattr(args, "min_content_tokens", 0),
        min_content_chars=getattr(args, "min_content_chars", MIN_CONTENT_CHARS),
    )

    # Save manifest
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    logger.info("Manifest saved to %s", MANIFEST_FILE)

    # Summary by project
    by_project: dict[str, dict[str, Any]] = {}
    total_size = 0
    total_subagents = 0

    for entry in manifest:
        proj = entry["project_name"]
        if proj not in by_project:
            by_project[proj] = {"count": 0, "size": 0, "subagents": 0}
        by_project[proj]["count"] += 1
        by_project[proj]["size"] += entry["size_bytes"]
        by_project[proj]["subagents"] += entry["subagent_count"]
        total_size += entry["size_bytes"]
        total_subagents += entry["subagent_count"]

    print(f"\n{'=' * 60}")
    print("DISCOVERY SUMMARY")
    print(f"{'=' * 60}")
    print(f"Sessions to archive: {len(manifest)}")
    print(f"Total subagents:     {total_subagents}")
    print(f"Total raw size:      {total_size / 1024 / 1024:.1f} MB")
    print(f"Estimated compressed: {total_size * 0.2 / 1024 / 1024:.0f} MB")
    print()

    # Enrichment cost estimate
    est_input_cost = (
        len(manifest) * EST_TOKENS_PER_SESSION / 1_000_000
        * BATCH_INPUT_COST_PER_M
    )
    est_output_cost = (
        len(manifest) * EST_OUTPUT_TOKENS_PER_SESSION / 1_000_000
        * BATCH_OUTPUT_COST_PER_M
    )
    print(
        f"Estimated enrichment cost: "
        f"${est_input_cost + est_output_cost:.2f} "
        f"(Haiku Batch API)"
    )
    print()

    print(f"{'Project':<35} {'Sessions':>8} {'Size (MB)':>10} {'Subagents':>10}")
    print("-" * 65)
    for proj, data in sorted(
        by_project.items(), key=lambda x: -x[1]["count"]
    ):
        print(
            f"{proj:<35} {data['count']:>8} "
            f"{data['size'] / 1024 / 1024:>10.1f} "
            f"{data['subagents']:>10}"
        )
    print("-" * 65)
    print(
        f"{'TOTAL':<35} {len(manifest):>8} "
        f"{total_size / 1024 / 1024:>10.1f} "
        f"{total_subagents:>10}"
    )

    print(f"\nManifest: {MANIFEST_FILE}")
    print("Next: python3 scripts/bulk-archive.py archive [--dry-run]")


# ============================================================================
# Archive
# ============================================================================


def _empty_checkpoint() -> dict[str, Any]:
    """Return a fresh, empty checkpoint structure."""
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "archived_ids": [],
        "skipped_trivial_ids": [],
        "failed_ids": {},
        "stats": {
            "total_archived": 0,
            "total_subagents": 0,
            "total_compressed_bytes": 0,
        },
    }


def _load_checkpoint(logger: logging.Logger | None = None) -> dict[str, Any]:
    """Load the archive checkpoint, treating an unusable file as empty.

    ``logs/bulk-archive-progress.json`` is tracked in the private data
    submodule, so it can arrive here with git conflict markers in it, and a
    crash mid-write used to leave it truncated. Either way ``json.loads``
    raised and ``archive`` died before doing any work — a progress file, a
    pure optimisation, taking the command down (audit round 4c-2, finding 2).

    A checkpoint that cannot be read is worth exactly nothing and costs
    exactly one re-scan: every entry it holds is re-verified against disk
    anyway. So it is logged loudly and treated as absent. A file of the wrong
    SHAPE is handled the same way — a list, or a dict missing the keys the
    caller indexes, would otherwise fail later and further from the cause.
    """
    if not CHECKPOINT_FILE.exists():
        return _empty_checkpoint()
    try:
        loaded = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if logger is not None:
            logger.warning(
                "Checkpoint at %s is unreadable (%s) — starting from an "
                "empty one. Nothing is lost: every entry is re-verified "
                "against disk before it is honoured.",
                CHECKPOINT_FILE, exc,
            )
        return _empty_checkpoint()
    if not isinstance(loaded, dict):
        if logger is not None:
            logger.warning(
                "Checkpoint at %s is a %s, not an object — starting from an "
                "empty one.", CHECKPOINT_FILE, type(loaded).__name__,
            )
        return _empty_checkpoint()
    # Fill in anything a hand-edited or older file is missing, so the callers
    # below can index without guarding every key.
    checkpoint = _empty_checkpoint()
    checkpoint.update(loaded)
    for key, empty in (
        ("archived_ids", []), ("skipped_trivial_ids", []), ("failed_ids", {}),
    ):
        if not isinstance(checkpoint.get(key), type(empty)):
            checkpoint[key] = empty
    if not isinstance(checkpoint.get("stats"), dict):
        checkpoint["stats"] = _empty_checkpoint()["stats"]
    return checkpoint


#: A failed_ids entry older than this is retried automatically. Failures are
#: overwhelmingly environmental (a full disk, an unmounted store, a session
#: that was live at the time); keeping one forever turns a transient problem
#: into a permanently unarchivable session (audit round 4c-2, finding 1).
#:
#: **There is deliberately no attempt cap.** A session that fails for its own
#: reasons — a transcript the toolkit cannot parse, say — is retried once
#: every FAILED_RETRY_AFTER_DAYS, for ever. That is a bounded cost (one
#: attempt a week, logged each time) and the alternative is worse: a
#: permanent-failure state would silence the drift gate's only remaining
#: complaint about a session that is genuinely not archived, which is the
#: never-clearable-gate shape this pipeline has now been bitten by three
#: times. A poisoned session should keep asking (audit round 4c-3, L-9).
FAILED_RETRY_AFTER_DAYS = 7

#: Substrings of a recorded failure reason that mean "try again next run".
#: These describe the state of the SOURCE at one moment, not a defect in the
#: session, so the next run is entitled to a different answer.
#:
#: Only reasons that can actually reach ``failed_ids`` belong here. The
#: completeness guard's refusals do NOT: they are collected in
#: ``skipped_incomplete`` and never recorded as failures, so listing them
#: here described a path that does not exist (audit round 4c-3, finding
#: L-7). "size changed since discovery" was pruned for a second reason —
#: round 4c-2 replaced that refusal with a warning, and round 4c-3 replaced
#: the shrink half with a differently-worded refusal that is likewise a
#: skip, not a failure.
_TRANSIENT_FAILURE_MARKERS = (
    # Written at the post-copy comparison: the source moved while it was
    # being read, so the entry may hold a prefix. Next run, the session is
    # usually quiescent and the copy succeeds.
    "source changed DURING the copy",
)


def _record_failure(
    checkpoint: dict[str, Any], session_id: str, reason: str
) -> None:
    """Record a per-session failure with the time it happened.

    Stored as ``{"reason": ..., "recorded_at": ...}``. The legacy bare-string
    form is still read (see :func:`_partition_failed_ids`); without a
    timestamp there is no way to expire an entry, which is half of why a
    failure used to be permanent.
    """
    checkpoint["failed_ids"][session_id] = {
        "reason": reason,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _failure_reason(entry: Any) -> str:
    """Return the reason text from either checkpoint failure shape."""
    if isinstance(entry, dict):
        return str(entry.get("reason", ""))
    return str(entry)


def _partition_failed_ids(
    failed: dict[str, Any],
    on_disk: set[str],
    *,
    retry_all: bool = False,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Split ``failed_ids`` into (still binding, retried) with reasons.

    A failure is retried when any of these holds:

    * the session is on this machine's disk after all — some other path
      archived it, so the record is simply wrong;
    * the recorded reason describes a moment rather than a defect (the source
      was growing, was in grace, was briefly unreadable);
    * the entry has aged past :data:`FAILED_RETRY_AFTER_DAYS`, or carries no
      timestamp at all (the legacy shape, which cannot be aged);
    * ``--retry-failed`` was passed.

    Everything else still blocks, so a genuinely broken session does not cost
    a full re-run every night.
    """
    moment = now or datetime.now(timezone.utc)
    binding: dict[str, Any] = {}
    retried: dict[str, str] = {}
    for session_id, entry in failed.items():
        reason = _failure_reason(entry)
        if retry_all:
            retried[session_id] = "--retry-failed"
            continue
        if session_id in on_disk:
            # An entry exists — but if the failure was the during-copy
            # comparison, that entry is the SUSPECT one this run wrote, not
            # evidence the session is safely archived. Saying "already
            # archived on this machine" over it reads as reassurance for
            # exactly the case that needs a second look (round 4c-3, L-8).
            if "DURING the copy" in reason:
                retried[session_id] = (
                    "an entry is on disk, but it is the possibly-truncated "
                    "one this failure describes — re-archiving over it"
                )
            else:
                retried[session_id] = "already archived on this machine"
            continue
        if any(marker in reason for marker in _TRANSIENT_FAILURE_MARKERS):
            retried[session_id] = f"transient failure ({reason[:60]})"
            continue
        recorded_at = entry.get("recorded_at") if isinstance(entry, dict) else None
        if not recorded_at:
            retried[session_id] = "no timestamp (legacy entry) — retrying once"
            continue
        try:
            when = datetime.fromisoformat(recorded_at)
        except ValueError:
            retried[session_id] = "unparseable timestamp — retrying once"
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if (moment - when).days >= FAILED_RETRY_AFTER_DAYS:
            retried[session_id] = (
                f"failure is older than {FAILED_RETRY_AFTER_DAYS} days"
            )
            continue
        binding[session_id] = entry
    return binding, retried


def _save_checkpoint(checkpoint: dict[str, Any]) -> None:
    """Persist the checkpoint via a temporary file and an atomic rename.

    This is written after every single session, so it is the file most
    likely to be caught mid-write by a Ctrl-C or a power cut. A bare
    ``write_text`` truncates first and fills after, leaving a window in which
    the file on disk is half a JSON document (audit round 4c-2, finding 2).
    """
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_FILE.with_name(CHECKPOINT_FILE.name + ".tmp")
    tmp.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    tmp.replace(CHECKPOINT_FILE)


def archive_subagents(
    source_session_dir: Path,
    archive_dir: Path,
    logger: logging.Logger,
    force: bool = False,
) -> int:
    """
    Compress subagent JSONL files from a session's subagents directory
    into the archive directory.

    Written via a temporary file and an atomic rename, and an existing
    archived subagent is left alone unless *force* is set. The old version
    wrote straight to the destination, so an interrupted run left a truncated
    ``.gz`` that every later check accepted as the subagent's transcript, and
    a re-run overwrote a good archived subagent with whatever the source held
    now (audit 2026-09-08, finding AR14). ``cmd_subagents`` a few hundred
    lines below already did it this way; this is the same discipline applied
    to the path that runs far more often.

    Returns:
        Number of subagents archived (files skipped as already present are
        not counted).
    """
    subagent_source = source_session_dir / "subagents"
    if not subagent_source.is_dir():
        return 0

    subagent_files = sorted(subagent_source.glob("*.jsonl"))
    if not subagent_files:
        return 0

    subagent_dest = archive_dir / "subagents"
    subagent_dest.mkdir(parents=True, exist_ok=True)

    count = 0
    skipped = 0
    for sa_file in subagent_files:
        dest_gz = subagent_dest / f"{sa_file.stem}.jsonl.gz"
        if dest_gz.exists() and not force:
            skipped += 1
            continue

        tmp = dest_gz.with_suffix(".gz.tmp")
        try:
            with open(sa_file, "rb") as f_in:
                with gzip.open(tmp, "wb") as f_out:
                    # Stream in chunks to keep memory bounded
                    while True:
                        chunk = f_in.read(8192)
                        if not chunk:
                            break
                        f_out.write(chunk)
            tmp.replace(dest_gz)
            count += 1
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            logger.warning(
                "Failed to archive subagent %s: %s", sa_file.name, exc
            )

    if skipped:
        logger.info(
            "%d subagent archive(s) already present in %s — left alone "
            "(pass --force to overwrite)", skipped, subagent_dest,
        )
    return count


def relocate_to_legacy_precedent(
    archived_dirs: list[Path],
    archive_root: Path,
    logger: logging.Logger,
    dry_run: bool = False,
) -> int:
    """Move freshly archived entries under ``_legacy/`` where precedent exists.

    Sessions launched from outside a project tree — cwd ``/home/shawn`` or
    ``/home/shawn/Code`` — were historically filed under
    ``_legacy/<project_name>/`` (9 ``Code`` entries, 3 ``shawn``, plus
    ``gemma-project``, ``sciphi-project`` and ``llm_models``). The archiver
    derives the destination directory from ``project_name``, so without this
    step those sessions land in *new* top-level directories and the same
    project ends up split across ``_legacy/shawn/`` and ``shawn/`` — which is
    the cross-location fragmentation the archive was just repaired for.

    Only ``project_name`` values that **already** have a ``_legacy``
    subdirectory are moved, so this cannot invent new legacy projects. Metadata
    is deliberately left untouched: ``project.name`` is already correct (the
    existing ``_legacy`` entries carry the same plain names), and
    ``archive.jsonl_path`` is relative to the entry directory, so relocation
    does not invalidate it.

    Returns the number of entries moved.
    """
    legacy_root = archive_root / "_legacy"
    if not legacy_root.is_dir():
        return 0

    moved = 0
    for entry_dir in archived_dirs:
        if not entry_dir.is_dir() or entry_dir.parent == legacy_root:
            continue
        project_name = entry_dir.parent.name
        target_parent = legacy_root / project_name
        if not target_parent.is_dir():
            continue

        target = target_parent / entry_dir.name
        if target.exists():
            logger.warning(
                "Legacy target already exists, leaving in place: %s", target
            )
            continue

        if dry_run:
            logger.info("[DRY RUN] Would move %s -> %s", entry_dir, target)
            moved += 1
            continue

        entry_dir.rename(target)
        logger.info(
            "Relocated %s to _legacy/%s/ (matching existing precedent)",
            entry_dir.name, project_name,
        )
        moved += 1

        # Remove the now-empty top-level directory this run created, but never
        # a directory that already held other entries.
        try:
            entry_dir.parent.rmdir()
            logger.info("Removed empty directory %s", entry_dir.parent)
        except OSError:
            pass

    if moved:
        logger.info("Relocated %d entries under _legacy/", moved)
    return moved


def _parent_session_of(agent_file: Path) -> str | None:
    """Read the parent session id recorded inside a subagent transcript.

    Every subagent record carries ``sessionId`` pointing at the session that
    spawned it. This is what makes flat ``agent-*.jsonl`` files at the root of
    a project directory recoverable: they carry no directory context, but they
    do carry their parentage.
    """
    try:
        with agent_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    parent = json.loads(line).get("sessionId")
                except json.JSONDecodeError:
                    continue
                if parent:
                    return str(parent)
    except (OSError, UnicodeDecodeError):
        return None
    return None


def discover_orphan_subagents(
    source_root: Path,
    archive_root: Path,
    logger: logging.Logger,
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, str | None]]]:
    """Find subagent transcripts that exist in raw but not in the archive.

    Subagent transcripts are **research records in their own right** and are
    archived inside their parent session's entry, as
    ``<entry>/subagents/<agent-id>.jsonl.gz``. They are deliberately given no
    metadata of their own — they are not sessions — but they must still be
    captured, and two layouts were being missed:

    **Flat** ``<cwd-key>/agent-*.jsonl`` — the older on-disk layout. Discovery
    skips these when scanning for *sessions* (correctly, they are not
    sessions), and nothing else picked them up, so they were never archived.

    **Nested** ``<cwd-key>/<session-uuid>/subagents/*.jsonl`` — captured at
    archive time, but only for sessions archived *after* their subagents ran.
    A session archived earlier, or archived by a path that predates subagent
    capture, keeps an entry with no ``subagents/`` directory.

    Returns ``(attachable, unattachable)`` where attachable is a list of
    ``(agent_file, destination_entry_dir)`` pairs.
    """
    archived_names = {
        p.name.replace(".jsonl.gz", "")
        for p in archive_root.rglob("subagents/*.jsonl.gz")
    }
    session_to_entry: dict[str, Path] = {}
    for meta_path in archive_root.rglob("session.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        session_id = (meta.get("session") or {}).get("id")
        if session_id:
            session_to_entry[session_id] = meta_path.parent

    candidates: list[Path] = []
    for machine_dir in sorted(source_root.iterdir()):
        if not machine_dir.is_dir():
            continue
        # Both layouts, from either a live store or a merged snapshot.
        candidates.extend(machine_dir.glob("*/agent-*.jsonl"))
        candidates.extend(machine_dir.glob("*/*/subagents/*.jsonl"))
        candidates.extend(machine_dir.glob("agent-*.jsonl"))
        candidates.extend(machine_dir.glob("*/subagents/*.jsonl"))

    attachable: list[tuple[Path, Path]] = []
    unattachable: list[tuple[Path, str | None]] = []
    seen: set[str] = set()
    for agent_file in sorted(set(candidates)):
        name = agent_file.stem
        if name in archived_names or name in seen:
            continue
        seen.add(name)
        parent = _parent_session_of(agent_file)
        entry = session_to_entry.get(parent) if parent else None
        if entry is None:
            unattachable.append((agent_file, parent))
        else:
            attachable.append((agent_file, entry))

    logger.info(
        "Orphan subagents: %d attachable, %d unattachable "
        "(parent session not archived)",
        len(attachable), len(unattachable),
    )
    return attachable, unattachable


def cmd_subagents(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Backfill subagent transcripts into their parent archive entries."""
    attachable, unattachable = discover_orphan_subagents(
        args.source_root, DEFAULT_ARCHIVE_ROOT, logger
    )

    if unattachable:
        logger.warning(
            "%d subagent transcripts have no archived parent session",
            len(unattachable),
        )
        # These are still research records, and some have no parent transcript
        # anywhere in raw — the subagent outlived its session file. Dropping
        # them would lose the only surviving trace of that work, so they are
        # held under a clearly-named quarantine keyed by parent session id
        # rather than discarded. If the parent is ever archived, they can be
        # moved into it; the naming makes that a mechanical step.
        holding = DEFAULT_ARCHIVE_ROOT / "_legacy" / "_orphan-subagents"
        for agent_file, parent in unattachable:
            dest_dir = holding / (parent or "unknown-parent") / "subagents"
            logger.warning(
                "  %s (parent %s) -> %s",
                agent_file.name, (parent or "unreadable")[:8],
                dest_dir.relative_to(DEFAULT_ARCHIVE_ROOT),
            )
            if args.dry_run:
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{agent_file.stem}.jsonl.gz"
            if dest.exists():
                continue
            try:
                tmp = dest.with_suffix(".gz.tmp")
                with open(agent_file, "rb") as f_in, gzip.open(tmp, "wb") as f_out:
                    while True:
                        chunk = f_in.read(8192)
                        if not chunk:
                            break
                        f_out.write(chunk)
                tmp.replace(dest)
            except Exception as exc:
                logger.error("Failed to hold %s: %s", agent_file.name, exc)

    if not attachable:
        logger.info("No orphan subagents to archive")
        return

    if args.dry_run:
        by_entry = Counter(str(entry) for _, entry in attachable)
        logger.info("[DRY RUN] Would archive %d subagents:", len(attachable))
        for entry, count in by_entry.most_common(15):
            logger.info("  %3d -> %s", count, entry)
        return

    written = 0
    for agent_file, entry in attachable:
        dest_dir = entry / "subagents"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{agent_file.stem}.jsonl.gz"
        if dest.exists():
            continue
        try:
            # Write via a temporary name and rename, so an interrupted run
            # cannot leave a truncated archive that later looks complete.
            tmp = dest.with_suffix(".gz.tmp")
            with open(agent_file, "rb") as f_in, gzip.open(tmp, "wb") as f_out:
                while True:
                    chunk = f_in.read(8192)
                    if not chunk:
                        break
                    f_out.write(chunk)
            tmp.replace(dest)
            written += 1
        except Exception as exc:
            logger.error("Failed to archive %s: %s", agent_file.name, exc)

    logger.info("Archived %d orphan subagent transcripts", written)
    print("\nNext: python3 scripts/bulk-archive.py verify --fix-catalogue")


def uncompressed_size(transcript: Path) -> int | None:
    """Return the byte length an archived transcript decompresses to.

    For ``session.jsonl.gz`` this reads the gzip ISIZE trailer — the last
    four bytes of the member, little-endian — so the answer costs one seek
    rather than a full decompression pass over the whole archive. ISIZE is
    stored modulo 2**32; no session transcript comes close to 4 GiB, and a
    file that did would report a wrapped value, which is why the caller
    treats a mismatch as "report", never as "delete".

    Returns ``None`` when the size cannot be determined.
    """
    try:
        if transcript.suffix == ".gz":
            with open(transcript, "rb") as handle:
                if handle.seek(0, os.SEEK_END) < 8:
                    return None
                handle.seek(-4, os.SEEK_END)
                return int.from_bytes(handle.read(4), "little")
        return transcript.stat().st_size
    except OSError:
        return None


def refuse_incomplete_source(
    session_path: Path,
    expected_size: int | None,
    logger: logging.Logger,
) -> str | None:
    """Return a reason to refuse archiving *session_path*, or ``None``.

    The completeness guard (audit 2026-09-08, finding AR3). Discovery and
    archiving are separate commands, often minutes or days apart, and nothing
    between them stopped the archiver copying a transcript that was still
    being written. A copy taken mid-write is a prefix — and once it is in the
    archive it IS the session, with every integrity check reporting clean,
    because until now every check compared the archive against itself.

    Three refusals:

    * the transcript has gone (moved, or the machine's store was cleaned);
    * it was last written inside the grace window, so a live session or an
      in-flight compaction may still be appending;
    * it is SHORTER than discovery recorded.

    The two directions of a size difference are not the same event, and
    round 4c-2 wrongly treated them alike (audit round 4c-3, finding M-2).

    **Larger** is a stale manifest. Discovery already skipped anything inside
    the grace window, so a manifested session was quiescent when it was
    listed; if it is quiescent again now and has grown, the session simply
    resumed and finished between the two commands. Refusing on that made the
    mismatch permanent, because the manifest kept the old size and every
    later run refused for the same reason. So growth is a warning and the
    current content is archived. The manifest itself is NOT rewritten — it
    is only ever written by ``cmd_discover`` and by ``cmd_archive``'s
    discovery fallback — so the same warning repeats on every run until
    ``discover`` is next run. That is harmless and cheap, but an earlier
    version of this docstring claimed the caller refreshed the recorded
    size, which it does not (audit round 4c-3, finding L-4).

    **Smaller** is never a stale manifest. Transcripts are append-only: a
    source that has lost bytes was truncated by something — an interrupted
    store sync, a partial rsync, a manual edit, a failing disk. Archiving it
    writes the short version, and nothing downstream can tell: the toolkit
    records the length it actually compressed, so ``verify``'s size check
    compares the truncation against itself and reports clean. A shrink is
    the one case where the manifest is better evidence than the file, so it
    is refused and named, and the drift gate keeps reporting the session
    until a human looks.

    What still protects the copy in the growth case is the pair of checks
    about NOW: the grace window above, and the before/after comparison
    around the copy itself.
    """
    try:
        stat = session_path.stat()
    except OSError as exc:
        return f"source transcript unreadable ({exc})"
    if within_grace(session_path):
        return (
            f"written within the {GRACE_HOURS}h grace window "
            "(may still be growing)"
        )
    if expected_size is not None and stat.st_size < expected_size:
        return (
            f"source has SHRUNK since discovery ({expected_size} -> "
            f"{stat.st_size} bytes). Transcripts are append-only, so this "
            "is truncation, not staleness — archiving it would make the "
            "short version canonical and every check would call it clean"
        )
    if expected_size is not None and stat.st_size != expected_size:
        logger.warning(
            "%s: manifest records %d bytes, source now holds %d and is out "
            "of the grace window — archiving the current content",
            session_path.name, expected_size, stat.st_size,
        )
    logger.debug(
        "Completeness guard passed for %s (%d bytes)",
        session_path.name, stat.st_size,
    )
    return None


def cmd_archive(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Run the archive mode: compress and archive sessions."""
    # Add cc-session-toolkit to path
    ensure_toolkit_on_path()

    from cc_session_toolkit.archive import archive_session

    # Load manifest
    if not MANIFEST_FILE.exists():
        logger.info("No manifest found — running discovery first...")
        source_root = getattr(args, "source_root", CLAUDE_PROJECTS_DIR)
        source_pairs = iter_source_project_dirs(
            source_root, logger, getattr(args, "layout", "auto")
        )
        project_mapping = resolve_project_mapping(logger, source_pairs)
        manifest = discover_sessions(
            project_mapping, args.min_turns, logger, source_pairs,
            min_content_tokens=getattr(args, "min_content_tokens", 0),
            min_content_chars=getattr(
                args, "min_content_chars", MIN_CONTENT_CHARS
            ),
        )
        MANIFEST_FILE.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    else:
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        logger.info("Loaded manifest with %d sessions", len(manifest))

    # Load checkpoint for resume, then CHECK IT AGAINST DISK.
    #
    # The checkpoint is a progress file under logs/, and logs/ is git-tracked
    # and synced between machines, while the archive itself is per-machine.
    # So a checkpoint written on the other machine arrives here saying "these
    # 600 sessions are archived" about an archive that has never held them —
    # and this machine then skips every one of them, permanently, with the
    # drift gate reporting them forever (audit 2026-09-08, finding AR12).
    #
    # A checkpoint entry is now only honoured when the session really is on
    # this machine's disk. Stale entries are dropped, named in the log, and
    # removed from the file so the state self-heals.
    checkpoint = _load_checkpoint(logger)
    on_disk = archived_session_ids_on_disk(DEFAULT_ARCHIVE_ROOT, logger)
    claimed = list(checkpoint["archived_ids"])
    already_done = {sid for sid in claimed if sid in on_disk}
    stale = [sid for sid in claimed if sid not in on_disk]
    if stale:
        logger.warning(
            "Dropping %d checkpoint entr%s claiming a session this machine "
            "has never archived (checkpoint synced from another machine, or "
            "an archive entry removed): %s",
            len(stale), "y" if len(stale) == 1 else "ies",
            ", ".join(sid[:8] for sid in stale[:10])
            + (" …" if len(stale) > 10 else ""),
        )
        checkpoint["archived_ids"] = sorted(already_done)
        _save_checkpoint(checkpoint)

    # The same self-heal for failed_ids. Without it AR3 traded one defect for
    # a worse one: a session that was growing during a copy is recorded as
    # failed, the to_archive filter below skips it on every subsequent run,
    # and the drift gate reports it forever — silently truncated became
    # permanently unarchivable (audit round 4c-2, finding 1). A failure
    # entry synced from the other machine blocked archiving here in exactly
    # the same way.
    binding_failures, retried_failures = _partition_failed_ids(
        dict(checkpoint["failed_ids"]),
        on_disk,
        retry_all=getattr(args, "retry_failed", False),
    )
    if retried_failures:
        logger.info(
            "Retrying %d previously failed session(s):", len(retried_failures)
        )
        for session_id, why in sorted(retried_failures.items())[:10]:
            logger.info("  %s — %s", session_id[:8], why)
        if len(retried_failures) > 10:
            logger.info("  … and %d more", len(retried_failures) - 10)
        checkpoint["failed_ids"] = binding_failures
        _save_checkpoint(checkpoint)
    already_failed = set(binding_failures)

    # Apply limit
    to_archive = [
        entry for entry in manifest
        if entry["session_id"] not in already_done
        and entry["session_id"] not in already_failed
    ]
    if args.limit and args.limit > 0:
        to_archive = to_archive[:args.limit]

    if not to_archive:
        logger.info("Nothing to archive — all sessions already processed")
        return

    logger.info(
        "Archiving %d sessions (%d already done, %d previously failed)",
        len(to_archive), len(already_done), len(already_failed),
    )

    if args.dry_run:
        logger.info("[DRY RUN] Would archive %d sessions:", len(to_archive))
        for entry in to_archive[:10]:
            logger.info(
                "  %s (%s, %d turns, %.1f MB)",
                entry["session_id"][:8],
                entry["project_name"],
                entry["turns"],
                entry["size_bytes"] / 1024 / 1024,
            )
        if len(to_archive) > 10:
            logger.info("  ... and %d more", len(to_archive) - 10)
        return

    # Archive each session
    archived_count = 0
    subagent_count = 0
    archived_dirs: list[Path] = []
    # (session_id, reason) for sources the completeness guard refused.
    skipped_incomplete: list[tuple[str, str]] = []

    for i, entry in enumerate(to_archive, 1):
        session_path = Path(entry["session_path"])
        session_id = entry["session_id"]
        project_name = entry["project_name"]
        # Audit 2026-05-02 E-Medium: ``project_root`` may be JSON null
        # (unresolved). Treat that as "no project root" and let the
        # downstream archiver fall back to ``archive_root`` rather than
        # synthesising a Path("None") that would silently masquerade as
        # a real directory.
        raw_project_root = entry.get("project_root")
        project_root_path: Path | None = (
            Path(raw_project_root) if raw_project_root else None
        )

        if i % 10 == 0 or i == 1:
            logger.info(
                "Progress: %d/%d (%.0f%%)",
                i, len(to_archive), i / len(to_archive) * 100,
            )

        # Re-stat immediately before the copy, not at discovery time: the
        # window between the two commands is exactly where a growing
        # transcript slips through (AR3).
        refusal = refuse_incomplete_source(
            session_path, entry.get("size_bytes"), logger
        )
        if refusal:
            logger.warning(
                "Skipping %s (%s): %s", session_id[:8], project_name, refusal
            )
            skipped_incomplete.append((session_id, refusal))
            continue
        size_before_copy = session_path.stat().st_size

        try:
            metadata = archive_session(
                session_path=session_path,
                project_root=(
                    project_root_path
                    if project_root_path is not None
                    and project_root_path.is_dir()
                    else None
                ),
                stats_only=True,
                use_gzip=True,
                auto_metadata=False,
                archive_root=DEFAULT_ARCHIVE_ROOT,
                project_name_override=project_name,
                capture_type="bulk_archive",
            )

            if metadata is None:
                # archive_session returns None on skip (dry_run or error)
                _record_failure(
                    checkpoint, session_id, "archive_session returned None"
                )
                _save_checkpoint(checkpoint)
                continue

            # Archive subagents if present
            sa_count = 0
            archive_dir_str = metadata.get("_archive_directory")
            if archive_dir_str and entry.get("subagent_dir"):
                # The subagent source dir is the session UUID dir
                # under the project dir
                source_session_dir = Path(entry["subagent_dir"]).parent
                sa_count = archive_subagents(
                    source_session_dir,
                    Path(archive_dir_str),
                    logger,
                    force=getattr(args, "force", False),
                )
                if sa_count > 0:
                    logger.info(
                        "  Archived %d subagents for %s",
                        sa_count, session_id[:8],
                    )

            # Compare the source again AFTER the copy. If it moved under us
            # the archived entry may hold a prefix, so it is recorded as a
            # failure rather than a success: it is not added to archived_ids,
            # the drift gate keeps reporting the session, and `verify` will
            # flag the size mismatch. The entry is left in place — deleting
            # from the archive on a size heuristic is a worse failure mode
            # than keeping a suspect entry that every checker now names.
            try:
                size_after_copy = session_path.stat().st_size
            except OSError:
                size_after_copy = -1
            if size_after_copy != size_before_copy:
                reason = (
                    f"source changed DURING the copy ({size_before_copy} -> "
                    f"{size_after_copy} bytes); archived entry at "
                    f"{archive_dir_str} may be truncated — re-archive"
                )
                logger.error("%s (%s): %s", session_id[:8], project_name, reason)
                _record_failure(checkpoint, session_id, reason)
                _save_checkpoint(checkpoint)
                continue

            # Update checkpoint
            checkpoint["archived_ids"].append(session_id)
            checkpoint["stats"]["total_archived"] += 1
            checkpoint["stats"]["total_subagents"] += sa_count
            _save_checkpoint(checkpoint)

            archived_count += 1
            subagent_count += sa_count
            if archive_dir_str:
                archived_dirs.append(Path(archive_dir_str))

        except Exception as exc:
            logger.error(
                "Failed to archive %s (%s): %s",
                session_id[:8], project_name, exc,
            )
            _record_failure(checkpoint, session_id, str(exc))
            _save_checkpoint(checkpoint)

    relocate_to_legacy_precedent(
        archived_dirs, DEFAULT_ARCHIVE_ROOT, logger
    )

    logger.info(
        "\nArchive complete: %d sessions, %d subagents archived",
        archived_count, subagent_count,
    )
    if skipped_incomplete:
        logger.warning(
            "%d session(s) skipped by the completeness guard (not archived):",
            len(skipped_incomplete),
        )
        for session_id, reason in skipped_incomplete:
            logger.warning("  %s — %s", session_id[:8], reason)
    if checkpoint["failed_ids"]:
        logger.warning(
            "%d sessions failed — see checkpoint: %s",
            len(checkpoint["failed_ids"]), CHECKPOINT_FILE,
        )

    print("\nNext: python3 scripts/bulk-archive.py verify --fix-catalogue")


# ============================================================================
# Enrich — Batch API metadata generation
# ============================================================================


def _sample_user_messages(session_path: Path) -> tuple[list[str], set[str]]:
    """
    Extract a sample of user messages and modified file paths from a session.

    Replicates the sampling logic from cc-session-toolkit's
    generate_auto_metadata(): first 2 + last 2 substantive user messages,
    plus Write/Edit file paths.

    Returns:
        Tuple of (sampled_messages, files_modified).
    """
    all_user_messages: list[str] = []
    files_modified: set[str] = set()

    with open(session_path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            message = entry.get("message", {})
            role = message.get("role")

            # Collect file paths from Write/Edit tool calls
            if role == "assistant":
                a_content = message.get("content", [])
                if isinstance(a_content, list):
                    for block in a_content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("name") in {"Write", "Edit"}
                        ):
                            fp = block.get("input", {}).get("file_path")
                            if fp:
                                files_modified.add(fp)
                continue

            if role != "user":
                continue

            content = message.get("content", "")
            if isinstance(content, list):
                # Skip tool results
                if any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                ):
                    continue
                content = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )

            if content:
                all_user_messages.append(content[:500])

    # Filter meta messages (slash commands, short confirmations)
    substantive = [
        msg for msg in all_user_messages
        if not _is_meta_message(msg)
    ]
    sample_source = substantive or all_user_messages

    # First 2 + last 2, deduplicated
    first = sample_source[:2]
    last = sample_source[-2:]
    seen: set[str] = set()
    sampled: list[str] = []
    for msg in first + last:
        if msg not in seen:
            seen.add(msg)
            sampled.append(msg)

    return sampled, files_modified


def _is_meta_message(text: str) -> bool:
    """
    Check whether a user message is meta/housekeeping.

    Mirrors cc-session-toolkit's _is_meta_message for consistency.
    """
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("/"):
        return True
    lower = stripped.lower().rstrip(".!?,")
    if len(stripped) < 40 and lower in {
        "yes", "no", "ok", "okay", "sure", "thanks", "thank you",
        "go ahead", "proceed", "continue", "do it", "looks good",
        "lgtm", "approved", "commit", "push", "commit and push",
        "y", "n",
    }:
        return True
    return False


def _build_enrich_prompt(
    sampled_messages: list[str],
    files_modified: set[str],
    stats: dict[str, Any],
) -> str:
    """Build the Haiku prompt for metadata generation."""
    messages_text = "\n---\n".join(sampled_messages)
    tool_summary = ", ".join(
        f"{k}: {v}"
        for k, v in stats.get("tool_calls", {}).get("by_type", {}).items()
    )
    artefact_basenames = sorted({Path(fp).name for fp in files_modified})
    files_line = (
        f"Files modified: {', '.join(artefact_basenames)}\n"
        if artefact_basenames else ""
    )

    n_total = len(sampled_messages)
    sample_label = (
        f"First and last substantive user messages "
        f"(from {n_total} total, meta-messages filtered)"
    )

    return (
        f"Based on the following Claude Code session information, "
        f"generate:\n"
        f"1. A concise title (5-10 words) reflecting the session's "
        f"main accomplishment\n"
        f"2. A one-sentence purpose statement\n"
        f"3. 2-5 lowercase hyphenated tags\n\n"
        f"Session stats: {stats.get('duration_minutes', 0)} min, "
        f"{stats.get('turns', 0)} turns, tools: {tool_summary}\n"
        f"{files_line}\n"
        f"{sample_label}:\n"
        f"{messages_text}\n\n"
        f"Respond with ONLY a JSON object, no markdown:\n"
        f'{{"title": "...", "purpose": "...", "tags": ["..."]}}'
    )


def _find_unenriched_sessions(
    logger: logging.Logger,
) -> list[tuple[Path, dict[str, Any]]]:
    """
    Walk ~/cc-archives/ for sessions needing metadata enrichment.

    Returns:
        List of (archive_dir, metadata_dict) tuples.
    """
    results = []

    for meta_path in sorted(DEFAULT_ARCHIVE_ROOT.rglob("session.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", meta_path, exc)
            continue

        purpose = (
            meta.get("auto_generated", {}).get("purpose", "")
            or ""
        )
        if (
            "unavailable" in purpose.lower()
            or "requires interactive" in purpose.lower()
        ):
            results.append((meta_path.parent, meta))

    logger.info("Found %d sessions needing enrichment", len(results))
    return results


# -- Terra (OpenAI GPT-5.6) enrichment ------------------------------------

# Structured-output schema. The bake-off ran Terra on free-form JSON so that
# it faced the same parsing burden as the Gemini and Haiku arms — a fairness
# constraint for measurement, and one its own docstring flagged should be
# dropped in production. Here it is dropped: `text.format` makes the provider
# guarantee schema-valid JSON, which removes parse failure as a defect class
# rather than detecting it after the fact.
TERRA_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "purpose", "tags", "three_ps"],
    "properties": {
        "title": {"type": "string"},
        "purpose": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "three_ps": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "prompt_summary", "process_summary", "provenance_summary",
            ],
            "properties": {
                "prompt_summary": {"type": "string"},
                "process_summary": {"type": "string"},
                "provenance_summary": {"type": "string"},
            },
        },
    },
}

TERRA_MAX_OUTPUT_TOKENS = 1024
TERRA_RETRY_WAITS = (30, 60, 120)


def _terra_call(
    user_message: str,
    system_prompt: str,
    *,
    service_tier: str = "flex",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One Responses-API call against Terra. Returns ``(parsed, usage)``.

    Mirrors the vetted bake-off adapter (``scripts/bake-off-metadata.py``)
    with two deliberate production changes:

    - ``text.format`` pins the JSON schema, so the response cannot be
      unparseable prose.
    - ``reasoning.effort`` stays ``"none"``: reasoning tokens bill at the
      output rate, and the bake-off scored Terra 27/30 on long sessions with
      reasoning off, so paying for it buys nothing measured.

    ``store=False`` keeps transcript content out of OpenAI's retained storage.
    """
    import urllib.error
    import urllib.request

    api_key = resolve_openai_key("PA")

    body = {
        "model": TERRA_MODEL,
        "store": False,
        "service_tier": service_tier,
        "reasoning": {"effort": "none"},
        "instructions": system_prompt,
        "input": user_message,
        "max_output_tokens": TERRA_MAX_OUTPUT_TOKENS,
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "session_metadata",
                "strict": True,
                "schema": TERRA_OUTPUT_SCHEMA,
            },
        },
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Re-raise with the API's own explanation attached. A bare
        # "HTTP Error 400: Bad Request" is indistinguishable between a
        # malformed request and a moderation block, and the two need
        # completely different responses — the body carries `code`, e.g.
        # `invalid_prompt` for a content-filter refusal.
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = "<no body>"
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc

    text = payload.get("output_text")
    if not text:
        chunks: list[str] = []
        for item in payload.get("output", []):
            for part in item.get("content", []) or []:
                if part.get("type") in ("output_text", "text") and part.get("text"):
                    chunks.append(part["text"])
        text = "".join(chunks)

    if not text.strip():
        raise RuntimeError(
            "empty output "
            f"(status={payload.get('status')}, "
            f"incomplete={payload.get('incomplete_details')})"
        )

    return json.loads(text), payload.get("usage", {})


def _terra_call_with_retry(
    user_message: str,
    system_prompt: str,
    logger: logging.Logger,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call Terra on the Flex tier, backing off then falling back to default.

    Flex is priced at half the standard rate but is preemptible: it returns
    429/503 under load. Waits are 30/60/120 s, after which the call is retried
    once on the default tier so a long backfill completes rather than aborting
    at 90%. The fallback costs 2x for that one session and is logged.
    """
    for attempt, wait in enumerate(TERRA_RETRY_WAITS, 1):
        try:
            return _terra_call(user_message, system_prompt, service_tier="flex")
        except RuntimeError as exc:
            # Only Flex preemption is worth retrying. A moderation block
            # (`invalid_prompt`) is deterministic — retrying it just burns
            # three waits to fail identically.
            message = str(exc)
            if not (message.startswith("HTTP 429") or message.startswith("HTTP 503")):
                raise
            logger.warning(
                "Flex preempted, attempt %d/%d — waiting %ds",
                attempt, len(TERRA_RETRY_WAITS), wait,
            )
            time.sleep(wait)

    logger.warning("Flex unavailable after retries — falling back to default tier")
    return _terra_call(user_message, system_prompt, service_tier="default")


def _enrich_terra(
    args: argparse.Namespace, logger: logging.Logger
) -> None:
    """Enrich archived sessions with Terra-generated metadata, in place.

    Real-time and sequential: unlike the Haiku path there is no 24-hour batch
    SLA to wait on, and Flex already buys the batch discount synchronously.
    """
    prompt_path = Path(args.prompt).expanduser()
    if not prompt_path.exists():
        logger.error("Prompt file not found: %s", prompt_path)
        sys.exit(1)
    system_prompt = prompt_path.read_text(encoding="utf-8")

    # Explicitly, rather than relying on _make_token_counter below having
    # done it first (round 4c-2, finding 15).
    ensure_toolkit_on_path()
    distilled = _make_token_counter(logger)
    unenriched = _find_unenriched_sessions(logger)
    if not unenriched:
        logger.info("All sessions already have metadata — nothing to enrich")
        return

    # Only enrich entries that clear the substance floor; below it there is
    # nothing for a model to summarise (see MIN_CONTENT_TOKENS).
    jobs: list[tuple[Path, dict[str, Any], str, int]] = []
    skipped_thin = 0
    for archive_dir, meta in unenriched:
        jsonl_gz = archive_dir / "session.jsonl.gz"
        if not jsonl_gz.exists():
            logger.warning("No session.jsonl.gz in %s — skipping", archive_dir)
            continue
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with gzip.open(jsonl_gz, "rb") as f_in:
                tmp_path.write_bytes(f_in.read())
            text = _distil_to_text(tmp_path, logger)
            tokens = distilled(tmp_path)
            # The shared substance predicate, measured on the decompressed
            # transcript — the SAME rule discovery and the drift gate use, so
            # nothing can be archived that enrichment then declines to
            # summarise for a different reason (audit AR1).
            substantive = is_substantive(tmp_path, MIN_CONTENT_CHARS)
        finally:
            tmp_path.unlink(missing_ok=True)

        if not substantive:
            skipped_thin += 1
            continue
        jobs.append((archive_dir, meta, text, tokens))

    if skipped_thin:
        logger.info(
            "Skipped %d entries below the %d-character substance floor",
            skipped_thin, MIN_CONTENT_CHARS,
        )
    if args.limit and args.limit > 0:
        jobs = jobs[:args.limit]
    if not jobs:
        logger.info("Nothing to enrich above the substance floor")
        return

    # Cost projection. chars/4 runs ~11% under a real tokenizer (measured
    # against the 2026-07-28 Terra usage records), so scale before reporting
    # rather than quoting a number known to be low.
    est_input = int(sum(t for *_, t in jobs) * 1.11)
    in_rate = TERRA_INPUT_PRICE_PER_MTOK * TERRA_FLEX_DISCOUNT
    out_rate = TERRA_OUTPUT_PRICE_PER_MTOK * TERRA_FLEX_DISCOUNT
    est_cost = est_input * in_rate / 1e6 + len(jobs) * 280 * out_rate / 1e6

    print("\n" + "=" * 60)
    print("TERRA ENRICHMENT — API CALL REVIEW")
    print("=" * 60)
    print(f"Model            : {TERRA_MODEL} (OpenAI Responses API)")
    print("Mode             : real-time, sequential, service_tier=flex")
    print(f"Calls            : {len(jobs)}")
    print(f"Est. input tokens: {est_input:,} (chars/4 x 1.11 calibration)")
    print(f"Rates            : ${in_rate}/Mtok in, ${out_rate}/Mtok out (flex)")
    print(f"ESTIMATED COST   : ${est_cost:.2f}")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN] No API calls made.")
        return

    if not args.yes:
        if input("\nProceed with live API calls? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return

    applied = 0
    failed = 0
    fell_back = 0
    usage_rows: list[dict[str, Any]] = []
    responses_dir = Path(args.responses_out).expanduser() / "terra"
    # A manifest of what was sent, so the validator can check the generated
    # project tag against ground truth rather than skipping that check.
    manifest_rows: list[dict[str, Any]] = [
        {
            "session_id": (m.get("session") or {}).get("id", "unknown"),
            "project": (m.get("project") or {}).get("name", "unknown"),
            "content_tokens": t,
            "archive_dir": str(d),
        }
        for d, m, _, t in jobs
    ]

    for i, (archive_dir, meta, text, tokens) in enumerate(jobs, 1):
        session = meta.get("session") or {}
        session_id = session.get("id", "unknown")
        project = (meta.get("project") or {}).get("name", "unknown")
        bin_label = (
            "short" if tokens < 50_000
            else "medium" if tokens < 120_000
            else "long"
        )
        user_message = _build_terra_user_message(
            session_id=session_id,
            project=project,
            started_at=session.get("started_at", ""),
            bin_label=bin_label,
            content_tokens=tokens,
            transcript_text=text,
        )

        logger.info(
            "[%d/%d] %s (%s, %s, %s tok)",
            i, len(jobs), session_id[:8], project, bin_label, f"{tokens:,}",
        )
        extractor_used = TERRA_MODEL
        try:
            parsed, usage = _terra_call_with_retry(
                user_message, system_prompt, logger
            )
        except Exception as exc:
            # A moderation refusal is deterministic and provider-specific, so
            # the only useful response is a different provider. Other failures
            # (network, malformed request) are not helped by a fallback and
            # are recorded as failures.
            blocked = "invalid_prompt" in str(exc)
            if not (blocked and args.fallback_gemini):
                logger.error("  FAILED %s: %s", session_id[:8], exc)
                failed += 1
                continue
            logger.warning(
                "  %s refused by Terra content filter — falling back to %s",
                session_id[:8], GEMINI_MODEL,
            )
            try:
                parsed, usage = _gemini_call(user_message, system_prompt)
                extractor_used = GEMINI_MODEL
                fell_back += 1
            except Exception as exc2:
                logger.error(
                    "  FAILED %s on fallback too: %s", session_id[:8], exc2
                )
                failed += 1
                continue

        usage_rows.append({
            "session_id": session_id,
            "model": extractor_used,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        })

        # Persist the raw generated object next to the run, in the per-arm
        # layout `scripts/validate-session-metadata.py --responses-dir`
        # expects. Enrichment writes into the archive, so without this there
        # would be nothing for the deterministic validator to gate on, and no
        # record of what the model actually returned versus what was merged.
        responses_dir.mkdir(parents=True, exist_ok=True)
        (responses_dir / f"{session_id}.json").write_text(
            json.dumps(parsed, indent=2), encoding="utf-8"
        )

        if _write_enriched_meta(archive_dir, parsed, logger, extractor_used):
            applied += 1
        else:
            failed += 1

    total_in = sum(r["input_tokens"] for r in usage_rows)
    total_out = sum(r["output_tokens"] for r in usage_rows)
    # Rates differ per provider, so bill each row at its own model's rate
    # rather than assuming the whole run was Terra.
    rates = {
        TERRA_MODEL: (
            TERRA_INPUT_PRICE_PER_MTOK * TERRA_FLEX_DISCOUNT,
            TERRA_OUTPUT_PRICE_PER_MTOK * TERRA_FLEX_DISCOUNT,
        ),
        GEMINI_MODEL: (
            GEMINI_FLEX_INPUT_PRICE_PER_MTOK,
            GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK,
        ),
    }
    actual = 0.0
    for row in usage_rows:
        r_in, r_out = rates.get(row.get("model", TERRA_MODEL), (in_rate, out_rate))
        actual += row["input_tokens"] * r_in / 1e6
        actual += row["output_tokens"] * r_out / 1e6

    usage_path = LOG_DIR / "terra-enrich-usage.json"
    usage_path.write_text(
        json.dumps({
            "model": TERRA_MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "applied": applied,
            "failed": failed,
            "fell_back_to_gemini": fell_back,
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "actual_cost_usd": round(actual, 4),
            "sessions": usage_rows,
        }, indent=2),
        encoding="utf-8",
    )

    logger.info(
        "\nTerra enrichment complete: %d applied, %d failed", applied, failed
    )
    logger.info(
        "Billed tokens: %s in, %s out  ->  ACTUAL COST $%.2f "
        "(estimated $%.2f)",
        f"{total_in:,}", f"{total_out:,}", actual, est_cost,
    )
    logger.info("Usage detail: %s", usage_path)

    if applied:
        manifest_path = responses_dir.parent / "run-manifest.json"
        manifest_path.write_text(
            json.dumps({"sessions": manifest_rows}, indent=2), encoding="utf-8"
        )
        logger.info("Run manifest: %s", manifest_path)
        print(
            "\nNext:\n"
            f"  ./venv/bin/python scripts/validate-session-metadata.py \\\n"
            f"      --responses-dir {responses_dir.parent} \\\n"
            f"      --manifest {manifest_path} --fail-on error\n"
            "  ./venv/bin/python scripts/bulk-archive.py verify --fix-catalogue"
        )


GEMINI_MODEL = "gemini-3.6-flash"
# Gemini 3.6 Flash, Flex tier (USD per million tokens), verified 2026-07-28.
# Flex and Batch are priced identically for this model.
GEMINI_FLEX_INPUT_PRICE_PER_MTOK = 0.75
GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK = 3.75


def _gemini_call(
    user_message: str, system_prompt: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One Gemini Flex call, used as the fallback when Terra refuses.

    Exists because OpenAI's content filter returns ``invalid_prompt`` on a
    small number of entirely benign transcripts — on the 2026-07-28 backfill,
    three sessions about locating and editing an Ollama Modelfile and taking
    stock of locally installed models. The refusal is deterministic, so the
    only remedy is a different provider.

    ``thinking_level: "minimal"`` rather than the older ``thinking_budget: 0``,
    which gemini-3.6-flash now rejects with 400 INVALID_ARGUMENT. Thinking
    bills at the output rate, so leaving it unset silently inflates cost.
    """
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
        "GOOGLE_API_KEY"
    )
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set (expected in .env)")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_message,
        config={
            "service_tier": "flex",
            "max_output_tokens": TERRA_MAX_OUTPUT_TOKENS,
            "system_instruction": system_prompt,
            "thinking_config": {"thinking_level": "minimal"},
            # Unlike the bake-off arm, production pins the schema so the
            # response cannot come back as unparseable prose.
            "response_mime_type": "application/json",
            "response_json_schema": TERRA_OUTPUT_SCHEMA,
        },
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("empty output from Gemini")

    usage_meta = getattr(response, "usage_metadata", None)
    usage = {
        "input_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
    }
    return json.loads(text), usage


def _distil_to_text(jsonl_path: Path, logger: logging.Logger) -> str:
    """Distil a raw transcript to the text the extractor model is shown."""
    extractor_path = Path(__file__).with_name("extract-transcript-text.py")
    spec = importlib.util.spec_from_file_location(
        "extract_transcript_text", str(extractor_path)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {extractor_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_transcript_text(str(jsonl_path))


def _build_terra_user_message(
    *,
    session_id: str,
    project: str,
    started_at: str,
    bin_label: str,
    content_tokens: int,
    transcript_text: str,
) -> str:
    """Session header + delimited transcript + output reminder.

    Kept byte-identical in structure to the bake-off's ``_build_user_message``
    so the arm that won on quality is the arm that actually runs. The
    postamble repeats the output contract *after* the transcript because the
    transcript can be 100K+ tokens and recency dominates.
    """
    header = (
        "## Session metadata header (not authoritative — transcript wins)\n"
        f"- Session ID: {session_id}\n"
        f"- Project: {project}\n"
        f"- Started at: {started_at}\n"
        f"- Length bin: {bin_label}\n"
        f"- Distilled content tokens (chars/4): {content_tokens:,}\n"
    )
    postamble = (
        "## Output reminder\n\n"
        "You have now read the complete transcript. Return a single JSON "
        "object with keys ``title``, ``purpose``, ``tags``, and "
        "``three_ps`` (an object with ``prompt_summary``, "
        "``process_summary``, ``provenance_summary``). Field contracts "
        "and anti-satisficing rules are in the system prompt; apply them.\n\n"
        "You are an outside observer summarising the transcript. You are "
        "not a participant. Do not continue the conversation."
    )
    return (
        f"{header}\n"
        f"<transcript>\n"
        f"{transcript_text}\n"
        f"</transcript>\n\n"
        f"{postamble}\n"
    )


def _write_enriched_meta(
    archive_dir: Path,
    parsed: dict[str, Any],
    logger: logging.Logger,
    extractor_model: str = TERRA_MODEL,
) -> bool:
    """Merge generated metadata into ``session.meta.json``.

    Writes the three-Ps summaries in **both** places the schema carries them —
    nested under ``auto_generated`` and at the top level — because the two are
    read by different consumers and the legacy Haiku path populated neither.
    ``extractor_model_id`` is corrected too: the archiver stamps a default of
    ``gemini-3.5-flash``, which would otherwise misattribute this metadata to
    a model that never saw the transcript.

    Written via a temporary file and atomic replace, so an interrupted run
    cannot leave a half-written metadata file behind.
    """
    meta_path = archive_dir / "session.meta.json"
    if not meta_path.exists():
        logger.warning("Meta file not found: %s", meta_path)
        return False

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cannot read %s: %s", meta_path, exc)
        return False

    three_ps = parsed.get("three_ps") or {}
    normalised = {
        "prompt_summary": three_ps.get("prompt_summary", ""),
        "process_summary": three_ps.get("process_summary", ""),
        "provenance_summary": three_ps.get("provenance_summary", ""),
    }

    existing = meta.get("auto_generated") or {}
    meta["auto_generated"] = {
        **existing,
        "title": parsed.get("title", "Untitled Session"),
        "purpose": parsed.get("purpose", ""),
        "tags": parsed.get("tags", []),
        "three_ps": normalised,
    }
    meta["three_ps"] = normalised
    meta["extractor_model_id"] = extractor_model

    try:
        tmp = meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.replace(meta_path)
    except OSError as exc:
        logger.warning("Cannot write %s: %s", meta_path, exc)
        return False
    return True


def cmd_enrich(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Run the enrich mode: Terra in-place, or Haiku batch submit/apply."""
    load_env()

    if args.provider == "terra":
        if args.batch_submit or args.batch_apply:
            logger.error(
                "--provider terra runs real-time; it takes neither "
                "--batch-submit nor --batch-apply"
            )
            sys.exit(1)
        _enrich_terra(args, logger)
        return

    if args.batch_apply:
        _enrich_apply(args.batch_apply, logger)
    elif args.batch_submit:
        _enrich_submit(args, logger)
    else:
        logger.error("Enrich requires --batch-submit or --batch-apply BATCH_ID")
        sys.exit(1)


def _enrich_submit(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Submit batch enrichment requests to Anthropic Batch API."""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed — pip install anthropic")
        sys.exit(1)

    # Add cc-session-toolkit to path for stats extraction
    ensure_toolkit_on_path()

    from cc_session_toolkit.archive import extract_session_stats

    unenriched = _find_unenriched_sessions(logger)
    if not unenriched:
        logger.info("All sessions already have metadata — nothing to enrich")
        return

    if args.limit and args.limit > 0:
        unenriched = unenriched[:args.limit]

    # Build batch requests
    requests = []
    session_id_map: dict[str, str] = {}  # custom_id → archive_dir path

    for archive_dir, meta in unenriched:
        session_id = meta.get("session", {}).get("id", "unknown")

        # Find the compressed session JSONL
        jsonl_gz = archive_dir / "session.jsonl.gz"
        if not jsonl_gz.exists():
            logger.warning("No session.jsonl.gz in %s — skipping", archive_dir)
            continue

        # Decompress to temporary location for reading
        import tempfile
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".jsonl", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                with gzip.open(jsonl_gz, "rb") as gz:
                    while True:
                        chunk = gz.read(8192)
                        if not chunk:
                            break
                        tmp.write(chunk)

            # Extract stats and sample messages
            stats = extract_session_stats(tmp_path)
            sampled, files_modified = _sample_user_messages(tmp_path)

        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

        if not sampled:
            logger.warning(
                "No user messages found in %s — skipping", session_id[:8]
            )
            continue

        prompt = _build_enrich_prompt(sampled, files_modified, stats)
        custom_id = f"session-{session_id}"

        requests.append({
            "custom_id": custom_id,
            "params": {
                "model": HAIKU_MODEL,
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}],
            },
        })
        session_id_map[custom_id] = str(archive_dir)

    if not requests:
        logger.info("No valid sessions to enrich after processing")
        return

    # --- API cost gate ---
    est_input_cost = (
        len(requests) * EST_TOKENS_PER_SESSION / 1_000_000
        * BATCH_INPUT_COST_PER_M
    )
    est_output_cost = (
        len(requests) * EST_OUTPUT_TOKENS_PER_SESSION / 1_000_000
        * BATCH_OUTPUT_COST_PER_M
    )
    total_est = est_input_cost + est_output_cost

    print(f"\n{'=' * 60}")
    print("API COST GATE — Batch Enrichment")
    print(f"{'=' * 60}")
    print(f"Model:       {HAIKU_MODEL}")
    print("Mode:        Anthropic Batch API (50% discount)")
    print(f"Requests:    {len(requests)}")
    print(f"Est. cost:   ${total_est:.2f}")
    print(f"{'=' * 60}")
    print()

    response = input("Submit batch? [y/N] ").strip().lower()
    if response != "y":
        logger.info("Batch submission cancelled by user")
        return

    # Submit
    client = anthropic.Anthropic()
    batch_job = client.messages.batches.create(requests=requests)
    batch_id = batch_job.id

    # Save state
    state = {
        "batch_id": batch_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "n_requests": len(requests),
        "session_id_map": session_id_map,
    }
    state_file = save_state(state, BATCH_STATE_DIR, BATCH_STATE_FILE)

    logger.info(
        "Batch submitted: %s | %d requests | Status: %s",
        batch_id, len(requests), batch_job.processing_status,
    )
    print(f"\nBatch ID: {batch_id}")
    print(f"State saved: {state_file}")
    print(
        f"\nNext: python3 scripts/bulk-archive.py "
        f"enrich --batch-apply {batch_id}"
    )


def _enrich_apply(batch_id: str, logger: logging.Logger) -> None:
    """Retrieve and apply batch enrichment results."""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed — pip install anthropic")
        sys.exit(1)

    # Load the state that describes THIS batch. session_id_map is what turns
    # a custom_id back into an archive directory; applying one batch's
    # results through another's map writes each session's metadata into some
    # other session's entry (audit AR18). A slot naming a different batch is
    # therefore a refusal, not a fallback.
    state = load_state(batch_id, BATCH_STATE_DIR, BATCH_STATE_FILE)
    if state is None:
        logger.error(
            "No batch state describing %s (looked in %s and %s) — without "
            "its session map, results cannot be applied to the right entries",
            batch_id, BATCH_STATE_DIR, BATCH_STATE_FILE,
        )
        sys.exit(1)
    session_id_map = state.get("session_id_map", {})

    client = anthropic.Anthropic()

    # Check batch status
    batch_job = client.messages.batches.retrieve(batch_id)
    logger.info(
        "Batch %s: status=%s, succeeded=%d, failed=%d",
        batch_id,
        batch_job.processing_status,
        batch_job.request_counts.succeeded,
        batch_job.request_counts.errored,
    )

    if batch_job.processing_status != "ended":
        logger.info(
            "Batch not yet complete (processing: %d). Try again later.",
            batch_job.request_counts.processing,
        )
        return

    # Process results
    applied = 0
    failed = 0

    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id
        archive_dir_str = session_id_map.get(custom_id)

        if not archive_dir_str:
            logger.warning("Unknown custom_id: %s — skipping", custom_id)
            failed += 1
            continue

        if result.result.type != "succeeded":
            logger.warning(
                "Request %s failed: %s", custom_id, result.result.type
            )
            failed += 1
            continue

        # Parse the response
        try:
            response_text = result.result.message.content[0].text.strip()

            # Strip markdown code fences if present
            code_block = re.search(
                r"```(?:json)?\s*\n?(.*?)\n?\s*```",
                response_text,
                re.DOTALL,
            )
            json_str = (
                code_block.group(1).strip() if code_block
                else response_text
            )

            parsed = json.loads(json_str)
        except (json.JSONDecodeError, IndexError, AttributeError) as exc:
            logger.warning(
                "Failed to parse response for %s: %s", custom_id, exc
            )
            failed += 1
            continue

        # Update session.meta.json
        meta_path = Path(archive_dir_str) / "session.meta.json"
        if not meta_path.exists():
            logger.warning("Meta file not found: %s", meta_path)
            failed += 1
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            # MERGE, do not replace. The Terra path writes a three_ps block
            # into auto_generated; replacing the dict wholesale deleted it,
            # so applying a Haiku batch over a Terra-enriched entry silently
            # destroyed the three-Ps summaries (audit finding AR13).
            # _write_enriched_meta a few hundred lines above already merges;
            # this is the same discipline on the batch path.
            existing = meta.get("auto_generated") or {}
            meta["auto_generated"] = {
                **existing,
                "title": parsed.get("title", "Untitled Session"),
                "purpose": parsed.get("purpose", ""),
                "tags": parsed.get("tags", []),
            }
            # Temp file plus atomic rename: a crash here used to truncate the
            # metadata, and a session with no parseable meta has no id, which
            # drops it out of every archived-ids set and re-arms the drift
            # gates on a session that IS archived.
            tmp = meta_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            tmp.replace(meta_path)
            applied += 1
        except Exception as exc:
            logger.warning(
                "Failed to update %s: %s", meta_path, exc
            )
            failed += 1

    logger.info(
        "\nEnrichment complete: %d applied, %d failed", applied, failed
    )
    if applied > 0:
        print(
            f"\nNext: python3 scripts/bulk-archive.py verify --fix-catalogue"
        )


# ============================================================================
# Verify
# ============================================================================


def write_catalogue(
    catalogue: dict[str, Any],
    logger: logging.Logger,
) -> None:
    """Write CATALOG.json under an exclusive lock, temp file plus rename.

    The old write was a bare ``write_text`` with no lock, so two concurrent
    ``verify --fix-catalogue`` runs interleaved, and a crash left truncated
    JSON. Truncated JSON matters more than it looks: ``discover`` reads the
    catalogue on every run, and an unguarded parse there took the whole
    command down (audit 2026-09-08, finding AR16).

    The lock is a sibling file rather than the catalogue itself, so the
    rename that replaces the catalogue cannot pull the lock out from under a
    waiting writer.
    """
    CATALOGUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = CATALOGUE_FILE.with_name(CATALOGUE_FILE.name + ".lock")
    payload = json.dumps(catalogue, indent=2)
    with open(lock_path, "w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            tmp = CATALOGUE_FILE.with_name(CATALOGUE_FILE.name + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(CATALOGUE_FILE)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _recorded_transcript_bytes(meta: dict[str, Any]) -> int | None:
    """The uncompressed transcript length the metadata claims, or ``None``.

    The v1.1 archive block records ``jsonl_bytes_uncompressed`` when the
    transcript was gzipped and ``jsonl_bytes`` when it was not; older entries
    carry only the latter. Both name the same quantity — the size of the raw
    JSONL — so either answers the completeness question.
    """
    archive_block = meta.get("archive")
    if not isinstance(archive_block, dict):
        return None
    for key in ("jsonl_bytes_uncompressed", "jsonl_bytes"):
        value = archive_block.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def cmd_verify(args: argparse.Namespace, logger: logging.Logger) -> int:
    """Run integrity checks and optionally rebuild the catalogue.

    Returns 1 when any integrity issue was found, 0 otherwise. This is a
    check, and a check that always exits 0 is not a check: verify printed
    size mismatches and non-canonical entries to stdout and then reported
    success, so AR3's detection half and AR21 were invisible to daily-sync
    and to cron, which read the exit status and not the report (audit round
    4c-2, finding 4). ``check-archive-drift.py`` and
    ``normalise-archive-storage.py`` already work this way.
    """
    # Add cc-session-toolkit to path
    ensure_toolkit_on_path()

    from cc_session_toolkit.catalogue import rebuild_catalogue

    # Scan archive for session.meta.json files
    archive_dirs: list[Path] = []
    for meta_path in sorted(DEFAULT_ARCHIVE_ROOT.rglob("session.meta.json")):
        archive_dirs.append(meta_path.parent)

    logger.info("Found %d archived sessions on disk", len(archive_dirs))

    # Check integrity
    issues: list[str] = []
    by_project: dict[str, int] = {}
    enriched = 0
    unenriched = 0

    for archive_dir in archive_dirs:
        meta_path = archive_dir / "session.meta.json"
        transcript: Path | None = None
        for candidate in ("session.jsonl.gz", "session.jsonl"):
            if (archive_dir / candidate).exists():
                transcript = archive_dir / candidate
                break

        if transcript is None:
            issues.append(f"Missing JSONL: {archive_dir}")
        elif transcript.name == "session.jsonl":
            # `session.jsonl.gz` is the canonical storage form (decided
            # 2026-08-22). An entry still holding raw JSONL is not searchable:
            # `_scan_archives.py` — the engine behind search-archives-safe.sh
            # — globs only `session.jsonl.gz`, so a raw-only entry is
            # invisible to every ad-hoc search while verify called it fine
            # (audit 2026-09-08, finding AR21). Report it; the repair is
            # `scripts/normalise-archive-storage.py --apply`.
            issues.append(
                f"Non-canonical storage (raw session.jsonl, not searchable): "
                f"{archive_dir}"
            )

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            project = meta.get("project", {}).get("name", "unknown")
            by_project[project] = by_project.get(project, 0) + 1

            # Completeness check (AR3): the archived transcript must be as
            # long as the metadata says it is. Until 2026-09-08 verify
            # compared the archive only against itself — existence and a
            # parseable meta — so a transcript copied mid-write passed every
            # check that existed, forever.
            if transcript is not None:
                recorded = _recorded_transcript_bytes(meta)
                actual = uncompressed_size(transcript)
                if recorded is not None and actual is not None \
                        and recorded != actual:
                    issues.append(
                        f"Size mismatch: {archive_dir} — metadata records "
                        f"{recorded} bytes, {transcript.name} holds {actual}"
                    )

            purpose = meta.get("auto_generated", {}).get("purpose", "")
            if (
                "unavailable" in purpose.lower()
                or "requires interactive" in purpose.lower()
            ):
                unenriched += 1
            else:
                enriched += 1
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(f"Bad metadata: {archive_dir}: {exc}")

    # Report
    print(f"\n{'=' * 60}")
    print("ARCHIVE VERIFICATION")
    print(f"{'=' * 60}")
    print(f"Total sessions:  {len(archive_dirs)}")
    print(f"Enriched:        {enriched}")
    print(f"Needs enrichment: {unenriched}")
    print()

    print(f"{'Project':<35} {'Count':>8}")
    print("-" * 45)
    for proj, count in sorted(by_project.items(), key=lambda x: -x[1]):
        print(f"{proj:<35} {count:>8}")

    if issues:
        print(f"\nIssues ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        logger.warning(
            "Archive verification found %d issue(s) — exiting non-zero",
            len(issues),
        )
    else:
        print("\nNo integrity issues found.")

    # Rebuild catalogue if requested
    if args.fix_catalogue:
        logger.info("Rebuilding catalogue...")
        catalogue = rebuild_catalogue(DEFAULT_ARCHIVE_ROOT)
        write_catalogue(catalogue, logger)
        n_sessions = len(catalogue.get("sessions", []))
        logger.info(
            "Catalogue rebuilt: %d sessions → %s",
            n_sessions, CATALOGUE_FILE,
        )
        print(
            "\nNext: python3 scripts/sync-sessions-to-postgres.py "
            "--full-resync"
        )

    # The catalogue rebuild is a repair, not a finding: an archive whose only
    # complaint was an out-of-date index is clean once it has been rebuilt.
    return 1 if issues else 0


# ============================================================================
# CLI
# ============================================================================


def main() -> int:
    """Parse arguments and dispatch to the appropriate mode.

    Returns the process exit status: non-zero when a checking mode found
    something wrong.
    """
    parser = argparse.ArgumentParser(
        description="Bulk archive historical Claude Code sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # discover
    p_discover = subparsers.add_parser(
        "discover", help="Scan for unarchived sessions"
    )
    p_discover.add_argument(
        "--min-content-chars", type=int, default=MIN_CONTENT_CHARS,
        help=(
            "Substance floor, in characters of user/assistant prose "
            f"(default: {MIN_CONTENT_CHARS}; 0 disables). This is the DEFAULT "
            "filter and the same rule check-archive-drift.py reports on, so "
            "running this command with its defaults archives exactly what the "
            "drift gate listed."
        ),
    )
    p_discover.add_argument(
        "--min-turns", type=int, default=0,
        help=(
            "Legacy turn-count filter (default: 0 = off). Turn count is a bad "
            "substance proxy: at --min-turns 5 it discarded 56 of 77 "
            "substantive sessions on 2026-07-28, including a 205,848-token "
            "session with two turns."
        ),
    )
    p_discover.add_argument(
        "--min-content-tokens", type=int, default=0,
        help=(
            "Legacy filter on the DISTILLED transcript, in tokens "
            "(default: 0 = off). Applied in addition to --min-content-chars. "
            f"The vetted equivalent floor is {MIN_CONTENT_TOKENS} tokens."
        ),
    )
    p_discover.add_argument(
        "--source-root", type=Path, default=CLAUDE_PROJECTS_DIR,
        help=(
            "Transcript store to scan. Accepts the live layout "
            "(<root>/<cwd-key>/*.jsonl) or a merged multi-machine snapshot "
            "(<root>/<machine>/<cwd-key>/*.jsonl). Default: "
            "~/.claude/projects. Use the snapshot when sessions from another "
            "machine must be included — the two stores are disjoint."
        ),
    )

    p_discover.add_argument(
        "--layout", choices=("auto", "live", "snapshot"), default="auto",
        help=(
            "Force the source store's layout instead of probing for it. "
            "'live' is <root>/<cwd-key>/*.jsonl; 'snapshot' is "
            "<root>/<machine>/<cwd-key>/*.jsonl. The probe refuses rather "
            "than guesses when the tree matches neither."
        ),
    )

    # archive
    p_archive = subparsers.add_parser(
        "archive", help="Compress and archive sessions"
    )
    p_archive.add_argument("--dry-run", action="store_true")
    p_archive.add_argument(
        "--retry-failed", action="store_true",
        help=(
            "Clear every recorded failure and try all of them again. Rarely "
            "needed: failures whose reason was transient, whose session is "
            f"now on disk, or which are older than {FAILED_RETRY_AFTER_DAYS} "
            "days are retried automatically."
        ),
    )
    p_archive.add_argument(
        "--force", action="store_true",
        help=(
            "Overwrite subagent transcripts that are already archived. Off "
            "by default: a re-run must not replace a good archived subagent "
            "with whatever the source holds now."
        ),
    )
    p_archive.add_argument(
        "--limit", type=int, default=0,
        help="Archive at most N sessions (0 = all)",
    )
    p_archive.add_argument(
        "--min-turns", type=int, default=0,
        help="Legacy turn filter for the discovery fallback (0 = off).",
    )
    p_archive.add_argument(
        "--min-content-chars", type=int, default=MIN_CONTENT_CHARS,
        help="As for `discover` (used only by the discovery fallback).",
    )
    p_archive.add_argument(
        "--source-root", type=Path, default=CLAUDE_PROJECTS_DIR,
        help="As for `discover` (used only by the discovery fallback).",
    )
    p_archive.add_argument(
        "--min-content-tokens", type=int, default=0,
        help="As for `discover` (used only by the discovery fallback).",
    )

    p_archive.add_argument(
        "--layout", choices=("auto", "live", "snapshot"), default="auto",
        help=(
            "Force the source store's layout instead of probing for it. "
            "'live' is <root>/<cwd-key>/*.jsonl; 'snapshot' is "
            "<root>/<machine>/<cwd-key>/*.jsonl. The probe refuses rather "
            "than guesses when the tree matches neither."
        ),
    )

    # enrich
    p_enrich = subparsers.add_parser(
        "enrich", help="Generate metadata via Batch API"
    )
    p_enrich.add_argument(
        "--batch-submit", action="store_true",
        help="Submit batch enrichment requests",
    )
    p_enrich.add_argument(
        "--batch-apply", type=str, default=None,
        help="Apply results from completed batch (provide batch ID)",
    )
    p_enrich.add_argument(
        "--limit", type=int, default=0,
        help="Enrich at most N sessions (0 = all)",
    )
    p_enrich.add_argument(
        "--provider", choices=("haiku", "terra"), default="haiku",
        help=(
            "Extractor to use. 'terra' (OpenAI GPT-5.6 Terra, real-time Flex) "
            "is the model chosen by the 2026-07-28 blinded bake-off; 'haiku' "
            "is the legacy Anthropic Batch path and writes no three-Ps "
            "summaries. Default 'haiku' for backwards compatibility."
        ),
    )
    p_enrich.add_argument(
        "--prompt", type=Path,
        default=(
            PA_DIR / "data/experiments/bake-off-metadata-2026-05-18/prompt.md"
        ),
        help="System prompt for the extractor (terra provider).",
    )
    p_enrich.add_argument(
        "--dry-run", action="store_true",
        help="Report the cost projection and make no API calls.",
    )
    p_enrich.add_argument(
        "--fallback-gemini", action="store_true",
        help=(
            "When Terra's content filter refuses a transcript "
            "(invalid_prompt), retry that session on Gemini 3.6 Flash. The "
            "refusal is deterministic, so a different provider is the only "
            "remedy. Only moderation refusals fall back."
        ),
    )
    p_enrich.add_argument(
        "--yes", action="store_true",
        help="Skip the interactive confirmation before live API calls.",
    )
    p_enrich.add_argument(
        "--responses-out", type=Path,
        default=LOG_DIR / "terra-enrich-responses",
        help=(
            "Directory for raw generated objects, written in the per-arm "
            "layout validate-session-metadata.py expects."
        ),
    )

    # subagents
    p_subagents = subparsers.add_parser(
        "subagents",
        help="Backfill orphan subagent transcripts into parent entries",
    )
    p_subagents.add_argument(
        "--source-root", type=Path, default=CLAUDE_PROJECTS_DIR,
        help="Transcript store to scan (as for `discover`).",
    )
    p_subagents.add_argument("--dry-run", action="store_true")

    # verify
    p_verify = subparsers.add_parser(
        "verify", help="Check archive integrity"
    )
    p_verify.add_argument(
        "--fix-catalogue", action="store_true",
        help="Rebuild CATALOG.json from disk",
    )

    args = parser.parse_args()
    logger = setup_logging()

    # Modes that CHECK return a status; modes that DO return None and are
    # reported through their own logging. A caller (daily-sync, cron) reads
    # the exit status, so a check that cannot fail the process is decoration.
    if args.mode == "discover":
        cmd_discover(args, logger)
    elif args.mode == "archive":
        cmd_archive(args, logger)
    elif args.mode == "enrich":
        cmd_enrich(args, logger)
    elif args.mode == "subagents":
        cmd_subagents(args, logger)
    elif args.mode == "verify":
        return cmd_verify(args, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
