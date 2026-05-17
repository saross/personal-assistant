#!/usr/bin/env python3
"""
Bake-off runner: side-by-side quality comparison of Anthropic Claude Haiku 4.5
(Batch API) vs Google Gemini 3 Flash Preview (Flex tier) for auto-generating
session metadata in Shawn Ross's personal-assistant system.

The runner has two provider adapters that share an identical user prompt (the
contents of ``prompt.md``). The same N session transcripts are sent to each
provider; outputs are persisted side-by-side under ``--out-dir`` for human
review against ``review-rubric.md``.

Modes
-----
- ``--dry-run`` (the **only** mode exercised during the bake-off prep stage):
  load every transcript, build the request payloads, and print a one-line-per
  -request summary plus the first 300 characters of one example request body.
  No network calls.
- Live mode (run only after explicit Shawn approval): submit to the chosen
  provider and persist responses.

Provider adapters
-----------------
**Haiku (Anthropic Message Batches API)**: reuses the pattern in
``scripts/backfill-summaries.py``. Submits all N requests in a single batch,
persists the batch ID + custom_id → session_id index, and exits. A separate
``--haiku-apply`` invocation retrieves the completed batch and writes one
response file per session. 50% discount, ~24h SLA.

**Gemini (google-genai SDK, Flex tier)**: sequential ``generate_content``
calls with ``config={"service_tier": "flex"}``. On HTTP 503 (Flex
preemption), retries with exponential backoff (30 s, 60 s, 120 s, then
abort). Same price as Batch. Real-time.

Output layout
-------------
``<out-dir>/<provider>/<session_id>.json`` — the parsed JSON object returned
by the provider, or ``{"error": "..."}`` on failure.
``<out-dir>/<provider>/<session_id>.raw.txt`` — the raw text returned, for
debugging parse failures.
``<out-dir>/<provider>/batch-state.json`` (Haiku only) — batch ID and the
custom_id → session_id map.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HAIKU_MODEL = "claude-haiku-4-5-20251001"
GEMINI_MODEL = "gemini-3-flash-preview"
MAX_OUTPUT_TOKENS = 1024  # JSON object — well under any provider ceiling.

# Anthropic Haiku 4.5 list price (USD per million tokens). Batch is -50%.
HAIKU_INPUT_PRICE_PER_MTOK = 1.00
HAIKU_OUTPUT_PRICE_PER_MTOK = 5.00
HAIKU_BATCH_DISCOUNT = 0.50

# Gemini 3 Flash Preview Flex list price (USD per million tokens) as per
# https://ai.google.dev/gemini-api/docs/pricing#flex (verified 2026-05-17).
GEMINI_FLEX_INPUT_PRICE_PER_MTOK = 0.25
GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK = 1.50

# Wait pattern for Flex preemption (HTTP 503) retries.
FLEX_RETRY_WAITS_SECONDS = (30, 60, 120)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

PA_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PA_DIR / ".env"


def load_env() -> None:
    """Hydrate ``os.environ`` from the personal-assistant ``.env`` file.

    Reuses the same simple loader as ``scripts/backfill-summaries.py``; we
    deliberately avoid pulling in ``python-dotenv`` to keep dependencies
    minimal.
    """
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


# ---------------------------------------------------------------------------
# Extractor (import the sibling script as a module)
# ---------------------------------------------------------------------------


def _load_extractor():
    """Import ``scripts/extract-transcript-text.py`` as a module.

    The script name contains hyphens, so we cannot use a normal import.
    """
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
# Request assembly (shared)
# ---------------------------------------------------------------------------


@dataclass
class SessionRequest:
    """Pre-assembled payload for one transcript / one provider.

    ``custom_id`` is short and stable: providers' batch APIs require it to
    correlate responses back to inputs.
    """

    session_id: str
    project: str
    bin: str
    content_tokens: int
    transcript_text: str
    user_message: str
    custom_id: str


def _build_user_message(
    *,
    session_id: str,
    project: str,
    started_at: str,
    bin_label: str,
    content_tokens: int,
    transcript_text: str,
) -> str:
    """Build the user message: session header + delimited transcript + postamble.

    The system prompt (separately) carries the role + contracts + JSON
    output spec. The user message carries the *input* (header + transcript)
    plus a final reminder of the output contract after the closing
    transcript delimiter — leveraging recency rather than fighting it,
    since the transcript itself may be ~100K+ tokens long.
    """
    header = (
        f"## Session metadata header (not authoritative — transcript wins)\n"
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
        "not a participant. Do not continue the conversation.\n\n"
        "Begin output with ``{`` on the very next character. End with "
        "``}``. No markdown code fence. Nothing before, nothing after."
    )
    return (
        f"{header}\n"
        f"<transcript>\n"
        f"{transcript_text}\n"
        f"</transcript>\n\n"
        f"{postamble}"
    )


def assemble_requests(
    manifest_path: Path,
    prompt_path: Path,
) -> list[SessionRequest]:
    """Read the manifest, run the extractor on each transcript, build payloads.

    ``prompt_path`` is read for length-accounting and ad-hoc inspection,
    but the prompt itself is sent via the provider's ``system=`` /
    ``system_instruction=`` parameter — not concatenated into the user
    message. See ``_build_user_message`` and the per-provider adapters.
    """
    extractor = _load_extractor()
    manifest = json.loads(manifest_path.read_text())
    # prompt_text is loaded once and passed separately to the adapters.
    _ = prompt_path.read_text()

    requests: list[SessionRequest] = []
    for entry in manifest["sessions"]:
        transcript_text = extractor.extract_transcript_text(
            entry["transcript_path"]
        )
        user_msg = _build_user_message(
            session_id=entry["session_id"],
            project=entry["project"],
            started_at=entry.get("started_at", ""),
            bin_label=entry["bin"],
            content_tokens=entry["content_tokens"],
            transcript_text=transcript_text,
        )
        # custom_id must be <=64 chars for Anthropic Batch API; first 8 of
        # the session ID is unique enough across 10 sessions.
        custom_id = f"sess-{entry['session_id'][:8]}"
        requests.append(
            SessionRequest(
                session_id=entry["session_id"],
                project=entry["project"],
                bin=entry["bin"],
                content_tokens=entry["content_tokens"],
                transcript_text=transcript_text,
                user_message=user_msg,
                custom_id=custom_id,
            )
        )
    return requests


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def estimate_cost_usd(
    requests: list[SessionRequest],
    *,
    provider: str,
    output_tokens_per_call: int = 350,
) -> dict[str, Any]:
    """Compute a per-provider cost estimate from real input token counts.

    ``output_tokens_per_call`` is set to 350: empirically the target JSON
    object runs ~300 tokens; 350 is a safe estimate that still beats the
    1,024-token max we send.
    """
    total_input = sum(
        max(1, len(r.user_message) // 4) for r in requests
    )
    total_output = output_tokens_per_call * len(requests)

    if provider == "haiku":
        # Batch API discount applies to both input and output.
        in_rate = HAIKU_INPUT_PRICE_PER_MTOK * HAIKU_BATCH_DISCOUNT
        out_rate = HAIKU_OUTPUT_PRICE_PER_MTOK * HAIKU_BATCH_DISCOUNT
    elif provider == "gemini":
        in_rate = GEMINI_FLEX_INPUT_PRICE_PER_MTOK
        out_rate = GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK
    else:
        raise ValueError(f"unknown provider: {provider}")

    in_cost = (total_input / 1_000_000) * in_rate
    out_cost = (total_output / 1_000_000) * out_rate
    return {
        "provider": provider,
        "n_requests": len(requests),
        "input_tokens": total_input,
        "output_tokens_assumed": total_output,
        "input_rate_per_mtok": round(in_rate, 4),
        "output_rate_per_mtok": round(out_rate, 4),
        "input_cost_usd": round(in_cost, 4),
        "output_cost_usd": round(out_cost, 4),
        "total_cost_usd": round(in_cost + out_cost, 4),
        "per_session_cost_usd": [
            {
                "session_id": r.session_id,
                "bin": r.bin,
                "input_tokens": max(1, len(r.user_message) // 4),
                "cost_usd": round(
                    (max(1, len(r.user_message) // 4) / 1_000_000) * in_rate
                    + (output_tokens_per_call / 1_000_000) * out_rate,
                    4,
                ),
            }
            for r in requests
        ],
    }


# ---------------------------------------------------------------------------
# Response parsing (shared)
# ---------------------------------------------------------------------------


def parse_response_json(raw_text: str) -> dict[str, Any]:
    """Extract a JSON object from a model response.

    The prompt instructs the model to emit bare JSON (no fences), but
    real-world models intermittently wrap output in ```json blocks. This
    function strips any single leading/trailing fence and then tries
    ``json.loads``. On any failure, raises ``ValueError`` with the raw text
    so callers can persist diagnostics.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[-1].startswith("```"):
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Haiku adapter (Anthropic Message Batches API)
# ---------------------------------------------------------------------------


