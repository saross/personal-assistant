#!/usr/bin/env python3
"""
Bake-off runner: side-by-side quality comparison of Anthropic Claude Haiku 4.5
(Batch API) vs Google Gemini 3.5 Flash (Flex tier) for auto-generating
session metadata in Shawn Ross's personal-assistant system.

Originally landed for the 2026-05-18 Haiku-vs-Gemini-3-Flash-Preview
bake-off; updated 2026-05-23 to default to Gemini 3.5 Flash (the
current production extractor per the 2026-05-22 toolkit migration).

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
import hashlib
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
GEMINI_MODEL = "gemini-3.6-flash"
LUNA_MODEL = "gpt-5.6-luna"
MAX_OUTPUT_TOKENS = 1024  # JSON object — well under any provider ceiling.

# Anthropic Haiku 4.5 list price (USD per million tokens). Batch is -50%.
HAIKU_INPUT_PRICE_PER_MTOK = 1.00
HAIKU_OUTPUT_PRICE_PER_MTOK = 5.00
HAIKU_BATCH_DISCOUNT = 0.50

# Gemini 3.6 Flash, Flex tier (USD per million tokens).
# **Re-verified 2026-07-28** against https://ai.google.dev/gemini-api/docs/pricing
# — Flex and Batch are priced identically for this model (both 50% off the
# standard $1.50 / $7.50), so Flex buys the batch discount at real-time latency.
#
# NOTE — these constants were previously 0.25 / 1.50, the Gemini 3 Flash
# *Preview* rate. The prior comment already recorded that the real rate was
# ~3× that and the code was never updated to match, so every cost estimate this
# file produced before today under-counted by roughly 3×. Corrected here.
GEMINI_FLEX_INPUT_PRICE_PER_MTOK = 0.75
GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK = 3.75

# OpenAI GPT-5.6 Luna list price (USD per million tokens), verified 2026-07-28
# against https://developers.openai.com/api/docs/pricing. Batch is -50%; this
# arm runs real-time, so the standard rate applies and the comparison against
# Gemini Flex is deliberately conservative *against* Luna.
LUNA_INPUT_PRICE_PER_MTOK = 1.00
LUNA_OUTPUT_PRICE_PER_MTOK = 6.00
LUNA_BATCH_DISCOUNT = 0.50

# OpenAI GPT-5.6 Terra, verified 2026-07-28 (same source as Luna). 2.5x Luna
# on both input and output — the mid-tier of the 5.6 family.
TERRA_MODEL = "gpt-5.6-terra"
TERRA_INPUT_PRICE_PER_MTOK = 2.50
TERRA_OUTPUT_PRICE_PER_MTOK = 15.00

# Anthropic Claude Sonnet 5, verified 2026-07-28 against the Anthropic model
# reference. List price is 3.00/15.00, but INTRODUCTORY pricing of 2.00/10.00
# runs through 2026-08-31 -- the rates below are the intro rates, so they go
# STALE on 1 Sep 2026 and must be raised to 3.00/15.00 then. Batch is -50%;
# this arm runs real-time like the Haiku arm, so the standard rate applies.
SONNET_MODEL = "claude-sonnet-5"
SONNET_INPUT_PRICE_PER_MTOK = 2.00
SONNET_OUTPUT_PRICE_PER_MTOK = 10.00

# Provider -> (model id, input $/MTok, output $/MTok) at the discounted tier
# each provider can actually reach for this workload. Haiku is listed at its
# STANDARD rate because the 2026-07-28 four-arm run used the real-time
# Messages API, not Batch: a 24-hour Batch SLA would have made the Haiku arm
# non-comparable with three same-day real-time arms, and at this volume the
# 50% discount is worth well under a dollar. Haiku's Batch rate (0.50/2.50)
# remains available for production backfills.
PROVIDER_SPECS: dict[str, tuple[str, float, float]] = {
    "luna": (LUNA_MODEL, LUNA_INPUT_PRICE_PER_MTOK * LUNA_BATCH_DISCOUNT,
             LUNA_OUTPUT_PRICE_PER_MTOK * LUNA_BATCH_DISCOUNT),
    "terra": (TERRA_MODEL, TERRA_INPUT_PRICE_PER_MTOK * LUNA_BATCH_DISCOUNT,
              TERRA_OUTPUT_PRICE_PER_MTOK * LUNA_BATCH_DISCOUNT),
    "gemini": (GEMINI_MODEL, GEMINI_FLEX_INPUT_PRICE_PER_MTOK,
               GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK),
    "haiku-rt": (HAIKU_MODEL, HAIKU_INPUT_PRICE_PER_MTOK,
                 HAIKU_OUTPUT_PRICE_PER_MTOK),
    "sonnet-5": (SONNET_MODEL, SONNET_INPUT_PRICE_PER_MTOK,
                 SONNET_OUTPUT_PRICE_PER_MTOK),
}

# Wait pattern for Flex preemption (HTTP 503) retries.
FLEX_RETRY_WAITS_SECONDS = (30, 60, 120)

# Approximate token cost of the bake-off system prompt
# (``data/experiments/bake-off-metadata-2026-05-18/prompt.md``). Measured
# at ~1,500 tokens on 2026-05-20 via the chars/4 heuristic against the
# committed prompt text. Used in ``estimate_cost_usd`` so the per-call
# input figure includes the system layer (Anthropic and Gemini both bill
# system tokens at the input rate); without it the dry-run estimate
# under-counted by ``SYSTEM_PROMPT_TOKENS_APPROX * n_requests`` tokens.
SYSTEM_PROMPT_TOKENS_APPROX = 1500

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
    # Per-request input tokens = user_message tokens + system prompt tokens.
    # The system prompt is sent on every call (no caching across requests),
    # so the aggregate input cost must include ``n_requests`` copies of it.
    total_input = sum(
        max(1, len(r.user_message) // 4) + SYSTEM_PROMPT_TOKENS_APPROX
        for r in requests
    )
    total_output = output_tokens_per_call * len(requests)

    if provider == "haiku":
        # Batch API discount applies to both input and output.
        in_rate = HAIKU_INPUT_PRICE_PER_MTOK * HAIKU_BATCH_DISCOUNT
        out_rate = HAIKU_OUTPUT_PRICE_PER_MTOK * HAIKU_BATCH_DISCOUNT
    elif provider == "gemini":
        in_rate = GEMINI_FLEX_INPUT_PRICE_PER_MTOK
        out_rate = GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK
    elif provider in PROVIDER_SPECS:
        # Flex tier is priced identically to Batch on OpenAI (0.5x standard),
        # so the OpenAI arms get the batch discount at real-time latency —
        # the same bargain the Gemini arm takes via Google's Flex tier.
        _, in_rate, out_rate = PROVIDER_SPECS[provider]
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
                # Per-session input tokens include the system prompt
                # (sent on every call) — matches the aggregate.
                "input_tokens": (
                    max(1, len(r.user_message) // 4)
                    + SYSTEM_PROMPT_TOKENS_APPROX
                ),
                "cost_usd": round(
                    (
                        (
                            max(1, len(r.user_message) // 4)
                            + SYSTEM_PROMPT_TOKENS_APPROX
                        )
                        / 1_000_000
                    )
                    * in_rate
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
    # ``out_dir`` here is the provider subdir (e.g. ``<root>/haiku``);
    # apply expects the user to pass the *root* ``--out-dir`` and
    # navigates into the provider subdir itself. Print the parent so
    # the hint copy-pastes cleanly.
    print(
        f"[haiku] retrieve with: "
        f"scripts/bake-off-metadata.py --provider haiku "
        f"--haiku-apply {batch_job.id} --out-dir {out_dir.parent}"
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
        # An empty ``content`` list (rare but possible if the model
        # returns a successful result with no text blocks) would raise
        # IndexError below. Persist a structured failure record and
        # continue rather than crashing the whole retrieval loop.
        if not result.result.message.content:
            (out_dir / f"{session_id}.json").write_text(
                json.dumps(
                    {"error": "succeeded result had empty content list"},
                    indent=2,
                )
                + "\n"
            )
            print(
                f"[haiku] succeeded result for {session_id} carried no "
                "content blocks — recording empty-content error"
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
            # Gemini 3.6 Flash is a reasoning model — without this, thinking
            # tokens consume the output budget before any visible JSON is
            # emitted (observed directly: max_output_tokens=64 with default
            # thinking returns empty text).
            #
            # **API CHANGE, found 2026-07-28.** The previous
            # ``{"thinking_budget": 0}`` is REJECTED by gemini-3.6-flash with
            # 400 INVALID_ARGUMENT — thinking can no longer be switched off
            # outright. Probed the alternatives on the live API:
            #   thinking_level=minimal  -> no thinking tokens reported
            #   thinking_level=low      -> ~80 thinking tokens
            #   thinking_budget=128     -> ~59 thinking tokens
            #   default (unset)         -> ~82 thinking tokens
            # ``minimal`` is therefore the closest available equivalent to the
            # old budget=0 and is what keeps this arm comparable with the Luna
            # arm (reasoning.effort="none"). It also matters for cost: Gemini
            # bills thinking at the OUTPUT rate, so an unset thinking config
            # silently inflates the bill.
            "thinking_config": {"thinking_level": "minimal"},
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
# OpenAI GPT-5.6 Luna adapter (Responses API, Flex tier)
# ---------------------------------------------------------------------------


def luna_call_once(
    user_message: str, system_prompt: str, *, service_tier: str = "flex",
    model: str = LUNA_MODEL,
) -> tuple[str, dict[str, Any]]:
    """Single Responses-API call. Returns ``(text, usage)``.

    Uses the **Responses API** (``POST /v1/responses``) rather than Chat
    Completions: OpenAI's guidance is that "Responses is recommended for all
    new projects", and reasoning models behave better on it. Verified
    2026-07-28 against developers.openai.com/api/docs/guides/migrate-to-responses.

    Deliberate parameter choices, each with a reason:

    - ``store=False`` — every call is independent; nothing is retained
      server-side. Keeps the arm stateless and avoids leaving transcript
      content in OpenAI's storage.
    - ``reasoning.effort="none"`` — **symmetry with the Gemini arm**, which
      sets ``thinking_budget=0``. Reasoning tokens bill at the *output* rate,
      so leaving the default ``medium`` would both inflate cost and give Luna
      a capability the Gemini arm was denied. Fair comparison requires both
      reasoning modes off.
    - ``text.verbosity="low"`` — fewer output tokens for schema-shaped output.
    - **No ``text.format`` JSON schema.** OpenAI can *guarantee* schema-valid
      JSON via structured outputs, but the Gemini and Haiku arms parse
      free-form JSON out of prose. Handing Luna a hard guarantee the others
      lack would measure the feature, not the model. Production should switch
      the winner to ``text.format`` — it eliminates parse failures outright.
    - ``service_tier="flex"`` — priced identically to Batch (0.5x standard)
      but synchronous, matching the Gemini Flex arm. Flex is in beta and may
      return 429; the caller falls back to the default tier.

    No SDK dependency: the toolkit deliberately avoids extra packages, so this
    speaks HTTP directly like the rest of the file's minimal-dependency style.
    """
    import urllib.error
    import urllib.request

    api_key = os.environ.get("OPENAI_API_KEY_PA_AMDT")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY_PA_AMDT not set (expected in personal-assistant/.env)"
        )
    body = {
        "model": model,
        "store": False,
        "service_tier": service_tier,
        "reasoning": {"effort": "none"},
        "instructions": system_prompt,
        "input": user_message,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "text": {"verbosity": "low"},
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
    with urllib.request.urlopen(req, timeout=900) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    # Responses returns a typed output array; prefer the convenience field.
    text = payload.get("output_text")
    if not text:
        chunks: list[str] = []
        for item in payload.get("output", []):
            for part in item.get("content", []) or []:
                if part.get("type") in ("output_text", "text") and part.get("text"):
                    chunks.append(part["text"])
        text = "".join(chunks)
    return text, payload.get("usage", {})


def luna_call_with_retry(
    user_message: str, system_prompt: str, *, model: str = LUNA_MODEL
) -> tuple[str, dict[str, Any]]:
    """Flex call with backoff on 429, falling back to the default tier.

    OpenAI documents Flex as returning ``429 Resource Unavailable`` under
    contention, explicitly *without* charging for the failed call. We retry on
    the same waits the Gemini arm uses, then degrade to the default tier so a
    busy Flex pool cannot stall the bake-off. The tier actually used is
    reported so the cost estimate can be corrected afterwards.
    """
    import urllib.error

    last_exc: Exception | None = None
    for attempt, wait_seconds in enumerate((0,) + FLEX_RETRY_WAITS_SECONDS):
        if wait_seconds:
            print(
                f"[openai] flex unavailable; waiting {wait_seconds}s before retry "
                f"(attempt {attempt + 1}/{len(FLEX_RETRY_WAITS_SECONDS) + 1})"
            )
            time.sleep(wait_seconds)
        try:
            return luna_call_once(user_message, system_prompt, service_tier="flex", model=model)
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            last_exc = exc
            if exc.code != 429:
                detail = exc.read().decode("utf-8", "replace")[:400]
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    print("[openai] flex exhausted; falling back to default service tier")
    return luna_call_once(user_message, system_prompt, service_tier="default", model=model)


def luna_run(
    requests: list[SessionRequest],
    out_dir: Path,
    system_prompt: str,
    *,
    model: str = LUNA_MODEL,
    tag: str = "luna",
) -> None:
    """Run all requests sequentially against Luna; persist responses + usage.

    Sequential by design, matching the Gemini arm: at ten requests the
    wall-clock saving from concurrency is irrelevant, and sequential execution
    keeps the two arms' timing comparable. For the production backfill this
    should become the Batch API (same 50% discount, 24h window) — see the
    plan doc; Tier-1 batch queue limits are 5M tokens, so a large run needs
    splitting into waves.
    """
    n_ok = 0
    n_fail = 0
    usage_log: list[dict[str, Any]] = []
    for i, r in enumerate(requests, 1):
        print(
            f"[{tag}] {i}/{len(requests)}  {r.session_id[:8]}  "
            f"({r.bin}, {r.content_tokens:,} tokens) …"
        )
        try:
            raw_text, usage = luna_call_with_retry(
                r.user_message, system_prompt, model=model
            )
        except Exception as exc:  # noqa: BLE001 — graceful per-session degrade
            (out_dir / f"{r.session_id}.json").write_text(
                json.dumps({"error": str(exc)}, indent=2) + "\n"
            )
            n_fail += 1
            print(f"[{tag}]   failed: {exc}")
            continue
        (out_dir / f"{r.session_id}.raw.txt").write_text(raw_text)
        usage_log.append({"session_id": r.session_id, **usage})
        try:
            parsed = parse_response_json(raw_text)
            n_ok += 1
        except ValueError as exc:
            parsed = {"error": str(exc), "raw": raw_text[:500]}
            n_fail += 1
        (out_dir / f"{r.session_id}.json").write_text(
            json.dumps(parsed, indent=2) + "\n"
        )
    # Real billed usage beats any estimate — record it for the cost comparison.
    (out_dir / "_usage.json").write_text(json.dumps(usage_log, indent=2) + "\n")
    print(f"[{tag}] wrote {n_ok} successes and {n_fail} failures to {out_dir}")
    billed_in = sum(u.get("input_tokens", 0) for u in usage_log)
    billed_out = sum(u.get("output_tokens", 0) for u in usage_log)
    reasoning = sum(
        (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
        for u in usage_log
    )
    print(
        f"[{tag}] billed: {billed_in:,} input, {billed_out:,} output "
        f"({reasoning:,} of which reasoning)"
    )


# ---------------------------------------------------------------------------
# Anthropic Haiku adapter — REAL-TIME (Messages API)
# ---------------------------------------------------------------------------


def haiku_rt_run(
    requests: list[SessionRequest],
    out_dir: Path,
    system_prompt: str,
    *,
    model: str = HAIKU_MODEL,
    tag: str = "haiku-rt",
    disable_thinking: bool = False,
) -> None:
    """Run all requests sequentially against Haiku 4.5 via the Messages API.

    **Why real-time rather than the existing Batch adapter.** ``haiku_submit``
    uses the Message Batches API for its 50% discount, but that carries a 24h
    SLA. In a same-day four-arm comparison that would leave one arm's results
    arriving a day after the other three, confounding "which model is better"
    with "which model answered today". At this volume the discount is worth
    well under a dollar, so latency parity is the better trade. The Batch
    adapter remains the right choice for production backfills.

    Haiku has no thinking mode, so no reasoning-suppression parameter is
    needed — it is natively in the same configuration the other three arms
    were forced into.
    """
    from anthropic import Anthropic  # type: ignore[import-not-found]

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    n_ok = n_fail = 0
    usage_log: list[dict[str, Any]] = []
    for i, r in enumerate(requests, 1):
        print(
            f"[{tag}] {i}/{len(requests)}  {r.session_id[:8]}  "
            f"({r.bin}, {r.content_tokens:,} tokens) …"
        )
        try:
            # Claude Sonnet 5 runs ADAPTIVE THINKING BY DEFAULT (a change from
            # Sonnet 4.6, where omitting the field meant no thinking), and
            # max_tokens caps thinking + visible output *together*. At
            # MAX_OUTPUT_TOKENS=1024 the thinking consumed the whole budget on
            # the two longest sessions and the arm returned EMPTY text -- no
            # error, just nothing to parse. Disabling thinking both fixes that
            # and matches the other arms, which all run reasoning off.
            # Haiku 4.5 has no thinking mode, so the flag stays off for it.
            extra = {"thinking": {"type": "disabled"}} if disable_thinking else {}
            resp = client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": r.user_message}],
                **extra,
            )
            raw_text = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            )
            usage_log.append({
                "session_id": r.session_id,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            })
        except Exception as exc:  # noqa: BLE001 — graceful per-session degrade
            (out_dir / f"{r.session_id}.json").write_text(
                json.dumps({"error": str(exc)}, indent=2) + "\n"
            )
            n_fail += 1
            print(f"[{tag}]   failed: {exc}")
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
    (out_dir / "_usage.json").write_text(json.dumps(usage_log, indent=2) + "\n")
    print(f"[{tag}] wrote {n_ok} successes and {n_fail} failures to {out_dir}")
    print(
        f"[{tag}] billed: {sum(u['input_tokens'] for u in usage_log):,} input, "
        f"{sum(u['output_tokens'] for u in usage_log):,} output"
    )


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
    blind_key: dict[str, dict[str, str]] = {}
    for i, entry in enumerate(manifest["sessions"], 1):
        sid = entry["session_id"]
        # Which providers actually have output for this run? Discovered from
        # the filesystem rather than hardcoded, so the rubric works for any
        # pair (haiku/gemini, luna/gemini, …) without further edits.
        available = sorted(
            d.name for d in out_dir.iterdir()
            if d.is_dir() and (d / f"{sid}.json").exists()
        )
        # BLINDING. Scoring is the whole point of the rubric, and a visible
        # provider label anchors the scorer before they have read a word of
        # output. Assign each provider a neutral letter, with the assignment
        # *flipped per session* so a scorer cannot learn "A is always the
        # OpenAI one" halfway through and back-fill their earlier scores.
        #
        # The flip is derived by hashing the session id against a fixed salt
        # rather than drawn at random: identical inputs regenerate an
        # identical rubric, so a re-run is comparable with the first. The key
        # is written to a sidecar file, NOT into the rubric.
        order = list(available)
        if int(
            hashlib.sha256(f"bakeoff-blind-2026-07-28:{sid}".encode()).hexdigest(), 16
        ) % 2:
            order.reverse()
        labelled = list(zip(("A", "B", "C", "D"), order))
        blind_key[sid] = {letter: prov for letter, prov in labelled}
        provider_blocks = []
        for letter, prov in labelled:
            text = (out_dir / prov / f"{sid}.json").read_text()
            # Sanitise failures. A raw provider error leaks the vendor — an
            # Anthropic context-limit message names "200000 maximum", which
            # identifies the arm instantly and unblinds every other session
            # for that model too. The *fact* of failure is legitimate signal
            # and is kept; the vendor-identifying detail is moved to the key.
            try:
                parsed_obj = json.loads(text)
            except ValueError:
                parsed_obj = None
            if isinstance(parsed_obj, dict) and "error" in parsed_obj:
                blind_key.setdefault("_redacted_errors", {}).setdefault(
                    prov, {}
                )[sid] = parsed_obj["error"]
                text = json.dumps(
                    {"error": "[redacted to preserve blinding — see key]"},
                    indent=2,
                )
            provider_blocks.append(
                f"#### Model {letter} output\n\n```json\n{text.rstrip()}\n```\n"
            )
        provider_section = "\n".join(provider_blocks)
        score_header = " / ".join(letter for letter, _ in labelled)

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

{provider_section}
#### Scores ({score_header} / T for tie)

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

    # The blinding key goes in a SIDECAR, never in the rubric — a scorer who
    # can see the mapping is not blind. Written next to the rubric so it is
    # trivially findable after scoring, and deliberately named so it is
    # obvious what not to open first.
    key_path = rubric_out.with_name(rubric_out.stem + ".blind-key.json")
    key_path.write_text(json.dumps({
        "note": (
            "Model-letter -> provider mapping for the blinded rubric. "
            "Assignment is flipped per session (sha256 of session id against "
            "a fixed salt), so it is deterministic and re-generable but not "
            "guessable from the rubric itself. DO NOT read before scoring."
        ),
        "salt": "bakeoff-blind-2026-07-28",
        "redacted_errors": blind_key.pop("_redacted_errors", {}),
        "mapping": blind_key,
    }, indent=1) + "\n")
    print(f"Wrote blinding key to {key_path} (do not open before scoring)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bake-off runner — Anthropic Haiku Batch vs Gemini Flash Flex "
            "for session metadata generation."
        )
    )
    parser.add_argument(
        "--provider",
        choices=("haiku", "haiku-rt", "sonnet-5", "gemini", "luna", "terra"),
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
        "--yes",
        action="store_true",
        help=(
            "Skip the interactive 'yes' confirmation before live API calls. "
            "Use only for non-interactive runs where the API Call Review Gate "
            "approval has already been recorded out-of-band."
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
        # submit persists batch-state.json under the provider subdir
        # (<out-dir>/haiku/), so apply must navigate to the same subdir.
        haiku_apply(args.haiku_apply, args.out_dir / "haiku")
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
    if args.yes:
        print(
            f"--yes flag set; proceeding with {args.provider} live calls "
            "without interactive prompt."
        )
    else:
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
    elif args.provider == "luna":
        luna_run(requests, provider_dir, system_prompt)
    elif args.provider == "terra":
        luna_run(
            requests, provider_dir, system_prompt,
            model=TERRA_MODEL, tag="terra",
        )
    elif args.provider == "haiku-rt":
        haiku_rt_run(requests, provider_dir, system_prompt)
    elif args.provider == "sonnet-5":
        haiku_rt_run(
            requests, provider_dir, system_prompt,
            model=SONNET_MODEL, tag="sonnet-5", disable_thinking=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
