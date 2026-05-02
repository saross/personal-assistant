#!/usr/bin/env python3
"""
Memory extraction hook for Claude Code.

Triggered by Stop, PreCompact, and SessionEnd hooks.
Extracts structured memories via Haiku, normalises tags,
and appends to canonical JSONL file.

Modifications from design review (cc-design-questions-response.md):
  - Error logging to logs/extraction.log (not just stderr)
  - Cursor only advances after successful append
  - Added 'source' field to distinguish extraction vs manual
  - Thinking block truncation increased to 1500 chars
  - Automatic singularisation skipped (handled in monthly /tags gardening)
"""

import fcntl
import hashlib
import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# Shared helpers live under ``scripts/`` — both hooks and CLI scripts
# import them by extending sys.path. Centralised so any drift across
# writers becomes a single-line edit (audit IC3, IC4, A-CF3).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _command_markers import COMMAND_MARKERS  # noqa: E402
from _timestamps import now_iso  # noqa: E402

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path.home() / "personal-assistant"
ENV_FILE = PA_DIR / ".env"
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
CURSOR_FILE = PA_DIR / "memories" / "extraction-cursor.json"
VOCABULARY_FILE = PA_DIR / "memories" / "tag-vocabulary.txt"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "extraction.log"

# Model for extraction — Haiku is cheap and fast
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Transcript parsing limits
MIN_CONTENT_LENGTH = 500   # Skip short conversations
MAX_EXCHANGES = 30         # Cap exchanges sent to Haiku
MAX_MESSAGE_CHARS = 3000   # Truncate individual messages
MAX_THINKING_CHARS = 1500  # Truncation for thinking blocks

# COMMAND_MARKERS is imported from scripts/_command_markers at the
# top of this module — see audit IC1 / A-Critical #3 fix.

# ============================================================================
# Environment Loading
# ============================================================================


def load_env() -> None:
    """
    Load environment variables from the project .env file.

    Uses os.environ.setdefault so externally-set variables take precedence.
    Handles comments and blank lines. No external dependencies.
    """
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


# ============================================================================
# Logging setup
# ============================================================================

if __name__ == "__main__" or "pytest" not in sys.modules:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("extraction-hook")

# ============================================================================
# Categories and Extraction Prompt
# ============================================================================

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
- `commitment` — Promises made, deadlines agreed (decays 30 days after deadline; include deadline if mentioned)
- `waiting_for` — Blocked on others, follow-up needed (decays after 14 days)
- `contact` — People info, preferences, communication style (permanent)

### Transient
- `progress` — Status updates, milestones (decays after 30 days)
- `context` — Background information, requirements (decays after 30 days)

### Retrospective (assigned during review, not extraction)
- `slip` — Commitments not met, patterns of avoidance (permanent)
- `completion` — Successfully finished items, what enabled success (90 days)
- `blocker_real` — Genuine blockers identified, not excuses (30 days)
- `blocker_excuse` — Stated blockers that turned out to be avoidance (permanent)

### System Adaptation
- `system_evolution` — Changes made to the productivity system and why (permanent)
- `system_friction` — Points where the system creates friction or gets bypassed (60 days)
- `system_success` — Moments where the system clearly helped (90 days)

Note: Retrospective categories (slip, completion, blocker_real, blocker_excuse)
are primarily assigned during weekly review, but may also be detected during
extraction when the evidence is clear. System adaptation categories are captured
whenever relevant.
"""

EXTRACTION_PROMPT = """Analyse this conversation and extract memories worth preserving \
for future sessions.

Today's date is {today}. Use the current year ({year}) when interpreting relative dates \
(e.g., "Friday 13 February" means {year}-02-13, not a previous year).

{categories}

## Output Format

Return a JSON array. Each object must have:
- `category`: One of the categories above
- `content`: The memory (1-3 sentences, specific and self-contained)
- `confidence`: "high", "medium", or "low"
- `research_tags`: Array of relevant tags (see guidelines below)
- `summary`: One-sentence summary (max 150 characters) for quick scanning at session start. \
Must be self-contained and capture the core insight or decision.
- `zotero_key`: If a Zotero item key was mentioned, include it (optional)
- `deadline_at`: For commitments, the deadline in ISO format (optional)
- `source_context`: Brief note on conversation context (optional)

## Tag Guidelines