def haiku_build_batch_requests(
    requests: list[SessionRequest],
    system_prompt: str,
) -> list[dict[str, Any]]:
    """Convert ``SessionRequest`` objects into Anthropic batch entries.

    The prompt's role + contracts content is sent via Anthropic's
    ``system=`` parameter (a separate layer from the user message), so
    the model treats it as instruction context rather than as text to
    continue. The user message carries only the session header, the
    delimited transcript, and the post-transcript output reminder.
    """
    out: list[dict[str, Any]] = []
    for r in requests:
        out.append({
            "custom_id": r.custom_id,
            "params": {
                "model": HAIKU_MODEL,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": r.user_message},
                ],
            },
        })
    return out


def haiku_submit(
    requests: list[SessionRequest],
    out_dir: Path,
    system_prompt: str,
) -> str:
    """Submit a single Batch API job; persist state; return the batch ID.

    Mirrors ``scripts/backfill-summaries.py:run_batch_submit``.
    """
    from anthropic import Anthropic  # type: ignore[import-not-found]

    client = Anthropic()
    batch_requests = haiku_build_batch_requests(requests, system_prompt)
    batch_job = client.messages.batches.create(requests=batch_requests)

    state = {
        "batch_id": batch_job.id,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_requests": len(batch_requests),
        "custom_id_to_session": {
            r.custom_id: r.session_id for r in requests
        },
    }
    state_path = out_dir / "batch-state.json"
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    print(f"[haiku] submitted batch {batch_job.id}")
    print(f"[haiku] state persisted to {state_path}")
    print(
        f"[haiku] retrieve with: "
        f"scripts/bake-off-metadata.py --provider haiku "
        f"--haiku-apply {batch_job.id} --out-dir {out_dir}"
    )
    return batch_job.id


