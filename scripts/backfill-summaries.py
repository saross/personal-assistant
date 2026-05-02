#!/usr/bin/env python3
"""
Backfill summaries for existing memories that lack them.

Reads memories.jsonl, batches records without summaries, sends each
batch to Haiku for summary generation, and rewrites the JSONL file
with summaries added. Designed to be run incrementally — records that
already have summaries are skipped.

Usage:
    python3 scripts/backfill-summaries.py [--dry-run] [--batch-size N] [--limit N]
    python3 scripts/backfill-summaries.py --batch-api [--batch-size N] [--limit N]
    python3 scripts/backfill-summaries.py --batch-apply BATCH_ID

Modes:
    (default)       Synchronous — one API call per batch, writes after each
    --batch-api     Submit all batches as a single Anthropic Batch API job
                    (50% discount, processes within 24h). Prints the batch ID.
    --batch-apply   Retrieve results from a completed batch job and apply
                    summaries to memories.jsonl.

Options:
    --dry-run       Show what would be done without making API calls
    --batch-size N  Memories per API call (default: 20)
    --limit N       Process at most N memories (for testing)
    --delay S       Seconds between API calls, sync mode only (default: 0.5)
"""

import argparse
import atexit
import json
import logging
import os
import sys
import time
from pathlib import Path
import sys as _sys_for_guard_import

# Guard against racing with extraction-hook appends or scheduled sync.
# See scripts/_bulk_rewrite_guard.py.
_sys_for_guard_import.path.insert(0, str(Path(__file__).resolve().parent))
from _bulk_rewrite_guard import (  # noqa: E402
    ensure_safe_to_rewrite,
    lock_jsonl_for_rewrite,
    release_lock,
)

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PA_DIR / ".env"
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "backfill-summaries.log"
BATCH_STATE_FILE = LOG_DIR / "backfill-batch-state.json"

HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BATCH_SIZE = 20
DEFAULT_DELAY = 0.5
MAX_SUMMARY_CHARS = 150

# Static instruction portion of the prompt (sent as system message in
# batch mode, inlined in user message in sync mode).
SUMMARY_INSTRUCTIONS = (
    f"Generate a one-sentence summary (max {MAX_SUMMARY_CHARS} characters) "
    "for each memory below. The summary must be self-contained and capture "
    "the core insight or decision.\n\n"
    "Return a JSON array of objects, each with:\n"
    '- "id": the memory\'s id (copied exactly from input)\n'
    '- "summary": the one-sentence summary\n\n'
    "Return ONLY the JSON array, no markdown fences or commentary."
)

# Legacy combined prompt for sync mode
SUMMARY_PROMPT = """Generate a one-sentence summary (max {max_chars} characters) for each \
memory below. The summary must be self-contained and capture the core insight or decision.

Return a JSON array of objects, each with:
- "id": the memory's id (copied exactly from input)
- "summary": the one-sentence summary

## Memories

{memories_json}
"""

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
    logger = logging.getLogger("backfill-summaries")
    logger.setLevel(logging.INFO)

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    return logger


# ============================================================================
# Core logic — shared
# ============================================================================


def load_memories() -> list[dict]:
    """Load all memories from JSONL, preserving order."""
    records = []
    with open(MEMORIES_FILE, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                records.append(None)  # Preserve blank lines
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                logging.getLogger("backfill-summaries").warning(
                    "Skipping malformed line %d: %s", i, e
                )
                records.append(None)
    return records


def needs_summary(record: dict | None) -> bool:
    """Check whether a record needs a summary generated."""
    if record is None:
        return False
    if not isinstance(record, dict):
        return False
    if record.get("summary"):
        return False
    if not record.get("content"):
        return False
    return True


def format_batch_input(batch: list[dict]) -> str:
    """Format a batch of memories for the API prompt."""
    items = []
    for mem in batch:
        items.append({
            "id": mem.get("id", "unknown"),
            "category": mem.get("category", ""),
            "content": mem.get("content", ""),
        })
    return json.dumps(items, indent=2)


def parse_response(response_text: str) -> dict[str, str]:
    """
    Parse Haiku's response into a mapping of id → summary.

    Handles markdown code fences that Haiku sometimes wraps around JSON.
    """
    text = response_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].startswith("```"):
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])

    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed)}")

    result = {}
    for item in parsed:
        if isinstance(item, dict) and "id" in item and "summary" in item:
            summary = item["summary"]
            # Truncate if Haiku exceeded the limit
            if len(summary) > MAX_SUMMARY_CHARS:
                summary = summary[:MAX_SUMMARY_CHARS - 1] + "…"
            result[item["id"]] = summary
    return result


