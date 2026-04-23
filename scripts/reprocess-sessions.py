#!/usr/bin/env python3
"""
Reprocess archived sessions to extract memories from historical transcripts.

Targets sessions that predate the extraction hook (no memories extracted).
Uses the same extraction prompt and formatting as the live hook, submitted
via the Anthropic Batch API for cost efficiency.

Usage:
    venv/bin/python3 scripts/reprocess-sessions.py discover
    venv/bin/python3 scripts/reprocess-sessions.py submit [--limit N] [--dry-run]
    venv/bin/python3 scripts/reprocess-sessions.py apply BATCH_ID
    venv/bin/python3 scripts/reprocess-sessions.py status BATCH_ID

Modes:
    discover    Identify sessions needing reprocessing, report stats
    submit      Build extraction requests and submit to Haiku Batch API
    apply       Retrieve batch results and append memories to JSONL
    status      Check batch processing status
"""

import argparse
import atexit
import gzip
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Guard against racing with extraction-hook appends or scheduled sync.
# See scripts/_bulk_rewrite_guard.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bulk_rewrite_guard import ensure_safe_to_rewrite, release_lock  # noqa: E402
from typing import Any, Optional

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PA_DIR / ".env"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "reprocess-sessions.log"
BATCH_STATE_FILE = LOG_DIR / "reprocess-batch-state.json"
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
TAG_VOCAB_FILE = PA_DIR / "memories" / "tag-vocabulary.txt"
ARCHIVE_ROOT = Path.home() / "cc-archives"

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS_OUTPUT = 4096
MAX_EXCHANGES = 30
MAX_MESSAGE_CHARS = 3000
MAX_THINKING_CHARS = 1500
MIN_CONTENT_LENGTH = 500

# Cost estimates (Haiku Batch API — 50% off standard)
BATCH_INPUT_COST_PER_M = 0.40
BATCH_OUTPUT_COST_PER_M = 2.00

# Slash commands to skip (mirrors extraction-hook.py)
COMMAND_MARKERS = [
    "/remember", "/recall", "/capture", "/craft", "/focus",
    "/done", "/standup", "/recap", "/track", "/weekly-review",
    "/retro", "/sync-board", "/process-email",
    "End-of-Session Reflection",
]

# Categories and prompt (shared with extraction-hook.py)
CATEGORIES_REFERENCE = """
## Categories

### Research Methodology (permanent)
- `methodology` — Analytical approach decisions, why this method over alternatives
- `ethics` — IRB, consent, data handling, anonymisation decisions
- `provenance` — Data origin, transformations, processing chain
- `hypothesis` — Research questions, testable predictions
- `limitation` — Known constraints, scope boundaries, what won't work
- `openness` — FAIR compliance, open science, licensing, reproducibility decisions
- `source_insight` — Key learnings from scholarly sources (include zotero_key if mentioned)

### LLM Interaction Research (permanent)
- `error_mode` — Cases where Claude made mistakes, misunderstood, or needed correction
- `surprise` — Unexpected insights, abductive reasoning, emergent understanding
- `self_reflection` — Claude reflecting on its own reasoning or limitations
- `prompt_effectiveness` — Observations about which prompts worked well or poorly

### Project / Architecture
- `decision` — Explicit choices with rationale (permanent)
- `architecture` — System design, structure decisions (permanent)
- `pattern` — Recurring approaches, conventions (decays after 180 days)
- `gotcha` — Pitfalls, edge cases, things that broke (decays after 180 days)

### GTD / Personal Assistant
- `commitment` — Promises made, deadlines agreed (decays 30 days after deadline)
- `waiting_for` — Blocked on others, follow-up needed (decays after 14 days)
- `contact` — People info, preferences, communication style (permanent)

### Transient
- `progress` — Status updates, milestones (decays after 30 days)
- `context` — Background information, requirements (decays after 30 days)

### System Adaptation
- `system_evolution` — Changes made to the productivity system and why (permanent)
- `system_friction` — Points where the system creates friction or gets bypassed (60 days)
- `system_success` — Moments where the system clearly helped (90 days)
"""