def haiku_apply(
    batch_id: str,
    out_dir: Path,
) -> None:
    """Retrieve a completed Haiku batch and write per-session response files."""
    from anthropic import Anthropic  # type: ignore[import-not-found]

    client = Anthropic()
    state_path = out_dir / "batch-state.json"
    state = json.loads(state_path.read_text())
    custom_to_session = state["custom_id_to_session"]

    batch_job = client.messages.batches.retrieve(batch_id)
    if batch_job.processing_status != "ended":
        print(
            f"[haiku] batch {batch_id} not ready "
            f"(status: {batch_job.processing_status}); try later"
        )
        return

    n_ok = 0
    n_fail = 0
    for result in client.messages.batches.results(batch_id):
        session_id = custom_to_session.get(result.custom_id)
        if not session_id:
            print(f"[haiku] unknown custom_id {result.custom_id} — skipping")
            continue
        if result.result.type != "succeeded":
            (out_dir / f"{session_id}.json").write_text(
                json.dumps({"error": result.result.type}, indent=2) + "\n"
            )
            n_fail += 1
            continue
        raw_text = result.result.message.content[0].text
        (out_dir / f"{session_id}.raw.txt").write_text(raw_text)
        try:
            parsed = parse_response_json(raw_text)
        except ValueError as exc:
            parsed = {"error": str(exc), "raw": raw_text[:500]}
            n_fail += 1
        else:
            n_ok += 1
        (out_dir / f"{session_id}.json").write_text(
            json.dumps(parsed, indent=2) + "\n"
        )
    print(f"[haiku] wrote {n_ok} successes and {n_fail} failures to {out_dir}")