def write_memories(records: list[dict | None]) -> None:
    """Write all records back to the JSONL file.

    After writing, verify the file's line count matches the in-memory
    record count. If it doesn't, the file has been corrupted (an
    historical "append instead of overwrite" regression, a concurrent
    writer interfering, or a partial write) and we raise loudly rather
    than leave a silently broken canonical.

    NOTE: this function truncates and rewrites the canonical. Callers
    MUST wrap it (and the immediately preceding load) in
    ``lock_jsonl_for_rewrite(MEMORIES_FILE)`` so concurrent appends
    from the extraction hook are not silently overwritten.
    """
    expected = len(records)
    # Atomic-ish write: stage to a temp path, fsync, then rename. The
    # surrounding LOCK_EX (held by the caller via
    # ``lock_jsonl_for_rewrite``) keeps the extraction-hook appender
    # blocked for the duration. We retain the post-write line-count
    # invariant from the original implementation.
    tmp_path = MEMORIES_FILE.with_suffix(MEMORIES_FILE.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for record in records:
            if record is None:
                f.write("\n")
            else:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.rename(str(tmp_path), str(MEMORIES_FILE))
    # Invariant: file line count must equal in-memory record count.
    with open(MEMORIES_FILE, encoding="utf-8") as f:
        actual = sum(1 for _ in f)
    if actual != expected:
        raise RuntimeError(
            f"write_memories invariant violated: wrote {actual} lines, "
            f"expected {expected}. Canonical may be corrupted — investigate "
            f"before any further sync operations."
        )


def _apply_summaries_under_lock(
    summaries: dict[str, str],
    logger: logging.Logger,
) -> tuple[int, int]:
    """
    Apply a ``{id: summary}`` mapping to the canonical under LOCK_EX.

    Re-reads the file inside the lock, attaches each summary to the
    matching record, and rewrites. Re-reading inside the lock means
    any extraction-hook appends that landed since the previous
    invocation are preserved. Returns ``(applied, missing)`` —
    summaries that matched a record vs ones whose id was not found.
    """
    if not summaries:
        return 0, 0
    with lock_jsonl_for_rewrite(MEMORIES_FILE):
        records = load_memories()
        applied = 0
        missing = 0
        index_by_id: dict[str, int] = {}
        for i, rec in enumerate(records):
            if rec is None:
                continue
            mid = rec.get("id")
            if mid:
                index_by_id[mid] = i
        for mid, summary in summaries.items():
            idx = index_by_id.get(mid)
            if idx is None:
                missing += 1
                continue
            rec = records[idx]
            if rec is None:
                missing += 1
                continue
            rec["summary"] = summary
            applied += 1
        if applied:
            write_memories(records)
        else:
            logger.info("No summaries matched on re-read — skipping rewrite")
    return applied, missing


# ============================================================================
# Sync mode (original)
# ============================================================================


def generate_summaries(
    batch: list[dict],
    logger: logging.Logger,
) -> dict[str, str]:
    """Send a batch to Haiku synchronously and return id → summary mapping."""
    from anthropic import Anthropic

    prompt = SUMMARY_PROMPT.format(
        max_chars=MAX_SUMMARY_CHARS,
        memories_json=format_batch_input(batch),
    )

    client = Anthropic()
    try:
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error("API call failed: %s", e)
        return {}

    if not response.content:
        logger.error("Empty response from Haiku")
        return {}

    first_block = response.content[0]
    if not hasattr(first_block, "text") or not first_block.text:
        logger.error("Response block has no text: %s", type(first_block))
        return {}

    try:
        return parse_response(first_block.text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse response: %s", e)
        logger.debug("Raw response: %s", first_block.text[:500])
        return {}


def run_sync(
    to_backfill: list[tuple[int, dict]],
    all_records: list[dict | None],
    already_have: int,
    args: argparse.Namespace,
    logger: logging.Logger,
) -> None:
    """Run backfill in synchronous mode (original behaviour).

    Each batch's summaries are applied under ``lock_jsonl_for_rewrite``
    by re-reading the canonical inside the lock, so any extraction-hook
    appends that landed since the previous batch are preserved.
    The ``all_records`` list is kept in sync with the on-disk state for
    in-memory progress tracking, but the disk write reads fresh records
    each time.
    """
    total_generated = 0
    total_failed = 0
    batch_count = 0

    for batch_start in range(0, len(to_backfill), args.batch_size):
        batch_items = to_backfill[batch_start:batch_start + args.batch_size]
        batch_records = [r for _, r in batch_items]
        batch_count += 1

        logger.info(
            "Batch %d: processing %d memories (%d/%d)…",
            batch_count,
            len(batch_records),
            batch_start + len(batch_items),
            len(to_backfill),
        )

        summaries = generate_summaries(batch_records, logger)

        batch_hits = 0
        for idx, record in batch_items:
            mem_id = record.get("id", "unknown")
            if mem_id in summaries:
                # Track in memory so subsequent batches see the
                # update for any progress reporting.
                if all_records[idx] is not None:
                    all_records[idx]["summary"] = summaries[mem_id]
                batch_hits += 1
            else:
                total_failed += 1
                logger.warning("No summary returned for id=%s", mem_id)

        total_generated += batch_hits
        logger.info(
            "  → %d/%d summaries generated", batch_hits, len(batch_items)
        )

        # Write after each batch for incremental progress, holding
        # LOCK_EX so concurrent extraction-hook appends are queued
        # behind us rather than silently overwritten.
        applied, missing = _apply_summaries_under_lock(summaries, logger)
        if missing:
            logger.warning(
                "Batch %d: %d summary id(s) not found in canonical "
                "on re-read (likely dedup or rewrite happened mid-run)",
                batch_count, missing,
            )

        # Rate limiting delay (skip after last batch)
        if batch_start + args.batch_size < len(to_backfill):
            time.sleep(args.delay)

    logger.info(
        "Backfill complete: %d generated, %d failed, %d total with summaries",
        total_generated,
        total_failed,
        already_have + total_generated,
    )


# ============================================================================
# Batch API mode
# ============================================================================


def run_batch_submit(
    to_backfill: list[tuple[int, dict]],
    args: argparse.Namespace,
    logger: logging.Logger,
) -> None:
    """Submit all batches as a single Anthropic Batch API job."""
    from anthropic import Anthropic

    client = Anthropic()

    # Build batch requests
    requests = []
    batch_index_map = {}  # custom_id → list of memory IDs in that batch

    for batch_start in range(0, len(to_backfill), args.batch_size):
        batch_items = to_backfill[batch_start:batch_start + args.batch_size]
        batch_records = [r for _, r in batch_items]
        custom_id = f"batch-{batch_start}"

        batch_index_map[custom_id] = [
            r.get("id", "unknown") for _, r in batch_items
        ]

        requests.append({
            "custom_id": custom_id,
            "params": {
                "model": HAIKU_MODEL,
                "max_tokens": 4096,
                "messages": [{
                    "role": "user",
                    "content": SUMMARY_PROMPT.format(
                        max_chars=MAX_SUMMARY_CHARS,
                        memories_json=format_batch_input(batch_records),
                    ),
                }],
            },
        })

    n_requests = len(requests)
    n_memories = len(to_backfill)
    logger.info(
        "Submitting batch job: %d requests covering %d memories",
        n_requests,
        n_memories,
    )

    try:
        batch_job = client.messages.batches.create(requests=requests)
    except Exception as e:
        logger.error("Batch submission failed: %s", e)
        sys.exit(1)

    batch_id = batch_job.id
    logger.info("Batch job submitted: %s", batch_id)
    logger.info(
        "Status: %s | Processing: %s",
        batch_job.processing_status,
        f"{batch_job.request_counts.processing}/{n_requests}",
    )

    # Save state for --batch-apply
    state = {
        "batch_id": batch_id,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_requests": n_requests,
        "n_memories": n_memories,
        "batch_size": args.batch_size,
        "batch_index_map": batch_index_map,
    }
    BATCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BATCH_STATE_FILE.write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Batch state saved to %s", BATCH_STATE_FILE)
    logger.info(
        "Run 'python3 scripts/backfill-summaries.py --batch-apply %s' "
        "to apply results once the batch completes.",
        batch_id,
    )


def run_batch_apply(
    batch_id: str,
    logger: logging.Logger,
) -> None:
    """Retrieve results from a completed batch job and apply summaries."""
    from anthropic import Anthropic

    # Guard against racing with extraction-hook appends or scheduled
    # sync (this path rewrites memories.jsonl in place).
    ensure_safe_to_rewrite(
        reason=f"backfill-summaries --batch-apply {batch_id}"
    )
    atexit.register(release_lock)
    logger.info(
        "TIP: commit the result with the trailer so M3 shrink-check "
        "recognises it as intentional:\n"
        "    cd data && git commit -m 'backfill: summaries from batch %s' -m 'Rewrite-Class: bulk'",
        batch_id,
    )

    client = Anthropic()

    # Check batch status
    try:
        batch_job = client.messages.batches.retrieve(batch_id)
    except Exception as e:
        logger.error("Failed to retrieve batch %s: %s", batch_id, e)
        sys.exit(1)

    logger.info(
        "Batch %s — status: %s, succeeded: %d, errored: %d, "
        "expired: %d, cancelled: %d",
        batch_id,
        batch_job.processing_status,
        batch_job.request_counts.succeeded,
        batch_job.request_counts.errored,
        batch_job.request_counts.expired,
        batch_job.request_counts.canceled,
    )

    if batch_job.processing_status != "ended":
        logger.error(
            "Batch is not complete yet (status: %s). Try again later.",
            batch_job.processing_status,
        )
        sys.exit(1)

    # Load memories outside the lock for progress reporting; the
    # actual rewrite happens inside ``lock_jsonl_for_rewrite`` below
    # via ``_apply_summaries_under_lock``, which re-reads the file
    # under the lock to pick up any extraction-hook appends that
    # arrived during the API roundtrips above.
    all_records = load_memories()
    # Build an ID → index lookup for fast updates
    id_to_index = {}
    for i, rec in enumerate(all_records):
        if rec is not None and rec.get("id"):
            id_to_index[rec["id"]] = i

    # Retrieve results and accumulate id → summary, then apply once
    # at the end under the rewrite lock.
    total_applied = 0
    total_failed = 0
    total_parse_errors = 0
    pending_summaries: dict[str, str] = {}

    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id

        if result.result.type != "succeeded":
            logger.warning(
                "Request %s: %s", custom_id, result.result.type
            )
            total_failed += 1
            continue

        message = result.result.message
        if not message.content:
            logger.warning("Request %s: empty response", custom_id)
            total_failed += 1
            continue

        response_text = message.content[0].text
        try:
            summaries = parse_response(response_text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "Request %s: parse error: %s", custom_id, e
            )
            total_parse_errors += 1
            continue

        for mem_id, summary in summaries.items():
            idx = id_to_index.get(mem_id)
            if idx is not None and all_records[idx] is not None:
                all_records[idx]["summary"] = summary
                pending_summaries[mem_id] = summary
                total_applied += 1

    # Write updated records under LOCK_EX (re-reads inside the lock).
    if pending_summaries:
        applied, missing = _apply_summaries_under_lock(
            pending_summaries, logger,
        )
        if missing:
            logger.warning(
                "%d summary id(s) not found in canonical on re-read "
                "(likely dedup happened between load and write)",
                missing,
            )

    total_with_summaries = sum(
        1 for r in all_records
        if r is not None and r.get("summary")
    )
    logger.info(
        "Applied %d summaries (%d failed, %d parse errors). "
        "Total with summaries: %d/%d",
        total_applied,
        total_failed,
        total_parse_errors,
        total_with_summaries,
        sum(1 for r in all_records if r is not None),
    )


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    """Run the backfill process."""
    parser = argparse.ArgumentParser(
        description="Backfill summaries for memories without them"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making API calls",
    )
    parser.add_argument(
        "--batch-api",
        action="store_true",
        help="Submit as Anthropic Batch API job (50%% discount)",
    )
    parser.add_argument(
        "--batch-apply",
        type=str,
        metavar="BATCH_ID",
        help="Apply results from a completed batch job",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Memories per API call (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N memories (0 = all)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Seconds between API calls, sync mode (default: {DEFAULT_DELAY})",
    )
    args = parser.parse_args()

    load_env()
    logger = setup_logging()

    # --batch-apply mode: retrieve and apply results
    if args.batch_apply:
        run_batch_apply(args.batch_apply, logger)
        return

    # Load and identify records needing summaries
    all_records = load_memories()
    total_records = sum(1 for r in all_records if r is not None)

    to_backfill = [
        (i, r) for i, r in enumerate(all_records) if needs_summary(r)
    ]

    if args.limit > 0:
        to_backfill = to_backfill[:args.limit]

    already_have = total_records - len(
        [r for r in all_records if needs_summary(r)]
    )
    logger.info(
        "Total records: %d | Already have summaries: %d | To backfill: %d",
        total_records,
        already_have,
        len(to_backfill),
    )

    if not to_backfill:
        logger.info("Nothing to backfill — all records have summaries.")
        return

    # Guard against racing with extraction-hook appends or scheduled
    # sync. Dry-run and --batch-api submission skip — they do not write
    # the canonical file. --batch-apply mode is the writer; the guard
    # runs there instead (handled in run_batch_apply).
    if not args.dry_run and not args.batch_api:
        ensure_safe_to_rewrite(reason="backfill-summaries: write summary field to memories.jsonl")
        atexit.register(release_lock)
        logger.info(
            "TIP: commit the result with the trailer so M3 shrink-check "
            "recognises it as intentional:\n"
            "    cd data && git commit -m 'backfill: summaries' -m 'Rewrite-Class: bulk'"
        )

    if args.dry_run:
        n_batches = (len(to_backfill) + args.batch_size - 1) // args.batch_size
        est_time = n_batches * (args.delay + 1.5)
        logger.info(
            "Dry run: would process %d memories in %d batches (~%.0fs sync)",
            len(to_backfill),
            n_batches,
            est_time,
        )
        return

    if args.batch_api:
        run_batch_submit(to_backfill, args, logger)
    else:
        run_sync(to_backfill, all_records, already_have, args, logger)


if __name__ == "__main__":
    main()