EXTRACTION_PROMPT = """Analyse this conversation and extract memories worth preserving \
for future sessions.

Today's date is {today}. The conversation took place around {session_date}. \
Use {year} as the year for interpreting relative dates in the conversation.

{categories}

## Output Format

Return a JSON array. Each object must have:
- `category`: One of the categories above
- `content`: The memory (1-3 sentences, specific and self-contained)
- `confidence`: "high", "medium", or "low"
- `research_tags`: Array of relevant tags (lowercase-hyphenated)
- `summary`: One-sentence summary (max 150 characters) for quick scanning
- `source_context`: Brief note on conversation context (optional)

## Extraction Guidelines

- Extract genuinely important information for future sessions
- Each memory should be understandable without conversation context
- For decisions: include the rationale, not just the choice
- For error_mode: describe what went wrong AND the correction
- Skip routine exchanges, greetings, acknowledgements
- Prefer fewer high-quality memories over many low-quality ones
- Typical extraction: 2-8 memories per conversation chunk

<conversation>
{conversation}
</conversation>

Return ONLY a valid JSON array. No other text, no markdown fences."""


VALID_CATEGORIES = {
    "methodology", "ethics", "provenance", "hypothesis", "limitation",
    "openness", "source_insight", "error_mode", "surprise",
    "self_reflection", "prompt_effectiveness", "decision", "architecture",
    "pattern", "gotcha", "commitment", "waiting_for", "contact",
    "progress", "context", "system_evolution", "system_friction",
    "system_success", "slip", "completion", "blocker_real", "blocker_excuse",
}


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
    log = logging.getLogger("reprocess-sessions")
    log.setLevel(logging.INFO)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(ch)

    return log


# ============================================================================
# Session Discovery
# ============================================================================


