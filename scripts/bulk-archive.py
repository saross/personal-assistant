#!/usr/bin/env python3
"""
Bulk archive historical Claude Code sessions.

Phase 2 of the progressive disclosure system. Archives unarchived sessions
from ~/.claude/projects/ into ~/cc-archives/, optionally enriches them
with Haiku-generated metadata via the Anthropic Batch API, and verifies
archive integrity.

Usage:
    python3 scripts/bulk-archive.py discover [--min-turns N]
    python3 scripts/bulk-archive.py archive [--dry-run] [--limit N] [--resume]
    python3 scripts/bulk-archive.py enrich --batch-submit [--limit N]
    python3 scripts/bulk-archive.py enrich --batch-apply BATCH_ID
    python3 scripts/bulk-archive.py verify [--fix-catalogue]

Modes:
    discover        Scan for unarchived sessions, build manifest, report stats
    archive         Compress and archive sessions (no API calls)
    enrich          Generate Haiku metadata via Batch API (submit or apply)
    verify          Integrity checks and catalogue rebuild
"""

import argparse
import gzip
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_ARCHIVE_ROOT = Path.home() / "cc-archives"
CATALOGUE_FILE = DEFAULT_ARCHIVE_ROOT / "CATALOG.json"

HAIKU_MODEL = "claude-haiku-4-5-20251001"

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
    LOG_DIR.mkdir(parents=True, exist_ok=True)
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


def resolve_project_mapping(
    logger: logging.Logger,
) -> dict[str, tuple[Path | None, str]]:
    """
    Build a mapping from encoded project directory names to (project_root,
    project_name) tuples.

    Strategy: for each project dir in ~/.claude/projects/, find a session
    JSONL and extract ``cwd``. Falls back to path reconstruction from the
    encoded name. When neither succeeds, ``project_root`` is ``None`` —
    the call site must consult ``archive_root`` instead of treating any
    fallback path as a real project directory.

    Returns:
        Dictionary mapping encoded dir name to (project_root, project_name).
        ``project_root`` may be ``None`` if it could not be resolved.
    """
    mapping: dict[str, tuple[Path | None, str]] = {}

    if not CLAUDE_PROJECTS_DIR.is_dir():
        logger.warning("Claude projects dir not found: %s", CLAUDE_PROJECTS_DIR)
        return mapping

    for proj_dir in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue

        encoded = proj_dir.name
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


