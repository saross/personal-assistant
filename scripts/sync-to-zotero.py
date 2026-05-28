#!/usr/bin/env python3
"""
Sync source_insight memories from canonical JSONL to Zotero item notes.

Reads source_insight memories with a valid zotero_key from
memories/memories.jsonl, creates a note on the referenced Zotero item via
the pyzotero API, and updates the sync cursor.

Idempotency: each note written by this script includes a footer with the
originating memory ID. Before creating a note, existing notes on the item
are fetched and checked for the marker — if found, the memory is skipped.

Usage:
    venv/bin/python3 scripts/sync-to-zotero.py [--dry-run] [--limit N] [--verbose]

Environment variables:
    ZOTERO_LIBRARY_ID      — Your Zotero user or group library ID
    ZOTERO_API_KEY_PAPER_B — API token with write access to notes
                             (Paper-B-scoped under the target-suffixed
                             naming convention adopted 2026-05-22; see
                             workstream H in wiki/continuity.md and
                             global-claude-md/zotero-reference.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Shared quarantine helper (audit IC2 — quarantine-on-skip).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sync_cursor import (  # noqa: E402
    detect_jsonl_shrink,
    quarantine_record,
)

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

PA_DIR = Path(__file__).resolve().parent.parent
# Use symlink paths for consistency with sync-to-postgres.py
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
CURSOR_FILE = PA_DIR / "memories" / "sync-cursors.json"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "sync.log"
# Quarantine destination for memories whose Zotero target was missing at
# write time (audit IC2 / D-M10). Lives in the data submodule for
# consistency with the postgres quarantine paths but is .gitignored
# (data/.gitignore: memories/quarantine-*.jsonl) so quarantine events
# do not leak into the auto-commit cycle (audit IC6).
QUARANTINE_FILE = PA_DIR / "data" / "memories" / "quarantine-zotero-skipped.jsonl"

CURSOR_KEY = "zotero_sync_line"
API_SLEEP_SECONDS = 0.5  # Between API writes to avoid rate limits

# Zotero item keys are exactly 8 uppercase alphanumeric characters
ZOTERO_KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}$")

# Marker used to detect notes written by this script (embedded in footer)
NOTE_MARKER_PREFIX = "source_insight memory"


# -------------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------------

def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging to file and stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sync-to-zotero")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()  # Avoid duplicate handlers on re-import

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [sync-to-zotero] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO if verbose else logging.WARNING)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(sh)

    return logger


# -------------------------------------------------------------------------
# Cursor management
# -------------------------------------------------------------------------

def load_cursor() -> int:
    """Load the last synced line number (0 if no previous sync)."""
    if not CURSOR_FILE.exists():
        return 0
    try:
        data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        return int(data.get(CURSOR_KEY, 0))
    except (json.JSONDecodeError, ValueError, OSError):
        return 0


def save_cursor(line_number: int) -> None:
    """Save the current sync position to the cursor file."""
    data: dict[str, Any] = {}
    if CURSOR_FILE.exists():
        try:
            data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data[CURSOR_KEY] = line_number
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_FILE.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )


# -------------------------------------------------------------------------
# Memory filtering
# -------------------------------------------------------------------------

def is_valid_zotero_key(key: str | None) -> bool:
    """Check whether a value matches Zotero's 8-char alphanumeric key format."""
    return bool(key and ZOTERO_KEY_PATTERN.match(key))