- Use lowercase with hyphens: `gps-accuracy` not `GPS_Accuracy`
- Be specific: `gps-accuracy` not just `accuracy`
- Prefer existing tags when they fit: {seed_tags}
- Create new tags when needed (they'll be reviewed later)

## Extraction Guidelines

- Extract genuinely important information for future sessions
- Each memory should be understandable without conversation context
- For decisions: include the rationale, not just the choice
- For source_insight: capture what was learned, not bibliographic details
- For error_mode: describe what went wrong AND the correction
- Skip routine exchanges, greetings, acknowledgements
- Prefer fewer high-quality memories over many low-quality ones
- Typical extraction: 2-8 memories per session

<conversation>
{conversation}
</conversation>

Return ONLY a valid JSON array. No other text, no markdown fences."""

# ============================================================================
# Tag Normalisation
# ============================================================================


def normalise_tag(tag: str) -> str:
    """
    Normalise a tag according to folksonomy rules.

    Rules applied:
      1. Lowercase
      2. Replace underscores and spaces with hyphens
      3. Remove non-alphanumeric chars (except hyphens)
      4. Collapse multiple hyphens
      5. Strip leading/trailing hyphens

    Automatic singularisation is deliberately skipped — plurals are
    consolidated during monthly /tags gardening with human oversight.
    """
    # Lowercase and strip whitespace
    tag = tag.lower().strip()

    # Replace underscores and spaces with hyphens
    tag = re.sub(r"[_\s]+", "-", tag)

    # Remove non-alphanumeric except hyphens
    tag = re.sub(r"[^a-z0-9-]", "", tag)

    # Collapse multiple hyphens
    tag = re.sub(r"-+", "-", tag)

    # Strip leading/trailing hyphens
    tag = tag.strip("-")

    return tag


def normalise_tags(tags: list[str]) -> list[str]:
    """Normalise, filter empty results, and deduplicate a list of tags."""
    normalised = [normalise_tag(t) for t in tags if t]
    # Filter out tags that normalised to empty string (e.g., whitespace-only input)
    normalised = [t for t in normalised if t]
    # Deduplicate preserving order
    return list(dict.fromkeys(normalised))


def load_seed_tags() -> list[str]:
    """Load seed vocabulary for extraction prompt context."""
    if VOCABULARY_FILE.exists():
        lines = VOCABULARY_FILE.read_text().splitlines()
        return [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
    return [
        "field-method",
        "data-quality",
        "reproducibility",
        "fair-principle",
        "gps-accuracy",
        "interview",
        "survey",
        "ethics",
        "consent",
        "context-window",
        "prompt-engineering",
        "self-correction",
    ]


def update_vocabulary(new_tags: list[str]) -> None:
    """
    Add newly seen tags to the vocabulary file under a shared flock.

    The tag-vocabulary file is rewritten in place by
    ``scripts/tag-gardening.py merge``; the same shared/exclusive
    flock pattern used for ``memories.jsonl`` keeps this appender
    out of the rewriter's read-modify-rename window.
    """
    existing = set(load_seed_tags())
    novel = set(new_tags) - existing
    if not novel:
        return
    payload = "".join(f"{tag}\n" for tag in sorted(novel)).encode("utf-8")
    with _shared_locked_append_fd(VOCABULARY_FILE) as fd:
        os.write(fd, payload)
    logger.info("Added %d new tags to vocabulary: %s", len(novel), sorted(novel))


# ============================================================================
# Cursor Tracking
# ============================================================================


def load_cursor() -> dict:
    """Load cursor tracking last processed position per session."""
    if CURSOR_FILE.exists():
        try:
            return json.loads(CURSOR_FILE.read_text())
        except json.JSONDecodeError:
            logger.warning("Corrupt cursor file, starting fresh")
            return {}
    return {}


MAX_CURSOR_ENTRIES = 500


def save_cursor(cursor: dict) -> None:
    """Save cursor state atomically, pruning old entries if needed."""
    # Prune oldest entries if cursor has grown beyond limit.
    # Stale entries are harmless (trigger a full reparse of that session)
    # but keeping thousands of them wastes disk and memory.
    if len(cursor) > MAX_CURSOR_ENTRIES:
        # Keep the most recent entries — we can't sort by value (UUIDs aren't
        # ordered), so just keep an arbitrary subset. Old sessions that get
        # pruned will simply reparse on next encounter (idempotent).
        keys = list(cursor.keys())
        for key in keys[:len(keys) - MAX_CURSOR_ENTRIES]:
            del cursor[key]

    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Write to temp file then rename for atomicity
    tmp = CURSOR_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cursor, indent=2))
    tmp.rename(CURSOR_FILE)


# ============================================================================
# Transcript Parsing
# ============================================================================


def parse_transcript(
    transcript_path: str,
    last_uuid: Optional[str],
) -> tuple[list[dict], Optional[str]]:
    """
    Parse a Claude Code transcript JSONL file.

    Returns new messages since last_uuid, plus the UUID of the last
    entry seen (for cursor advancement).

    If last_uuid is set but not found in the transcript (stale cursor
    from a rotated/truncated file), falls back to processing the entire
    transcript to avoid permanently skipping all content.
    """
    messages = []
    last_seen_uuid = None
    found_cursor = last_uuid is None  # If no cursor, start from beginning
    skip_next_assistant = False  # Flag to skip assistant response to a command

    with open(transcript_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_uuid = entry.get("uuid")

            # Skip entries until we pass the cursor position
            if not found_cursor:
                if entry_uuid == last_uuid:
                    found_cursor = True
                continue

            if entry_uuid:
                last_seen_uuid = entry_uuid

            # Only process user and assistant messages
            if entry.get("type") not in ("user", "assistant"):
                continue

            msg = entry.get("message", {})
            content = msg.get("content", "")

            # Handle structured content blocks
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "thinking":
                            # Include thinking for LLM research value
                            thinking = block.get("thinking", "")
                            if MAX_THINKING_CHARS:
                                thinking = thinking[:MAX_THINKING_CHARS]
                            text_parts.append(f"[THINKING]: {thinking}")
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = " ".join(text_parts)

            # Skip slash command exchanges — these are handled by
            # the commands themselves (e.g., /remember writes to JSONL
            # directly, so extraction would produce duplicates)
            if entry.get("type") == "user":
                if any(marker in content for marker in COMMAND_MARKERS):
                    skip_next_assistant = True
                    continue
                else:
                    skip_next_assistant = False
            elif entry.get("type") == "assistant" and skip_next_assistant:
                skip_next_assistant = False
                continue

            if content and content.strip():
                messages.append(
                    {
                        "role": entry["type"],
                        "content": content[:MAX_MESSAGE_CHARS],
                        "uuid": entry_uuid,
                    }
                )

    # If cursor UUID was set but never found (stale/rotated transcript),
    # fall back to processing the entire file from the start
    if last_uuid is not None and not found_cursor:
        logger.warning(
            "Cursor UUID %s not found in transcript — stale cursor. "
            "Reprocessing entire file.",
            last_uuid,
        )
        return parse_transcript(transcript_path, None)

    return messages, last_seen_uuid


# ============================================================================
# Extraction via Haiku
# ============================================================================


def extract_memories(messages: list[dict], session_id: str) -> list[dict]:
    """Send conversation to Haiku for structured memory extraction."""
    try:
        from anthropic import Anthropic
    except ImportError:
        logger.error("anthropic package not installed — cannot extract")
        return []

    # Build conversation text from recent exchanges
    conversation_text = "\n\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in messages[-MAX_EXCHANGES:]
    )

    if len(conversation_text) < MIN_CONTENT_LENGTH:
        logger.info(
            "Conversation too short (%d chars), skipping extraction",
            len(conversation_text),
        )
        return []

    # Build the prompt with categories, seed tags, and current date
    seed_tags = ", ".join(load_seed_tags()[:30])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year = datetime.now(timezone.utc).strftime("%Y")
    prompt = EXTRACTION_PROMPT.format(
        categories=CATEGORIES_REFERENCE,
        seed_tags=seed_tags,
        conversation=conversation_text,
        today=today,
        year=year,
    )

    client = Anthropic()
    try:
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error("Haiku API call failed: %s", e)
        return []

    # Guard against empty or unexpected response structure
    if not response.content:
        logger.error("Haiku returned empty content array")
        return []
    first_block = response.content[0]
    if not hasattr(first_block, "text") or not first_block.text:
        logger.error("Haiku response block has no text: %s", type(first_block))
        return []
    response_text = first_block.text.strip()

    # Handle markdown code fences that Haiku sometimes wraps around JSON
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        if lines[-1].startswith("```"):
            response_text = "\n".join(lines[1:-1])
        else:
            response_text = "\n".join(lines[1:])

    try:
        extracted = json.loads(response_text)
        if not isinstance(extracted, list):
            logger.warning("Extraction returned non-array: %s", type(extracted))
            return []
        # Filter out non-dict elements (Haiku may return malformed items)
        valid = [m for m in extracted if isinstance(m, dict)]
        if len(valid) < len(extracted):
            logger.warning(
                "Filtered %d non-dict items from extraction response",
                len(extracted) - len(valid),
            )
        return valid
    except json.JSONDecodeError as e:
        logger.error("Failed to parse extraction JSON: %s", e)
        logger.debug("Raw response: %s", response_text[:500])
        return []


# ============================================================================
# Memory Formatting and Persistence
# ============================================================================

# Valid categories for validation
VALID_CATEGORIES = {
    # Research Methodology (permanent)
    "methodology",
    "ethics",
    "provenance",
    "hypothesis",
    "limitation",
    "openness",
    "source_insight",
    # LLM Interaction Research (permanent)
    "error_mode",
    "surprise",
    "self_reflection",
    "prompt_effectiveness",
    # Project / Architecture
    "decision",
    "architecture",
    "pattern",
    "gotcha",
    # GTD / Personal Assistant
    "commitment",
    "waiting_for",
    "contact",
    # Transient
    "progress",
    "context",
    # Retrospective
    "slip",
    "completion",
    "blocker_real",
    "blocker_excuse",
    # System Adaptation
    "system_evolution",
    "system_friction",
    "system_success",
}


def format_memories(
    extracted: list[dict],
    session_id: str,
    project: str = "",
) -> list[dict]:
    """
    Format extracted memories with metadata, normalised tags, and IDs.

    Each memory gets a unique ID, normalised tags, a 'source' field
    set to 'extraction' to distinguish from manual captures, and a
    'project' field identifying the working directory.
    """
    # Use shared helper (audit IC4) — guarantees the same ISO format
    # for all writers of memory ``created_at``.
    timestamp = now_iso()
    date_prefix = timestamp[:10]
    memories = []
    all_tags = []

    for i, mem in enumerate(extracted):
        if not mem.get("content"):
            continue

        # Validate category
        category = mem.get("category", "context")
        if category not in VALID_CATEGORIES:
            logger.warning("Unknown category '%s', defaulting to 'context'", category)
            category = "context"

        # Generate unique ID from session, timestamp, and index
        id_source = f"{session_id}-{timestamp}-{i}"
        mem_id = hashlib.sha256(id_source.encode()).hexdigest()[:12]

        # Normalise tags — handle string (Haiku sometimes returns a single string)
        raw_tags = mem.get("research_tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        normalised = normalise_tags(raw_tags)
        all_tags.extend(normalised)

        # Validate confidence
        confidence = mem.get("confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        record = {
            "id": f"{date_prefix}-{mem_id}",
            "session_id": session_id,
            "project": project,
            "source": "extraction",
            "category": category,
            "content": mem["content"],
            "confidence": confidence,
            "research_tags": normalised,
            "source_context": mem.get("source_context", ""),
            "created_at": timestamp,
        }

        # Optional fields — only include when present
        if mem.get("summary"):
            record["summary"] = mem["summary"]
        if mem.get("zotero_key"):
            record["zotero_key"] = mem["zotero_key"]
        if mem.get("deadline_at"):
            record["deadline_at"] = mem["deadline_at"]

        memories.append(record)

    # Update vocabulary with any new tags
    if all_tags:
        update_vocabulary(all_tags)

    return memories


@contextmanager
def _shared_locked_append_fd(target_path: Path) -> Iterator[int]:
    """
    Open ``target_path`` for appending and hold a shared (``LOCK_SH``)
    flock for the duration of the context.

    Multiple appenders may hold ``LOCK_SH`` concurrently — this is a
    fast path. A bulk rewriter holding ``LOCK_EX`` (via
    ``_bulk_rewrite_guard.lock_jsonl_for_rewrite``) will block until
    every appender releases ``LOCK_SH``, and any appender that
    arrives while ``LOCK_EX`` is held will wait until the rewrite
    completes.

    Rename-under-fd race: a rewriter atomically renames a temp file
    over ``target_path``. If the appender opened ``target_path``
    before the rename (acquiring an fd to the now-orphaned inode A)
    and only acquired ``LOCK_SH`` afterwards (on the orphan), its
    write would land on the orphan and be lost. To prevent this we
    open + lock + ``fstat``-vs-``stat`` and retry until the fd we
    hold is the same inode the path resolves to. ``LOCK_SH`` is
    fully serialised against the rewriter's ``LOCK_EX`` because the
    flock is on the open file description, not the path — but the
    inode-identity check is what guarantees the open file
    description is the post-rename inode.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        fd = os.open(
            str(target_path),
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o644,
        )
        fcntl.flock(fd, fcntl.LOCK_SH)
        try:
            fd_ino = os.fstat(fd).st_ino
            path_ino = os.stat(target_path).st_ino
        except FileNotFoundError:
            # Path vanished between open and stat — retry.
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
            continue
        if fd_ino != path_ino:
            # We hold a flock on an orphan inode (the rewriter
            # renamed under us). Drop and retry.
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
            continue
        break
    try:
        # O_APPEND already places writes at end of file at kernel
        # level; the lseek is belt-and-braces so a caller can still
        # see the offset for diagnostics.
        os.lseek(fd, 0, os.SEEK_END)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def append_memories(memories: list[dict]) -> None:
    """
    Append memories to the canonical JSONL file under a shared flock.

    Holding ``LOCK_SH`` lets multiple appenders proceed concurrently
    while blocking against bulk rewriters, which take ``LOCK_EX`` via
    :func:`_bulk_rewrite_guard.lock_jsonl_for_rewrite`. A rewrite
    in flight will pause this append until the rewrite completes.
    """
    if not memories:
        return
    payload = "".join(json.dumps(mem) + "\n" for mem in memories)
    encoded = payload.encode("utf-8")
    with _shared_locked_append_fd(MEMORIES_FILE) as fd:
        os.write(fd, encoded)


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    """
    Hook entry point.

    Reads hook input from stdin (JSON with transcript_path and session_id),
    parses new transcript content, extracts memories via Haiku, and appends
    to the canonical JSONL file.
    """
    # Load project-specific environment (ANTHROPIC_API_KEY etc.)
    load_env()

    # Parse hook input from stdin
    try:
        raw_input = sys.stdin.read()
        hook_input = json.loads(raw_input)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON input from hook: %s", e)
        sys.exit(1)

    transcript_path = hook_input.get("transcript_path")
    session_id = hook_input.get("session_id", "unknown")

    # Derive project identifier from the transcript path.
    # Transcripts live under ~/.claude/projects/<encoded-cwd>/<session>.jsonl
    # so the parent directory name is the encoded project path.
    project = ""
    if transcript_path:
        project = Path(transcript_path).parent.name

    if not transcript_path or not Path(transcript_path).exists():
        logger.debug("No transcript at %s, nothing to extract", transcript_path)
        sys.exit(0)

    # Load cursor to find where we left off in this session's transcript
    cursor = load_cursor()
    last_uuid = cursor.get(session_id)

    # Parse new content from transcript
    messages, new_last_uuid = parse_transcript(transcript_path, last_uuid)

    if not messages:
        logger.debug("No new messages in session %s", session_id)
        sys.exit(0)

    logger.info(
        "Processing %d new messages from session %s", len(messages), session_id
    )

    # Extract memories via Haiku
    extracted = extract_memories(messages, session_id)

    if extracted:
        try:
            memories = format_memories(extracted, session_id, project=project)
            append_memories(memories)

            # Only advance cursor AFTER successful append
            if new_last_uuid:
                cursor[session_id] = new_last_uuid
                save_cursor(cursor)

            logger.info(
                "Extracted %d memories from %d messages (session %s)",
                len(memories),
                len(messages),
                session_id,
            )
        except Exception as e:
            logger.error("Failed to save memories for session %s: %s", session_id, e)
            # Don't advance cursor — will retry next time
            sys.exit(1)
    else:
        # No memories extracted, but still advance cursor so we don't
        # reprocess the same content
        if new_last_uuid:
            cursor[session_id] = new_last_uuid
            save_cursor(cursor)
        logger.info(
            "No memories extracted from %d messages (session %s)",
            len(messages),
            session_id,
        )

    # Suppress hook output from appearing in the conversation
    print(json.dumps({"suppressOutput": True}))


if __name__ == "__main__":
    main()