def discover_sessions(
    project_mapping: dict[str, tuple[Path | None, str]],
    min_turns: int,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    """
    Scan for unarchived sessions, filter trivials, build a manifest.

    Returns:
        List of session manifest entries, sorted by project then session ID.
    """
    # Add cc-session-toolkit to path for imports
    toolkit_src = Path.home() / "Code" / "cc-session-toolkit" / "src"
    if str(toolkit_src) not in sys.path:
        sys.path.insert(0, str(toolkit_src))

    from cc_session_toolkit.archive import (
        extract_session_stats,
        get_archived_session_ids,
        get_session_id,
        is_trivial_session,
    )

    # Load already-archived session IDs for deduplication
    archived_ids: set[str] = set()
    if CATALOGUE_FILE.exists():
        archived_ids = get_archived_session_ids(CATALOGUE_FILE)
        logger.info("Found %d already-archived sessions", len(archived_ids))

    manifest: list[dict[str, Any]] = []
    total_skipped_trivial = 0
    total_skipped_archived = 0
    total_skipped_agent = 0

    for encoded, (project_root, project_name) in sorted(
        project_mapping.items()
    ):
        proj_dir = CLAUDE_PROJECTS_DIR / encoded

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

            # Extract stats for trivial filtering
            try:
                stats = extract_session_stats(jsonl_file)
            except Exception as exc:
                logger.warning(
                    "Failed to extract stats for %s: %s", jsonl_file, exc
                )
                continue

            if is_trivial_session(stats, min_turns=min_turns):
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

            manifest.append({
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
            })

    logger.info(
        "Discovery complete: %d sessions to archive, "
        "%d skipped (trivial), %d skipped (already archived), "
        "%d skipped (flat agents)",
        len(manifest), total_skipped_trivial,
        total_skipped_archived, total_skipped_agent,
    )

    return manifest


def cmd_discover(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Run the discover mode: scan, filter, report, save manifest."""
    project_mapping = resolve_project_mapping(logger)
    manifest = discover_sessions(project_mapping, args.min_turns, logger)

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


def _load_checkpoint() -> dict[str, Any]:
    """Load the archive checkpoint file, or return empty state."""
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
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


def _save_checkpoint(checkpoint: dict[str, Any]) -> None:
    """Persist the checkpoint to disk."""
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(
        json.dumps(checkpoint, indent=2), encoding="utf-8"
    )


def archive_subagents(
    source_session_dir: Path,
    archive_dir: Path,
    logger: logging.Logger,
) -> int:
    """
    Compress subagent JSONL files from a session's subagents directory
    into the archive directory.

    Returns:
        Number of subagents archived.
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
    for sa_file in subagent_files:
        dest_gz = subagent_dest / f"{sa_file.stem}.jsonl.gz"

        try:
            with open(sa_file, "rb") as f_in:
                with gzip.open(dest_gz, "wb") as f_out:
                    # Stream in chunks to keep memory bounded
                    while True:
                        chunk = f_in.read(8192)
                        if not chunk:
                            break
                        f_out.write(chunk)
            count += 1
        except Exception as exc:
            logger.warning(
                "Failed to archive subagent %s: %s", sa_file.name, exc
            )

    return count


def cmd_archive(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Run the archive mode: compress and archive sessions."""
    # Add cc-session-toolkit to path
    toolkit_src = Path.home() / "Code" / "cc-session-toolkit" / "src"
    if str(toolkit_src) not in sys.path:
        sys.path.insert(0, str(toolkit_src))

    from cc_session_toolkit.archive import archive_session

    # Load manifest
    if not MANIFEST_FILE.exists():
        logger.info("No manifest found — running discovery first...")
        project_mapping = resolve_project_mapping(logger)
        manifest = discover_sessions(project_mapping, args.min_turns, logger)
        MANIFEST_FILE.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    else:
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        logger.info("Loaded manifest with %d sessions", len(manifest))

    # Load checkpoint for resume
    checkpoint = _load_checkpoint()
    already_done = set(checkpoint["archived_ids"])
    already_failed = set(checkpoint["failed_ids"].keys())

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
                checkpoint["failed_ids"][session_id] = "archive_session returned None"
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
                )
                if sa_count > 0:
                    logger.info(
                        "  Archived %d subagents for %s",
                        sa_count, session_id[:8],
                    )

            # Update checkpoint
            checkpoint["archived_ids"].append(session_id)
            checkpoint["stats"]["total_archived"] += 1
            checkpoint["stats"]["total_subagents"] += sa_count
            _save_checkpoint(checkpoint)

            archived_count += 1
            subagent_count += sa_count

        except Exception as exc:
            logger.error(
                "Failed to archive %s (%s): %s",
                session_id[:8], project_name, exc,
            )
            checkpoint["failed_ids"][session_id] = str(exc)
            _save_checkpoint(checkpoint)

    logger.info(
        "\nArchive complete: %d sessions, %d subagents archived",
        archived_count, subagent_count,
    )
    if checkpoint["failed_ids"]:
        logger.warning(
            "%d sessions failed — see checkpoint: %s",
            len(checkpoint["failed_ids"]), CHECKPOINT_FILE,
        )

    print(f"\nNext: python3 scripts/bulk-archive.py verify --fix-catalogue")


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


def cmd_enrich(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Run the enrich mode: batch submit or batch apply."""
    load_env()

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
    toolkit_src = Path.home() / "Code" / "cc-session-toolkit" / "src"
    if str(toolkit_src) not in sys.path:
        sys.path.insert(0, str(toolkit_src))

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
    print(f"Mode:        Anthropic Batch API (50% discount)")
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
    BATCH_STATE_FILE.write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )

    logger.info(
        "Batch submitted: %s | %d requests | Status: %s",
        batch_id, len(requests), batch_job.processing_status,
    )
    print(f"\nBatch ID: {batch_id}")
    print(f"State saved: {BATCH_STATE_FILE}")
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

    # Load state to get session_id_map
    if not BATCH_STATE_FILE.exists():
        logger.error("No batch state file found: %s", BATCH_STATE_FILE)
        sys.exit(1)

    state = json.loads(BATCH_STATE_FILE.read_text(encoding="utf-8"))
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
            meta["auto_generated"] = {
                "title": parsed.get("title", "Untitled Session"),
                "purpose": parsed.get("purpose", ""),
                "tags": parsed.get("tags", []),
            }
            meta_path.write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
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


def cmd_verify(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Run integrity checks and optionally rebuild the catalogue."""
    # Add cc-session-toolkit to path
    toolkit_src = Path.home() / "Code" / "cc-session-toolkit" / "src"
    if str(toolkit_src) not in sys.path:
        sys.path.insert(0, str(toolkit_src))

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
        has_jsonl = (
            (archive_dir / "session.jsonl.gz").exists()
            or (archive_dir / "session.jsonl").exists()
        )

        if not has_jsonl:
            issues.append(f"Missing JSONL: {archive_dir}")

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            project = meta.get("project", {}).get("name", "unknown")
            by_project[project] = by_project.get(project, 0) + 1

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
    else:
        print("\nNo integrity issues found.")

    # Rebuild catalogue if requested
    if args.fix_catalogue:
        logger.info("Rebuilding catalogue...")
        catalogue = rebuild_catalogue(DEFAULT_ARCHIVE_ROOT)
        CATALOGUE_FILE.write_text(
            json.dumps(catalogue, indent=2), encoding="utf-8"
        )
        n_sessions = len(catalogue.get("sessions", []))
        logger.info(
            "Catalogue rebuilt: %d sessions → %s",
            n_sessions, CATALOGUE_FILE,
        )
        print(
            f"\nNext: python3 scripts/sync-sessions-to-postgres.py "
            f"--full-resync"
        )


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    """Parse arguments and dispatch to the appropriate mode."""
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
        "--min-turns", type=int, default=5,
        help="Minimum turns to keep (default: 5)",
    )

    # archive
    p_archive = subparsers.add_parser(
        "archive", help="Compress and archive sessions"
    )
    p_archive.add_argument("--dry-run", action="store_true")
    p_archive.add_argument(
        "--limit", type=int, default=0,
        help="Archive at most N sessions (0 = all)",
    )
    p_archive.add_argument(
        "--min-turns", type=int, default=5,
        help="Minimum turns for discovery fallback (default: 5)",
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

    if args.mode == "discover":
        cmd_discover(args, logger)
    elif args.mode == "archive":
        cmd_archive(args, logger)
    elif args.mode == "enrich":
        cmd_enrich(args, logger)
    elif args.mode == "verify":
        cmd_verify(args, logger)


if __name__ == "__main__":
    main()