def load_pending_memories(
    since_line: int,
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Load memories with a valid zotero_key starting at the given line.

    Returns:
        (pending_memories, new_cursor_line, skipped_legacy_count)

    ``new_cursor_line`` is the line after the last one read (never less
    than ``since_line`` — the cursor never rewinds, except in the
    explicit shrink-detection branch below). ``skipped_legacy_count``
    counts memories that matched category+zotero_key but had an invalid
    key format.

    Shrink detection (audit IC2 / D-C3): if the canonical JSONL has
    fewer lines than the saved cursor (compaction, dedup migration,
    submodule revert), we do **not** silently leave the cursor pinned
    beyond EOF — every subsequent sync would be a no-op until the file
    grew past that line, at which point earlier memories would be
    silently skipped. Instead we WARN, reset the effective cursor to 0,
    and force a full re-scan; idempotency is preserved by the existing
    "memory ID in note marker" check.
    """
    shrunk, line_count = detect_jsonl_shrink(MEMORIES_FILE, since_line)
    if shrunk:
        if logger is not None:
            logger.warning(
                "Canonical JSONL shrunk below saved cursor (cursor=%d, "
                "current_lines=%d). Resetting to 0 and forcing full "
                "re-scan; idempotency relies on the in-note marker check.",
                since_line, line_count,
            )
        since_line = 0

    pending: list[dict[str, Any]] = []
    skipped_legacy = 0
    # Sentinel tracking: None means "loop body never ran"
    last_index: int | None = None

    with open(MEMORIES_FILE, "r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh):
            last_index = line_num
            if line_num < since_line:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            try:
                mem = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            if mem.get("category") != "source_insight":
                continue
            zkey = mem.get("zotero_key")
            if not zkey:
                continue

            if is_valid_zotero_key(zkey):
                pending.append(mem)
            else:
                skipped_legacy += 1

    # Cursor never rewinds: advance to last_index + 1, but never below
    # the input since_line (which handles file-shorter-than-cursor cases).
    if last_index is None:
        new_cursor = since_line
    else:
        new_cursor = max(since_line, last_index + 1)
    return pending, new_cursor, skipped_legacy


# -------------------------------------------------------------------------
# Note formatting and parsing
# -------------------------------------------------------------------------

def format_note(memory: dict[str, Any]) -> str:
    """
    Render a memory as an HTML note for Zotero.

    Includes a footer with the memory ID so subsequent runs can detect
    that this memory has already been synced.
    """
    content = memory.get("content", "").strip()
    memory_id = memory.get("id", "")
    session_id = memory.get("session_id", "")
    session_short = session_id[:8] if session_id else "unknown"
    created_at = memory.get("created_at", "")
    created_date = created_at[:10] if created_at else "unknown"
    tags = memory.get("research_tags", [])
    tags_str = ", ".join(tags) if tags else ""

    # Escape HTML special characters in user content
    def esc(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    parts = [
        f"<p>{esc(content)}</p>",
    ]
    if tags_str:
        parts.append(f"<p><strong>Tags:</strong> {esc(tags_str)}</p>")
    parts.append("<hr>")
    parts.append(
        f"<p><em>— {NOTE_MARKER_PREFIX} "
        f"<code>{esc(memory_id)}</code> "
        f"(captured {esc(created_date)} in session {esc(session_short)})</em></p>"
    )
    return "".join(parts)


def extract_memory_ids_from_note(note_html: str) -> set[str]:
    """
    Parse an existing Zotero note and extract any memory IDs marked by
    this sync script. Returns an empty set for notes without markers.
    """
    # Look for: source_insight memory <code>ID</code>
    pattern = re.compile(
        re.escape(NOTE_MARKER_PREFIX) + r"\s*<code>([^<]+)</code>",
        re.IGNORECASE,
    )
    return set(pattern.findall(note_html))


def fetch_synced_memory_ids(
    zot: Any, item_key: str, logger: logging.Logger,
) -> set[str]:
    """
    Return the set of memory IDs already synced as notes on a Zotero item.

    Fetches child notes via pyzotero and scans each one for the marker.
    Returns an empty set on error (caller decides how to handle).
    """
    try:
        children = zot.children(item_key, itemType="note")
    except Exception as exc:  # noqa: BLE001 — graceful degradation
        logger.warning(
            f"Could not fetch existing notes for item {item_key}: "
            f"{type(exc).__name__}: {exc}"
        )
        return set()

    synced: set[str] = set()
    for child in children:
        note_html = child.get("data", {}).get("note", "")
        synced.update(extract_memory_ids_from_note(note_html))
    return synced


# -------------------------------------------------------------------------
# Zotero client
# -------------------------------------------------------------------------

def build_zotero_client() -> Any:
    """
    Initialise a pyzotero client using environment variables.

    Returns a pyzotero.Zotero instance configured for the user's library.
    Raises if credentials are missing or pyzotero is not installed.
    """
    library_id = os.environ.get("ZOTERO_LIBRARY_ID")
    api_key = os.environ.get("ZOTERO_API_KEY_PAPER_B")
    if not library_id or not api_key:
        raise RuntimeError(
            "ZOTERO_LIBRARY_ID and ZOTERO_API_KEY_PAPER_B must be set "
            "in the environment (see ~/personal-assistant/.env)."
        )

    try:
        from pyzotero import zotero as pyzotero_module
    except ImportError as exc:
        raise RuntimeError(
            "pyzotero is not installed. Run: "
            "venv/bin/pip install pyzotero"
        ) from exc

    return pyzotero_module.Zotero(library_id, "user", api_key)


def _is_not_found_exception(exc: Exception) -> bool:
    """
    Detect whether an exception indicates a missing Zotero item.

    Prefers the typed ResourceNotFound exception from pyzotero when
    available; falls back to string matching for older versions or
    transport-level errors.
    """
    try:
        from pyzotero.zotero_errors import ResourceNotFound
        if isinstance(exc, ResourceNotFound):
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return "not found" in msg or "404" in msg


# -------------------------------------------------------------------------
# Sync orchestration
# -------------------------------------------------------------------------

def sync_memory(
    zot: Any,
    memory: dict[str, Any],
    logger: logging.Logger,
    dry_run: bool,
) -> str:
    """
    Sync a single memory to its Zotero item.

    Returns one of: "created", "skipped_duplicate", "skipped_not_found",
    "failed".
    """
    mem_id = memory.get("id", "<unknown>")
    item_key = memory["zotero_key"]

    # Check for existing note with this memory ID
    existing_ids = fetch_synced_memory_ids(zot, item_key, logger)
    if mem_id in existing_ids:
        logger.debug(f"Skipping {mem_id} — already synced to {item_key}")
        return "skipped_duplicate"

    if dry_run:
        logger.info(f"[dry-run] Would create note for {mem_id} on {item_key}")
        return "created"

    # Create the note
    note_html = format_note(memory)
    try:
        template = zot.item_template("note")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Failed to get note template for {mem_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return "failed"

    template["note"] = note_html
    try:
        result = zot.create_items([template], parentid=item_key)
    except Exception as exc:  # noqa: BLE001
        if _is_not_found_exception(exc):
            logger.warning(
                f"Zotero item {item_key} not found for memory {mem_id} "
                f"— skipping"
            )
            return "skipped_not_found"
        logger.error(
            f"Failed to create note for {mem_id} on {item_key}: "
            f"{type(exc).__name__}: {exc}"
        )
        return "failed"

    # Check pyzotero result envelope. pyzotero.create_items() returns a
    # dict with up to four keys: successful, success, unchanged, failed.
    # Treat any of successful/success/unchanged as a non-failure outcome.
    if isinstance(result, dict):
        failed = result.get("failed", {})
        if failed:
            logger.error(
                f"Zotero reported failure for {mem_id}: {failed}"
            )
            return "failed"
        successful = result.get("successful", {})
        success = result.get("success", {})
        unchanged = result.get("unchanged", {})
        if successful or success or unchanged:
            logger.info(f"Created note for {mem_id} on {item_key}")
            return "created"

    logger.warning(f"Unexpected pyzotero response for {mem_id}: {result}")
    return "failed"


def run_sync(
    dry_run: bool = False,
    limit: int | None = None,
    verbose: bool = False,
) -> dict[str, int]:
    """
    Main sync entry point. Returns a summary dict of counts.
    """
    logger = setup_logging(verbose=verbose)
    logger.info(
        f"Starting sync (dry_run={dry_run}, limit={limit})"
    )

    cursor = load_cursor()
    logger.info(f"Resuming from line {cursor}")

    pending, new_cursor, skipped_legacy = load_pending_memories(cursor, logger)
    logger.info(
        f"Found {len(pending)} pending memories "
        f"({skipped_legacy} skipped as legacy format) "
        f"from lines {cursor}-{new_cursor - 1}"
    )

    if limit is not None and len(pending) > limit:
        logger.info(f"Limiting to first {limit} memories")
        pending = pending[:limit]

    summary = {
        "pending": len(pending),
        "created": 0,
        "skipped_duplicate": 0,
        "skipped_not_found": 0,
        "failed": 0,
        "skipped_legacy": skipped_legacy,
    }

    if not pending:
        logger.info("Nothing to sync.")
        if not dry_run and new_cursor > cursor:
            save_cursor(new_cursor)
            logger.info(f"Cursor advanced to {new_cursor}")
        return summary

    # Build client only when we have work to do
    try:
        zot = build_zotero_client() if not dry_run else None
    except RuntimeError as exc:
        logger.error(str(exc))
        return summary

    # Dry run still needs a client to check existing notes — but we can
    # skip that check and trust the user to verify manually
    if dry_run:
        for mem in pending:
            logger.info(
                f"[dry-run] Would sync memory {mem['id']} "
                f"→ Zotero item {mem['zotero_key']}"
            )
            summary["created"] += 1
        logger.info(f"Dry run complete. Summary: {summary}")
        return summary

    # Live sync — sequential per-memory. Batching the create_items calls
    # would require fetching existing notes per unique item first, which
    # adds complexity. Given expected volume (tens of memories per month),
    # sequential is fine. Revisit if scale demands it.
    #
    # ``skipped_not_found`` memories are quarantined here (audit IC2 /
    # D-M10) so the cursor can advance past them without losing the
    # record. A transiently-missing Zotero item (delete-then-restore,
    # cross-machine sync pending) would otherwise leave a permanent
    # silent gap; the operator can later replay from the quarantine.
    for mem in pending:
        outcome = sync_memory(zot, mem, logger, dry_run=False)
        summary[outcome] = summary.get(outcome, 0) + 1
        if outcome == "skipped_not_found":
            quarantine_record(
                QUARANTINE_FILE,
                mem,
                "zotero_item_missing",
                logger=logger,
            )
        # Only sleep after actions that touched the API for writes
        if outcome in ("created", "failed", "skipped_not_found"):
            time.sleep(API_SLEEP_SECONDS)

    # Only advance cursor if no hard failures (so retry picks up where we
    # left off). ``skipped_not_found`` is quarantined above and therefore
    # safe to advance past.
    if summary["failed"] == 0:
        save_cursor(new_cursor)
        logger.info(f"Cursor advanced to {new_cursor}")
    else:
        logger.warning(
            f"{summary['failed']} failures — cursor NOT advanced "
            f"(will retry on next run)"
        )

    logger.info(f"Sync complete. Summary: {summary}")
    return summary


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------

def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Sync source_insight memories to Zotero item notes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be synced without making API calls.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of memories to sync in this run.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging to stderr.",
    )
    args = parser.parse_args()

    summary = run_sync(
        dry_run=args.dry_run,
        limit=args.limit,
        verbose=args.verbose,
    )

    # Print summary to stdout for interactive use
    print(json.dumps(summary, indent=2))

    # Exit non-zero if anything failed
    sys.exit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