# ---------------------------------------------------------------------------
# Gemini adapter (google-genai SDK, Flex tier)
# ---------------------------------------------------------------------------


def gemini_call_once(
    client: Any, user_message: str, system_prompt: str
) -> str:
    """Single Flex-tier call. Raises on non-503 errors; returns raw text.

    ``system_prompt`` is passed via ``config.system_instruction`` — the
    Gemini equivalent of Anthropic's ``system=`` parameter. Keeps the role
    + contracts separate from the user message (which carries the
    delimited transcript and the post-transcript output reminder).
    """
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_message,
        config={
            "service_tier": "flex",
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "system_instruction": system_prompt,
            # Gemini 3 Flash is a reasoning model — without this, thinking
            # tokens consume the output budget before any visible JSON is
            # emitted. ``thinking_budget=0`` disables thinking, giving us
            # straight JSON output and a closer apples-to-apples match with
            # Haiku 4.5 (which has no thinking mode).
            "thinking_config": {"thinking_budget": 0},
        },
    )
    return response.text


def gemini_call_with_retry(
    client: Any,
    user_message: str,
    system_prompt: str,
) -> str:
    """Call Gemini Flex with exponential-backoff retries on HTTP 503.

    Per Google's Flex documentation, preemption surfaces as HTTP 503
    "Service Unavailable" via ``google.genai.errors.ServerError`` (or a
    subclass). We retry on 503 specifically; other errors propagate.
    """
    last_exc: Exception | None = None
    for attempt, wait_seconds in enumerate((0,) + FLEX_RETRY_WAITS_SECONDS):
        if wait_seconds:
            print(
                f"[gemini] preempted; waiting {wait_seconds}s before retry "
                f"(attempt {attempt + 1}/{len(FLEX_RETRY_WAITS_SECONDS) + 1})"
            )
            time.sleep(wait_seconds)
        try:
            return gemini_call_once(client, user_message, system_prompt)
        except Exception as exc:  # noqa: BLE001 — broad catch then narrow
            last_exc = exc
            # Detect 503 specifically without importing the exception class
            # at module top (the SDK may not be installed at import time).
            text = str(exc).lower()
            is_503 = (
                "503" in text
                or "service unavailable" in text
                or "preempt" in text
            )
            if not is_503:
                raise
            # Else: retry on next loop iteration.
    raise RuntimeError(
        f"Gemini Flex preempted {len(FLEX_RETRY_WAITS_SECONDS) + 1} times; "
        f"last error: {last_exc}"
    )


def gemini_run(
    requests: list[SessionRequest],
    out_dir: Path,
    system_prompt: str,
) -> None:
    """Run all requests sequentially against Gemini Flex; persist responses."""
    from google import genai  # type: ignore[import-not-found]

    client = genai.Client()
    n_ok = 0
    n_fail = 0
    for i, r in enumerate(requests, 1):
        print(
            f"[gemini] {i}/{len(requests)}  {r.session_id[:8]}  "
            f"({r.bin}, {r.content_tokens:,} tokens) …"
        )
        try:
            raw_text = gemini_call_with_retry(
                client, r.user_message, system_prompt
            )
        except Exception as exc:  # noqa: BLE001 — graceful per-session degrade
            (out_dir / f"{r.session_id}.json").write_text(
                json.dumps({"error": str(exc)}, indent=2) + "\n"
            )
            n_fail += 1
            print(f"[gemini]   failed: {exc}")
            continue
        (out_dir / f"{r.session_id}.raw.txt").write_text(raw_text)
        try:
            parsed = parse_response_json(raw_text)
            n_ok += 1
        except ValueError as exc:
            parsed = {"error": str(exc), "raw": raw_text[:500]}
            n_fail += 1
        (out_dir / f"{r.session_id}.json").write_text(
            json.dumps(parsed, indent=2) + "\n"
        )
    print(f"[gemini] wrote {n_ok} successes and {n_fail} failures to {out_dir}")


