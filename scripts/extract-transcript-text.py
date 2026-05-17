#!/usr/bin/env python3
"""
Distil a Claude Code session.jsonl(.gz) transcript into a single clean text
string suitable for sending to a Large Language Model (LLM) for whole-session
summarisation.

The current cc-session-toolkit archiver samples the first/last two user
messages and feeds Haiku only that slice (see
~/Code/cc-session-toolkit/src/cc_session_toolkit/archive.py:380-446). That
design loses the Process and Provenance evidence that lives in tool calls,
tool results, and the middle of long sessions. This extractor is the first
half of the redesign: produce a faithful, framing-free representation of the
whole transcript so downstream callers can ground all three Ps in the entire
session.

What is kept
------------
- User text (string content or ``text``-typed content blocks).
- Assistant text blocks (``type == "text"``).
- ``tool_use`` blocks — tool name plus a compact JSON serialisation of the
  inputs (truncated per block).
- ``tool_result`` text content — the actual results the assistant saw,
  truncated per block to bound runaway log/grep output.

What is stripped
----------------
- Framing scaffolds: ``<system-reminder>`` blocks, the
  ``# claudeMd`` / ``# userEmail`` / ``# currentDate`` injected context, and
  PreToolUse / PostToolUse / Stop hook output wrappers that appear in user
  turns.
- ``thinking`` content blocks (private reasoning — not sent to providers).
- Record types that are pure plumbing:
  ``file-history-snapshot``, ``queue-operation``, ``system``,
  ``custom-title``, ``agent-name``, ``last-prompt``.
- Empty / whitespace-only blocks.

Token counting
--------------
Uses the chars-divided-by-four heuristic. This is deliberately offline:
Anthropic's ``client.messages.count_tokens`` would make an API call, which is
forbidden in the bake-off prep stage. The heuristic is conservative-ish for
English prose and accurate enough for stratifying transcripts into bins.

Output
------
A single string. Turns are separated by a blank line and a distinctive
divider marker (``--- User ---``, ``--- Assistant ---``, ``--- Tool use
(Bash) ---``, ``--- Tool result ---``) so a reader (human or LLM) can
follow the conversation without needing the underlying JSON schema. The
divider style is deliberately distinct from ``[user]`` / ``[assistant]``
chat-turn brackets — when a downstream LLM is asked to *summarise* a
transcript, square-bracket role markers can trigger it to *continue* the
conversation as if it were the assistant, rather than extracting metadata
about it. The dividers do not.

Re-use
------
This module exposes ``extract_transcript_text(path) -> str`` and
``estimate_tokens(text) -> int`` for use by ``scripts/bake-off-metadata.py``
and the eventual production backfill.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Record-level types that carry no human-meaningful content.
SKIP_RECORD_TYPES = {
    "file-history-snapshot",
    "queue-operation",
    "system",
    "custom-title",
    "agent-name",
    "last-prompt",
}

# Per-block truncation. Tool results and tool-use inputs can blow up
# enormously (gigabyte log dumps, full file reads). We cap them so a single
# pathological block cannot dominate a session's token budget.
TOOL_RESULT_MAX_CHARS = 4000
TOOL_USE_INPUT_MAX_CHARS = 1500

# Patterns identifying framing material that should be stripped from any
# user-role text block before it is emitted.
SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>", re.DOTALL
)
# The injected context block at session start (claudeMd, userEmail,
# currentDate). It is fenced with a leading "# claudeMd" heading and ends
# before the next non-injected user content. We detect and remove the whole
# section conservatively: any contiguous block starting with "# claudeMd"
# and continuing through "# currentDate" plus the date line.
CLAUDE_MD_BLOCK_RE = re.compile(
    r"#\s*claudeMd\b.*?Today's date is \d{4}-\d{2}-\d{2}\.",
    re.DOTALL,
)
# PreToolUse / PostToolUse / Stop hook wrappers sometimes appear as
# ``<hook-output>`` or ``<tool-use-error>``-style XML in user turns.
HOOK_OUTPUT_RE = re.compile(
    r"<(?:hook-output|tool-use-error|local-command-stdout|"
    r"local-command-stderr|command-message|command-name|command-args)>"
    r".*?</(?:hook-output|tool-use-error|local-command-stdout|"
    r"local-command-stderr|command-message|command-name|command-args)>",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _open_transcript(path: Path):
    """Open a transcript regardless of whether it is gzip-compressed.

    Returns a text-mode file object. Caller is responsible for closing it.
    Some legacy archive entries have a ``.gz`` extension but contain
    plain-text JSONL (an early-archiver bug); we detect that by reading
    the gzip magic bytes and fall back to a plain text open if missing.
    """
    treat_as_gzip = (
        path.suffix == ".gz" or path.name.endswith(".jsonl.gz")
    )
    if treat_as_gzip:
        with open(path, "rb") as probe:
            magic = probe.read(2)
        if magic == b"\x1f\x8b":
            return gzip.open(path, "rt", encoding="utf-8")
        # Mis-labelled .gz that is actually plain text.
    return open(path, "rt", encoding="utf-8")


def _iter_records(path: Path) -> Iterable[dict]:
    """Yield parsed JSON records from a transcript, skipping malformed lines.

    Malformed lines are silently skipped — historical transcripts occasionally
    contain truncated tail records from interrupted writes. Logging is left
    to the caller if it matters.
    """
    with _open_transcript(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _strip_framing(text: str) -> str:
    """Remove framing wrappers (system-reminders, hook output, claudeMd).

    Operates only on user-role text. Assistant text and tool results are
    passed through untouched — the model produced them, so we keep them
    verbatim.
    """
    text = SYSTEM_REMINDER_RE.sub("", text)
    text = CLAUDE_MD_BLOCK_RE.sub("", text)
    text = HOOK_OUTPUT_RE.sub("", text)
    return text.strip()


def _truncate(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` characters with a trailing marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + f" …[truncated; total {len(text):,} chars]"


def _compact_json(value: Any, limit: int) -> str:
    """Serialise a tool-use input dict to compact JSON, truncated to limit."""
    try:
        s = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        s = repr(value)
    return _truncate(s, limit)


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


def _extract_content_blocks(
    blocks: list[dict], role: str
) -> list[str]:
    """Convert a list of content blocks into role-tagged text fragments.

    ``role`` is ``"user"`` or ``"assistant"``. For user-role text we strip
    framing; for assistant-role text we keep it as-is. Tool-use and
    tool-result blocks emit their own labelled fragments regardless of
    enclosing role.
    """
    out: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            raw = block.get("text", "") or ""
            if role == "user":
                raw = _strip_framing(raw)
            raw = raw.strip()
            if raw:
                out.append(f"--- {role.capitalize()} ---\n{raw}")

        elif btype == "tool_use":
            name = block.get("name", "unknown-tool")
            inputs = block.get("input", {}) or {}
            inputs_text = _compact_json(inputs, TOOL_USE_INPUT_MAX_CHARS)
            out.append(f"--- Tool use ({name}) ---\n{inputs_text}")

        elif btype == "tool_result":
            content = block.get("content")
            text = _stringify_tool_result(content)
            if text:
                out.append(f"--- Tool result ---\n{_truncate(text, TOOL_RESULT_MAX_CHARS)}")

        # ``thinking`` blocks and any other types are intentionally dropped.

    return out


def _stringify_tool_result(content: Any) -> str:
    """Flatten a tool_result ``content`` field to a single string.

    The field can be a string, a list of sub-blocks (each with ``type`` and
    ``text``), or occasionally other shapes; we normalise to a string and
    leave truncation to the caller.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for sub in content:
            if not isinstance(sub, dict):
                continue
            stype = sub.get("type")
            if stype == "text":
                t = (sub.get("text") or "").strip()
                if t:
                    parts.append(t)
            elif stype == "image":
                # Images are not useful for text summarisation; leave a marker.
                parts.append("[image elided]")
        return "\n".join(parts).strip()
    # Unknown shape — best-effort repr.
    return str(content).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_transcript_text(path: str | Path) -> str:
    """Return a single distilled-text representation of the transcript.

    See module docstring for the inclusion / exclusion contract.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    fragments: list[str] = []
    for rec in _iter_records(p):
        rtype = rec.get("type")
        if rtype in SKIP_RECORD_TYPES:
            continue
        if rtype not in ("user", "assistant"):
            # Unknown record type — skip rather than dump unknown structure.
            continue

        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or rtype
        content = msg.get("content")

        if isinstance(content, str):
            # Older / simpler turns: plain string user content.
            if role == "user":
                content = _strip_framing(content)
            content = content.strip()
            if content:
                fragments.append(f"--- {role.capitalize()} ---\n{content}")
            continue

        if isinstance(content, list):
            fragments.extend(_extract_content_blocks(content, role))
            continue

        # Anything else (None, dict, etc.) is dropped.

    return "\n\n".join(fragments).strip()


def estimate_tokens(text: str) -> int:
    """Estimate token count using the chars-divided-by-four heuristic.

    Offline by design (see module docstring). Returns an integer; callers
    should treat this as an order-of-magnitude figure, not a precise count.
    """
    return max(0, len(text) // 4)


# ---------------------------------------------------------------------------
# Command-line entry point
# ---------------------------------------------------------------------------


def _smoke_test(path: Path, preview_chars: int = 2000) -> None:
    """Run a sanity check on a single transcript and print a small report.

    Prints the input path, the distilled-text length in characters, the
    estimated token count, and the first ``preview_chars`` of the output so
    a human can eyeball the result.
    """
    text = extract_transcript_text(path)
    print(f"Input: {path}")
    print(f"Distilled chars: {len(text):,}")
    print(f"Estimated tokens: {estimate_tokens(text):,}")
    print("--- preview ---")
    print(text[:preview_chars])
    if len(text) > preview_chars:
        print(f"\n…[{len(text) - preview_chars:,} more chars elided]")


def main() -> int:
    """CLI: distil a transcript to text, or run a smoke test."""
    parser = argparse.ArgumentParser(
        description=(
            "Distil a Claude Code session.jsonl(.gz) transcript into "
            "clean text for LLM consumption."
        ),
    )
    parser.add_argument(
        "transcript",
        nargs="?",
        help="Path to session.jsonl or session.jsonl.gz",
    )
    parser.add_argument(
        "--smoke-test",
        metavar="PATH",
        help=(
            "Run a sanity check on PATH: print chars, estimated tokens, "
            "and a preview, without invoking any model."
        ),
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=2000,
        help="Characters to show in the smoke-test preview (default: 2000).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write distilled text to this file instead of stdout.",
    )
    args = parser.parse_args()

    if args.smoke_test:
        _smoke_test(Path(args.smoke_test), preview_chars=args.preview_chars)
        return 0

    if not args.transcript:
        parser.error("transcript path required (or use --smoke-test PATH)")

    text = extract_transcript_text(args.transcript)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
