#!/usr/bin/env python3
"""
Distil a Claude Code session.jsonl(.gz) transcript into a single clean text
string suitable for sending to a Large Language Model (LLM) for whole-session
summarisation.

History
-------
This script was the original transcript distiller; the canonical module is
now ``cc_session_toolkit.transcript_text``. The script existed first and
the toolkit module was ported from it, after which the two slowly drifted:
the script kept per-block caps (4000 chars for ``tool_result``, 1500 chars
for ``tool_use_input``) and had no session-level cap, whereas the toolkit
module is uncapped at the block level and applies a session-level emergency
cap (``SESSION_TOKEN_BUDGET = 850_000`` tokens) with middle-truncation.

The drift was an active problem because two PA scripts —
``scripts/bake-off-metadata.py`` and ``scripts/resample-bake-off-manifest.py``
— ``importlib``-load this file at runtime, meaning the bake-off and
re-sampling pipelines exercised distillation logic that diverged from
production. This wrapper closes the gap: the public surface
(``extract_transcript_text``, ``estimate_tokens``, the
``TOOL_RESULT_MAX_CHARS`` / ``TOOL_USE_INPUT_MAX_CHARS`` sentinels,
the CLI) is preserved, but every callable now re-exports from the toolkit
module so the bake-off scripts share one distillation implementation with
the production archiver.

See ``cc_session_toolkit/transcript_text.py`` for the inclusion / exclusion
contract and the session-level emergency-cap policy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Re-export every public symbol the original script exposed so existing
# importers — ``bake-off-metadata.py`` and ``resample-bake-off-manifest.py``
# both load this file via ``importlib`` and access these names — keep
# working without any call-site changes.
from cc_session_toolkit.transcript_text import (  # noqa: F401
    CLAUDE_MD_BLOCK_RE,
    HOOK_OUTPUT_RE,
    SKIP_RECORD_TYPES,
    SYSTEM_REMINDER_RE,
    TOOL_RESULT_MAX_CHARS,
    TOOL_USE_INPUT_MAX_CHARS,
    estimate_tokens,
    extract_transcript_text,
)


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
