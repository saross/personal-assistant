#!/usr/bin/env python3
"""
Backfill summaries for existing memories that lack them.

Reads memories.jsonl, batches records without summaries, sends each
batch to Haiku for summary generation, and rewrites the JSONL file
with summaries added. Designed to be run incrementally — records that
already have summaries are skipped.

Usage:
    python3 scripts/backfill-summaries.py [--dry-run] [--batch-size N] [--limit N]

Options:
    --dry-run       Show what would be done without making API calls
    --batch-size N  Memories per API call (default: 20)
    --limit N       Process at most N memories (for testing)
    --delay S       Seconds between API calls (default: 0.5)
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PA_DIR / ".env"
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "backfill-summaries.log"

HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BATCH_SIZE = 20
DEFAULT_DELAY = 0.5
MAX_SUMMARY_CHARS = 150

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
# Core logic
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


def generate_summaries(
    batch: list[dict],
    logger: logging.Logger,
) -> dict[str, str]:
    """Send a batch to Haiku and return id → summary mapping."""
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


def write_memories(records: list[dict | None]) -> None:
    """Write all records back to the JSONL file."""
    with open(MEMORIES_FILE, "w", encoding="utf-8") as f:
        for record in records:
            if record is None:
                f.write("\n")
            else:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
        help=f"Seconds between API calls (default: {DEFAULT_DELAY})",
    )
    args = parser.parse_args()

    load_env()
    logger = setup_logging()

    # Load all records
    all_records = load_memories()
    total_records = sum(1 for r in all_records if r is not None)

    # Identify records needing summaries
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

    if args.dry_run:
        batches = (len(to_backfill) + args.batch_size - 1) // args.batch_size
        est_time = batches * (args.delay + 1.5)  # ~1.5s per API call
        logger.info(
            "Dry run: would process %d memories in %d batches (~%.0fs)",
            len(to_backfill),
            batches,
            est_time,
        )
        return

    # Process in batches
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

        # Apply summaries back to the records in all_records
        batch_hits = 0
        for idx, record in batch_items:
            mem_id = record.get("id", "unknown")
            if mem_id in summaries:
                all_records[idx]["summary"] = summaries[mem_id]
                batch_hits += 1
            else:
                total_failed += 1
                logger.warning("No summary returned for id=%s", mem_id)

        total_generated += batch_hits
        logger.info(
            "  → %d/%d summaries generated", batch_hits, len(batch_items)
        )

        # Write after each batch for incremental progress
        write_memories(all_records)

        # Rate limiting delay (skip after last batch)
        if batch_start + args.batch_size < len(to_backfill):
            time.sleep(args.delay)

    logger.info(
        "Backfill complete: %d generated, %d failed, %d total with summaries",
        total_generated,
        total_failed,
        already_have + total_generated,
    )


if __name__ == "__main__":
    main()