# ---------------------------------------------------------------------------
# Dry-run reporting
# ---------------------------------------------------------------------------


def dry_run_report(
    requests: list[SessionRequest],
    provider: str,
    out_dir: Path,
) -> None:
    """Print a per-request summary and a cost estimate; do not call APIs."""
    print(f"\n=== DRY RUN — provider={provider} ===")
    print(f"out_dir: {out_dir}")
    print(f"requests: {len(requests)}")
    print()
    print(f"{'idx':>3}  {'session_id':<10}  {'bin':<7}  "
          f"{'tokens':>9}  {'project':<28}  custom_id")
    for i, r in enumerate(requests, 1):
        print(
            f"{i:>3}  {r.session_id[:8]:<10}  {r.bin:<7}  "
            f"{r.content_tokens:>9,}  {r.project[:28]:<28}  {r.custom_id}"
        )

    cost = estimate_cost_usd(requests, provider=provider)
    print()
    print(f"--- Cost estimate ({provider}) ---")
    print(
        f"input tokens (sum): {cost['input_tokens']:,}  @ "
        f"${cost['input_rate_per_mtok']}/Mtok  =  ${cost['input_cost_usd']}"
    )
    print(
        f"output tokens (assumed 350/call): {cost['output_tokens_assumed']:,}  "
        f"@ ${cost['output_rate_per_mtok']}/Mtok  =  ${cost['output_cost_usd']}"
    )
    print(f"total ({provider}): ${cost['total_cost_usd']}")

    print()
    print("--- Example request body (first 400 chars of request 1) ---")
    print(requests[0].user_message[:400])
    print("…")

    # Write a dry-run-cost.json so the launch plan can include the figure
    # without re-running.
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dry-run-cost.json").write_text(
        json.dumps(cost, indent=2) + "\n"
    )
    print(f"\nCost detail written to {out_dir / 'dry-run-cost.json'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_rubric(
    manifest_path: Path,
    prompt_path: Path,
    out_dir: Path,
    rubric_template: Path,
    rubric_out: Path,
) -> None:
    """Populate the review rubric with per-session blocks.

    Reads the providers' JSON responses from ``out_dir/{haiku,gemini}/`` and
    interleaves them, in manifest order, with a 500-token transcript preview
    and the bin / project header. Leaves the scoring grid empty for Shawn
    to fill.
    """
    extractor = _load_extractor()
    manifest = json.loads(manifest_path.read_text())
    template = rubric_template.read_text()

    # Patch the summary table cells with real metadata.
    for i, entry in enumerate(manifest["sessions"], 1):
        template = template.replace(
            f"<!--SESSION-ID-{i}-->", entry["session_id"][:8]
        )
        template = template.replace(
            f"<!--PROJECT-{i}-->", entry["project"]
        )
        template = template.replace(
            f"<!--BIN-{i}-->", entry["bin"]
        )
        template = template.replace(
            f"<!--TOKENS-{i}-->", f"{entry['content_tokens']:,}"
        )

    blocks: list[str] = []
    for i, entry in enumerate(manifest["sessions"], 1):
        sid = entry["session_id"]
        haiku_path = out_dir / "haiku" / f"{sid}.json"
        gemini_path = out_dir / "gemini" / f"{sid}.json"
        haiku_text = (
            haiku_path.read_text() if haiku_path.exists()
            else '{"error": "no response file — provider not yet run"}'
        )
        gemini_text = (
            gemini_path.read_text() if gemini_path.exists()
            else '{"error": "no response file — provider not yet run"}'
        )

        # Distil and preview the first ~500 tokens (~2,000 chars).
        try:
            transcript_text = extractor.extract_transcript_text(
                entry["transcript_path"]
            )
            preview = transcript_text[:2000]
            if len(transcript_text) > 2000:
                preview += (
                    f"\n…[{len(transcript_text) - 2000:,} more chars elided]"
                )
        except Exception as exc:  # noqa: BLE001
            preview = f"[extractor failed: {exc}]"

        block = f"""
### Session {i}: `{sid[:8]}` ({entry['project']}, {entry['bin']}, {entry['content_tokens']:,} tokens)

- Session ID: `{sid}`
- Started at: {entry.get('started_at', '?')}
- Current three_ps state: {entry['current_three_ps_state']}
- Transcript: `{entry['transcript_path']}`

#### Transcript preview (first 500 tokens)

```text
{preview}
```

#### Haiku output

```json
{haiku_text.rstrip()}
```

#### Gemini output

```json
{gemini_text.rstrip()}
```

#### Scores (H / G / T)

- title (pithy + accurate): [ ]
- purpose (captures "why" not just "what"): [ ]
- tags (relevance + granularity): [ ]
- prompt_summary (what was asked + why): [ ]
- process_summary (how the tool was used + why this approach): [ ]
- provenance_summary (where this fits in broader project): [ ]

#### Notes

<!-- optional free-text comments -->
"""
        blocks.append(block)

    sessions_block = "\n".join(blocks)
    populated = template.replace(
        "<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->",
        f"<!--BEGIN-SESSIONS-->\n{sessions_block}\n<!--END-SESSIONS-->",
    )
    rubric_out.write_text(populated)
    print(f"Wrote populated rubric to {rubric_out}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bake-off runner — Anthropic Haiku Batch vs Gemini Flash Flex "
            "for session metadata generation."
        )
    )
    parser.add_argument(
        "--provider",
        choices=("haiku", "gemini"),
        required=False,
        help="Which provider adapter to exercise (omit for --build-rubric).",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to the sample manifest JSON.",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        type=Path,
        help="Path to the prompt markdown file.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Directory to write responses (and batch state for Haiku).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build requests, print summary + cost estimate, do not call any "
            "API. This is the only mode exercised during prep."
        ),
    )
    parser.add_argument(
        "--haiku-apply",
        metavar="BATCH_ID",
        help=(
            "Haiku only: retrieve results from a completed batch and write "
            "per-session response files."
        ),
    )
    parser.add_argument(
        "--build-rubric",
        action="store_true",
        help=(
            "After both providers have run, populate review-rubric.md with "
            "transcript previews and provider outputs. Requires --rubric-in "
            "and --rubric-out."
        ),
    )
    parser.add_argument(
        "--rubric-in",
        type=Path,
        help="Template rubric markdown (input).",
    )
    parser.add_argument(
        "--rubric-out",
        type=Path,
        help="Populated rubric markdown (output).",
    )
    args = parser.parse_args()

    load_env()

    if args.build_rubric:
        if not (args.rubric_in and args.rubric_out):
            print("--build-rubric requires --rubric-in and --rubric-out")
            return 2
        build_rubric(
            args.manifest, args.prompt, args.out_dir,
            args.rubric_in, args.rubric_out,
        )
        return 0

    if not args.provider:
        print("--provider is required unless --build-rubric is set")
        return 2

    if args.haiku_apply:
        if args.provider != "haiku":
            print("--haiku-apply is only valid with --provider haiku")
            return 2
        haiku_apply(args.haiku_apply, args.out_dir)
        return 0

    requests = assemble_requests(args.manifest, args.prompt)
    system_prompt = args.prompt.read_text()
    provider_dir = args.out_dir / args.provider
    provider_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        dry_run_report(requests, args.provider, provider_dir)
        return 0

    # Live mode — guarded by the API Call Review Gate. We do not invoke
    # without an extra confirmation step; this branch exists for after
    # Shawn approves the launch plan.
    print(
        "Live mode requested. This will make billed API calls. "
        "Re-run with --dry-run first if you have not yet reviewed the cost."
    )
    answer = input(
        f"Type 'yes' to proceed with {args.provider} live calls: "
    )
    if answer.strip().lower() != "yes":
        print("Aborted.")
        return 0

    if args.provider == "haiku":
        haiku_submit(requests, provider_dir, system_prompt)
    elif args.provider == "gemini":
        gemini_run(requests, provider_dir, system_prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