def load_session_memory_counts() -> dict[str, int]:
    """Count extraction-sourced memories per session ID."""
    counts: dict[str, int] = defaultdict(int)
    with open(MEMORIES_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                m = json.loads(line)
                sid = m.get("session_id", "")
                if sid and m.get("source") == "extraction":
                    counts[sid] += 1
            except json.JSONDecodeError:
                continue
    return dict(counts)


def find_sessions_needing_reprocessing(
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    """Find archived sessions that have zero extracted memories."""
    mem_counts = load_session_memory_counts()
    sessions = []

    for meta_path in sorted(ARCHIVE_ROOT.rglob("session.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        sid = meta.get("session", {}).get("id", "")
        if not sid:
            continue

        if mem_counts.get(sid, 0) > 0:
            continue  # Already has memories

        gz_path = meta_path.parent / "session.jsonl.gz"
        if not gz_path.exists():
            continue

        sessions.append({
            "session_id": sid,
            "archive_dir": str(meta_path.parent),
            "gz_path": str(gz_path),
            "project": meta.get("project", {}).get("name", "unknown"),
            "started_at": meta.get("session", {}).get("started_at", ""),
            "turns": meta.get("statistics", {}).get("turns", 0),
            "duration_minutes": meta.get("statistics", {}).get("duration_minutes", 0),
        })

    logger.info("Found %d sessions needing reprocessing", len(sessions))
    return sessions


# ============================================================================
# Transcript Processing
# ============================================================================


def parse_archived_transcript(gz_path: Path) -> list[dict[str, str]]:
    """
    Decompress and parse an archived session transcript.

    Returns list of {role, content} dicts, with slash commands filtered
    and messages truncated (mirrors extraction-hook.py logic).
    """
    messages: list[dict[str, str]] = []
    skip_next_assistant = False

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        with gzip.open(gz_path, "rb") as gz:
            while True:
                chunk = gz.read(8192)
                if not chunk:
                    break
                tmp.write(chunk)

    try:
        with open(tmp_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = entry.get("message", {})
                role = msg.get("role", entry.get("type", ""))
                content = msg.get("content", "")

                # Handle structured content blocks
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "thinking":
                                thinking = block.get("thinking", "")
                                if thinking:
                                    text_parts.append(
                                        f"[THINKING]: {thinking[:MAX_THINKING_CHARS]}"
                                    )
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = " ".join(text_parts)

                if not content or not content.strip():
                    continue

                # Skip slash command exchanges
                if role in ("user", "human"):
                    if any(marker in content for marker in COMMAND_MARKERS):
                        skip_next_assistant = True
                        continue
                    else:
                        skip_next_assistant = False
                elif role == "assistant" and skip_next_assistant:
                    skip_next_assistant = False
                    continue

                if role in ("user", "human"):
                    messages.append({
                        "role": "user",
                        "content": content[:MAX_MESSAGE_CHARS],
                    })
                elif role == "assistant":
                    messages.append({
                        "role": "assistant",
                        "content": content[:MAX_MESSAGE_CHARS],
                    })
    finally:
        tmp_path.unlink()

    return messages


def chunk_messages(
    messages: list[dict[str, str]],
) -> list[str]:
    """
    Split messages into conversation chunks of MAX_EXCHANGES exchanges.

    Each chunk is a formatted string ready for the extraction prompt.
    """
    # Pair user + assistant messages into exchanges
    exchanges: list[tuple[str, str]] = []
    i = 0
    while i < len(messages):
        if messages[i]["role"] == "user":
            user_msg = messages[i]["content"]
            asst_msg = ""
            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                asst_msg = messages[i + 1]["content"]
                i += 2
            else:
                i += 1
            exchanges.append((user_msg, asst_msg))
        else:
            i += 1  # Skip unpaired assistant messages

    # Window into chunks
    chunks = []
    for start in range(0, len(exchanges), MAX_EXCHANGES):
        window = exchanges[start:start + MAX_EXCHANGES]
        lines = []
        for user_msg, asst_msg in window:
            lines.append(f"[USER]: {user_msg}")
            if asst_msg:
                lines.append(f"[ASSISTANT]: {asst_msg}")
        chunk_text = "\n\n".join(lines)
        if len(chunk_text) >= MIN_CONTENT_LENGTH:
            chunks.append(chunk_text)

    return chunks


# ============================================================================
# Tag Normalisation (mirrors extraction-hook.py)
# ============================================================================


def normalise_tag(tag: str) -> str:
    """Normalise a single tag to lowercase-hyphenated form."""
    tag = tag.lower().strip()
    tag = tag.replace("_", "-").replace(" ", "-")
    tag = re.sub(r"[^a-z0-9\-]", "", tag)
    tag = re.sub(r"-+", "-", tag).strip("-")
    return tag


def normalise_tags(tags: list) -> list[str]:
    """Normalise and deduplicate a list of tags."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if isinstance(tag, str):
            normed = normalise_tag(tag)
            if normed and normed not in seen:
                seen.add(normed)
                result.append(normed)
    return result


def update_vocabulary(new_tags: list[str]) -> None:
    """Append novel tags to the vocabulary file."""
    existing: set[str] = set()
    if TAG_VOCAB_FILE.exists():
        existing = set(TAG_VOCAB_FILE.read_text().splitlines())
    novel = [t for t in new_tags if t and t not in existing]
    if novel:
        with open(TAG_VOCAB_FILE, "a") as f:
            for tag in sorted(set(novel)):
                f.write(tag + "\n")


def load_seed_tags(n: int = 30) -> list[str]:
    """Load seed tags from vocabulary for prompt context."""
    if not TAG_VOCAB_FILE.exists():
        return []
    tags = TAG_VOCAB_FILE.read_text().splitlines()
    # Return a diverse sample — first N alphabetically
    return sorted(set(t.strip() for t in tags if t.strip()))[:n]


# ============================================================================
# Memory Formatting (mirrors extraction-hook.py)
# ============================================================================


def format_memories(
    extracted: list[dict],
    session_id: str,
    project: str,
    session_date: str,
    custom_id: str = "",
) -> list[dict]:
    """Format extracted memories with metadata, normalised tags, and IDs.

    ``custom_id`` is the per-chunk batch request id and must be included in
    the id hash so memories from different chunks of the same session get
    distinct ids. Without it, memory ``i=0`` from chunk 0 collides with
    memory ``i=0`` from chunk 1 and so on (see the 2026-04-14 dedup —
    851 records were re-id'd to recover from this bug).
    """
    # Use the session date for created_at (not now), so memories are
    # temporally associated with when they actually happened
    if session_date:
        timestamp = session_date
        date_prefix = session_date[:10]
    else:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        date_prefix = now.strftime("%Y-%m-%d")

    memories = []
    all_tags: list[str] = []

    for i, mem in enumerate(extracted):
        if not mem.get("content"):
            continue

        category = mem.get("category", "context")
        if category not in VALID_CATEGORIES:
            category = "context"

        # Unique ID — include custom_id (batch request id) to prevent
        # chunk-level collisions within the same session.
        id_source = f"{session_id}-reprocess-{custom_id}-{i}"
        mem_id = hashlib.sha256(id_source.encode()).hexdigest()[:12]

        raw_tags = mem.get("research_tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        normalised = normalise_tags(raw_tags)
        all_tags.extend(normalised)

        confidence = mem.get("confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        record = {
            "id": f"{date_prefix}-{mem_id}",
            "session_id": session_id,
            "project": project,
            "source": "reprocessing",
            "category": category,
            "content": mem["content"],
            "confidence": confidence,
            "research_tags": normalised,
            "source_context": mem.get("source_context", ""),
            "created_at": timestamp,
        }

        if mem.get("summary"):
            record["summary"] = mem["summary"]
        if mem.get("zotero_key"):
            record["zotero_key"] = mem["zotero_key"]
        if mem.get("deadline_at"):
            record["deadline_at"] = mem["deadline_at"]

        memories.append(record)

    if all_tags:
        update_vocabulary(all_tags)

    return memories


# ============================================================================
# Commands
# ============================================================================


def cmd_discover(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Discover sessions needing reprocessing and estimate cost."""
    sessions = find_sessions_needing_reprocessing(logger)

    # Process each to count chunks
    total_chunks = 0
    total_tokens_est = 0
    by_project: dict[str, int] = defaultdict(int)

    for sess in sessions:
        messages = parse_archived_transcript(Path(sess["gz_path"]))
        chunks = chunk_messages(messages)
        total_chunks += len(chunks)
        for chunk in chunks:
            total_tokens_est += len(chunk) // 4
        by_project[sess["project"]] += len(chunks)

    # Cost estimate
    # Add prompt overhead (~3K tokens per request for categories + instructions)
    prompt_overhead = 3000 * total_chunks
    total_input_tokens = total_tokens_est + prompt_overhead
    est_output_tokens = total_chunks * 1000  # ~1K output per chunk
    input_cost = total_input_tokens / 1_000_000 * BATCH_INPUT_COST_PER_M
    output_cost = est_output_tokens / 1_000_000 * BATCH_OUTPUT_COST_PER_M
    total_cost = input_cost + output_cost

    print(f"\n{'=' * 60}")
    print("SESSION REPROCESSING — DISCOVERY")
    print(f"{'=' * 60}")
    print(f"Sessions to reprocess: {len(sessions)}")
    print(f"Total chunks:          {total_chunks}")
    print(f"Est. input tokens:     {total_input_tokens:,}")
    print(f"Est. output tokens:    {est_output_tokens:,}")
    print(f"Est. cost (Haiku Batch): ${total_cost:.2f}")
    print()

    print(f"{'Project':<30} {'Sessions':>8} {'Chunks':>8}")
    print("-" * 50)
    for proj, chunks in sorted(by_project.items(), key=lambda x: -x[1]):
        sess_count = sum(1 for s in sessions if s["project"] == proj)
        print(f"{proj:<30} {sess_count:>8} {chunks:>8}")


def cmd_submit(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Build and submit batch extraction requests."""
    load_env()

    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed")
        sys.exit(1)

    sessions = find_sessions_needing_reprocessing(logger)
    if args.limit and args.limit > 0:
        sessions = sessions[:args.limit]

    if not sessions:
        logger.info("No sessions to reprocess")
        return

    # Build batch requests
    requests = []
    # Map custom_id → (session_id, project, session_date, chunk_index)
    request_map: dict[str, dict[str, Any]] = {}
    seed_tags = ", ".join(load_seed_tags(30))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year = datetime.now(timezone.utc).strftime("%Y")

    for sess in sessions:
        messages = parse_archived_transcript(Path(sess["gz_path"]))
        chunks = chunk_messages(messages)

        if not chunks:
            logger.info(
                "Skipping %s (no extractable content)", sess["session_id"][:8]
            )
            continue

        session_date = sess.get("started_at", "")[:10] or today
        session_year = session_date[:4] if session_date else year

        for chunk_idx, chunk_text in enumerate(chunks):
            prompt = EXTRACTION_PROMPT.format(
                today=today,
                session_date=session_date,
                year=session_year,
                categories=CATEGORIES_REFERENCE,
                conversation=chunk_text,
            )

            custom_id = f"reprocess-{sess['session_id'][:8]}-c{chunk_idx}"

            requests.append({
                "custom_id": custom_id,
                "params": {
                    "model": HAIKU_MODEL,
                    "max_tokens": MAX_TOKENS_OUTPUT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            })

            request_map[custom_id] = {
                "session_id": sess["session_id"],
                "project": sess["project"],
                "started_at": sess.get("started_at", ""),
                "chunk_index": chunk_idx,
            }

    if not requests:
        logger.info("No extractable content found")
        return

    # Cost estimate
    total_chars = sum(
        len(r["params"]["messages"][0]["content"]) for r in requests
    )
    est_input_tokens = total_chars // 4
    est_output_tokens = len(requests) * 1000
    input_cost = est_input_tokens / 1_000_000 * BATCH_INPUT_COST_PER_M
    output_cost = est_output_tokens / 1_000_000 * BATCH_OUTPUT_COST_PER_M
    total_cost = input_cost + output_cost

    # --- API cost gate ---
    print(f"\n{'=' * 60}")
    print("API COST GATE — Session Reprocessing")
    print(f"{'=' * 60}")
    print(f"Model:       {HAIKU_MODEL}")
    print(f"Mode:        Anthropic Batch API (50% discount)")
    print(f"Sessions:    {len(sessions)}")
    print(f"Requests:    {len(requests)} (chunks)")
    print(f"Est. cost:   ${total_cost:.2f}")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\n[DRY RUN] Would submit the above. Exiting.")
        return

    response = input("\nSubmit batch? [y/N] ").strip().lower()
    if response != "y":
        logger.info("Cancelled by user")
        return

    # Submit
    client = anthropic.Anthropic()
    batch_job = client.messages.batches.create(requests=requests)

    # Save state
    state = {
        "batch_id": batch_job.id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "n_requests": len(requests),
        "n_sessions": len(sessions),
        "request_map": request_map,
    }
    BATCH_STATE_FILE.write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )

    logger.info(
        "Batch submitted: %s | %d requests (%d sessions) | Status: %s",
        batch_job.id, len(requests), len(sessions),
        batch_job.processing_status,
    )
    print(f"\nBatch ID: {batch_job.id}")
    print(f"State: {BATCH_STATE_FILE}")
    print(f"\nNext: venv/bin/python3 scripts/reprocess-sessions.py status {batch_job.id}")


def cmd_status(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Check batch processing status."""
    load_env()
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed")
        sys.exit(1)

    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(args.batch_id)
    print(f"Batch:      {args.batch_id}")
    print(f"Status:     {batch.processing_status}")
    print(f"Succeeded:  {batch.request_counts.succeeded}")
    print(f"Errored:    {batch.request_counts.errored}")
    print(f"Processing: {batch.request_counts.processing}")

    if batch.processing_status == "ended":
        print(
            f"\nReady to apply: venv/bin/python3 scripts/reprocess-sessions.py "
            f"apply {args.batch_id}"
        )


def cmd_apply(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Retrieve batch results and append memories to JSONL."""
    load_env()
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed")
        sys.exit(1)

    if not BATCH_STATE_FILE.exists():
        logger.error("No batch state file: %s", BATCH_STATE_FILE)
        sys.exit(1)

    # Guard against racing with extraction-hook appends or scheduled
    # sync. This path appends to memories.jsonl and modifies
    # tag-vocabulary.txt — bulk-rewrite class.
    ensure_safe_to_rewrite(
        reason=f"reprocess-sessions apply (batch={args.batch_id})"
    )
    atexit.register(release_lock)
    logger.info(
        "TIP: commit the result with the trailer so M3 shrink-check "
        "recognises it as intentional (only if net-negative deltas):\n"
        "    cd data && git commit -m 'reprocess: apply batch %s' -m 'Rewrite-Class: bulk'",
        args.batch_id,
    )

    state = json.loads(BATCH_STATE_FILE.read_text(encoding="utf-8"))
    request_map = state.get("request_map", {})

    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(args.batch_id)

    if batch.processing_status != "ended":
        logger.info(
            "Batch not yet complete (status: %s, processing: %d)",
            batch.processing_status, batch.request_counts.processing,
        )
        return

    # Process results
    total_memories = 0
    total_failed = 0
    all_memories: list[dict] = []

    for result in client.messages.batches.results(args.batch_id):
        custom_id = result.custom_id
        meta = request_map.get(custom_id)

        if not meta:
            logger.warning("Unknown custom_id: %s", custom_id)
            total_failed += 1
            continue

        if result.result.type != "succeeded":
            logger.warning("Request %s failed: %s", custom_id, result.result.type)
            total_failed += 1
            continue

        # Parse response
        try:
            response_text = result.result.message.content[0].text.strip()

            # Strip markdown code fences
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                if lines[-1].startswith("```"):
                    response_text = "\n".join(lines[1:-1])
                else:
                    response_text = "\n".join(lines[1:])

            extracted = json.loads(response_text)
            if not isinstance(extracted, list):
                logger.warning("Non-array response for %s", custom_id)
                total_failed += 1
                continue

            valid = [m for m in extracted if isinstance(m, dict)]
        except (json.JSONDecodeError, IndexError, AttributeError) as exc:
            logger.warning("Parse failed for %s: %s", custom_id, exc)
            total_failed += 1
            continue

        # Format memories
        memories = format_memories(
            valid,
            session_id=meta["session_id"],
            project=meta["project"],
            session_date=meta.get("started_at", ""),
            custom_id=custom_id,
        )

        all_memories.extend(memories)
        total_memories += len(memories)

    # Append all memories at once
    if all_memories:
        MEMORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORIES_FILE, "a", encoding="utf-8") as f:
            for mem in all_memories:
                f.write(json.dumps(mem) + "\n")

    logger.info(
        "Reprocessing complete: %d memories from %d requests (%d failed)",
        total_memories, state["n_requests"], total_failed,
    )

    if total_memories > 0:
        # Category breakdown
        cats: dict[str, int] = defaultdict(int)
        for m in all_memories:
            cats[m.get("category", "?")] += 1
        print("\nCategory breakdown:")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"  {cat:<25} {count:>4}")

        print(f"\nNext: venv/bin/python3 scripts/sync-to-postgres.py")


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(
        description="Reprocess archived sessions for memory extraction",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    subparsers.add_parser("discover", help="Find sessions needing reprocessing")

    p_submit = subparsers.add_parser("submit", help="Submit batch extraction")
    p_submit.add_argument("--limit", type=int, default=0)
    p_submit.add_argument("--dry-run", action="store_true")

    p_status = subparsers.add_parser("status", help="Check batch status")
    p_status.add_argument("batch_id", type=str)

    p_apply = subparsers.add_parser("apply", help="Apply batch results")
    p_apply.add_argument("batch_id", type=str)

    args = parser.parse_args()
    logger = setup_logging()

    if args.mode == "discover":
        cmd_discover(args, logger)
    elif args.mode == "submit":
        cmd_submit(args, logger)
    elif args.mode == "status":
        cmd_status(args, logger)
    elif args.mode == "apply":
        cmd_apply(args, logger)


if __name__ == "__main__":
    main()
