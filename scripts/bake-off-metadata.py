#!/usr/bin/env python3
"""
Bake-off runner: side-by-side quality comparison of several Large Language
Model (LLM) providers for auto-generating session metadata in Shawn Ross's
personal-assistant system.

``--provider`` offers six arms, in three families:

- ``haiku`` — Anthropic Claude Haiku 4.5 via the Message Batches API.
- ``haiku-rt`` / ``sonnet-5`` — the same Anthropic models in real time via
  the Messages API.
- ``gemini`` — Google Gemini 3.6 Flash on the Flex tier.
- ``luna`` / ``terra`` — OpenAI GPT-5.6 Luna and Terra via the Responses API.

Originally landed for the 2026-05-18 Haiku-versus-Gemini-3-Flash-Preview
bake-off; the Gemini arm moved to 3.5 Flash on 2026-05-23 and to 3.6 Flash
on 2026-07-28, when the two OpenAI arms and the real-time Anthropic arms
were added.

Every arm shares an identical user prompt (the contents of ``prompt.md``).
The same N session transcripts are sent to each provider; outputs are
persisted side-by-side under ``--out-dir`` for human review against
``review-rubric.md``.

Interpreter
-----------
Run this under the repository virtual environment
(``venv/bin/python3 scripts/bake-off-metadata.py …``). The system
``python3`` the shebang resolves to has neither ``cc_session_toolkit`` —
which the transcript extractor imports unconditionally — nor the provider
SDKs.

Modes
-----
- ``--dry-run`` (the **only** mode exercised during the bake-off prep stage):
  load every transcript, build the request payloads, and print a one-line-per
  -request summary plus the first 300 characters of one example request body.
  No network calls.
- Live mode (run only after explicit Shawn approval): submit to the chosen
  provider and persist responses. Guarded by the API Call Review Gate — the
  model id, batch versus real-time, the request count, and the estimated
  cost are printed before the confirmation, and ``--yes`` prints them too.
- ``--haiku-apply`` (retrieval): NOT gated, deliberately. Retrieving a
  finished batch costs nothing — the submission was the billed step — so it
  runs without a confirmation prompt. It does announce the batch id and the
  destination directory before fetching.

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
import random
import re
import shlex
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Per-machine OpenAI key resolution (2026-08-22): paid keys are issued per
# machine, so the variable name carries a host suffix.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _openai_key import resolve_openai_key  # noqa: E402

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

# Anthropic Claude Sonnet 5, list price, from the Anthropic model reference.
# The introductory 2.00/10.00 rate expired on 2026-08-31 exactly as the
# previous comment here predicted; these are the post-introductory LIST rates
# it instructed the next reader to install, applied 2026-09-08. Every
# estimate this file produced between 1 and 8 September under-counted the
# Sonnet arm by a third. Batch is -50%; this arm runs real-time like the
# Haiku arm, so the standard rate applies.
#
# NEXT REVIEW: on the next Anthropic pricing announcement, or by 2027-03-08 —
# whichever comes first. There is no further scheduled step, so a calendar
# date is the only tripwire left.
SONNET_MODEL = "claude-sonnet-5"
SONNET_INPUT_PRICE_PER_MTOK = 3.00
SONNET_OUTPUT_PRICE_PER_MTOK = 15.00

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

#: Exit code for a live run that was declined at the API Call Review Gate,
#: whether the operator typed something other than "yes" or no operator was
#: there at all (closed stdin). It is deliberately NOT 0: a cron or CI
#: wrapper that reads 0 as "the run happened" would record a refusal as a
#: completed bake-off. It is deliberately not 2 either, which this file uses
#: for a usage error the caller can fix by changing the command line.
EXIT_REFUSED_AT_GATE = 3

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

    The extractor re-exports ``cc_session_toolkit.transcript_text``, which is
    installed in the repository virtual environment and nowhere else, so an
    ImportError here almost always means the wrong interpreter. Say that,
    rather than surfacing a bare "No module named cc_session_toolkit".
    """
    path = Path(__file__).with_name("extract-transcript-text.py")
    spec = importlib.util.spec_from_file_location(
        "extract_transcript_text", str(path)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load extractor from {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        raise RuntimeError(
            f"Cannot load the transcript extractor ({exc}). Re-run under the "
            f"repository virtual environment: "
            f"venv/bin/python3 scripts/{Path(__file__).name} …"
        ) from exc
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


#: Anthropic's Message Batches API caps ``custom_id`` at 64 characters and
#: allows only ASCII letters, digits, underscores, and hyphens.
CUSTOM_ID_MAX_CHARS = 64
CUSTOM_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SessionIdError(ValueError):
    """A session id cannot be used to name a response or a batch entry."""


def validate_session_id(session_id: Any, *, where: str) -> str:
    """Return ``session_id`` unchanged, or explain why it cannot be used.

    One rule, checked at both entry points that commit to an id: the
    submission that pays for a batch, and the repair that rebuilds the map
    afterwards. They must agree, because the id has to round-trip
    byte-for-byte between them — ``build_custom_id`` hashes it and the
    response filename is built from it.

    Whitespace is REFUSED rather than stripped for that reason. Stripping
    here would make the repair reconstruct ``sess-abc`` for an id that was
    submitted as ``" abc "`` and stored under ``" abc .json"``, and the two
    would never meet again.

    Args:
        session_id: the value to check.
        where: what to name in the message (a manifest path, a position).

    Raises:
        SessionIdError: not a string, empty, blank, or carrying leading or
            trailing whitespace.
    """
    if not isinstance(session_id, str):
        raise SessionIdError(
            f"{where}: session_id is {type(session_id).__name__}, not a string"
        )
    if not session_id.strip():
        raise SessionIdError(
            f"{where}: session_id is empty or blank, so it names no session"
        )
    if session_id != session_id.strip():
        raise SessionIdError(
            f"{where}: session_id {session_id!r} has leading or trailing "
            "whitespace; it would not round-trip between the batch and the "
            "response filename"
        )
    return session_id


def build_custom_id(session_id: str) -> str:
    """Return a batch ``custom_id`` that maps one-to-one onto ``session_id``.

    The previous form was ``f"sess-{session_id[:8]}"``, justified as "unique
    enough across 10 sessions". It is not: the re-sampler sets
    ``session_id = path.stem`` for sub-agent transcripts, and those stems
    share long prefixes. ``haiku_submit`` then builds
    ``{custom_id: session_id}``, the second entry silently overwrites the
    first, and on retrieval one session's metadata is written to disk under
    the other session's name — with no error anywhere.

    A full id is used whenever it fits the API's 64-character, restricted
    alphabet; otherwise a SHA-256 digest of the id stands in, which is
    collision-free for any realistic corpus and still round-trips through
    the batch-state map.
    """
    candidate = f"sess-{session_id}"
    if (
        len(candidate) <= CUSTOM_ID_MAX_CHARS
        and CUSTOM_ID_SAFE_RE.match(candidate) is not None
    ):
        return candidate
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:40]
    return f"sess-{digest}"


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
    for position, entry in enumerate(manifest["sessions"], 1):
        # Validate BEFORE anything derives from the id: build_custom_id
        # would otherwise raise AttributeError on a list or a dict, several
        # frames from the manifest that caused it.
        validate_session_id(
            entry.get("session_id"),
            where=f"{manifest_path}: session {position}",
        )
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
        custom_id = build_custom_id(entry["session_id"])
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
# Response persistence (shared)
#
# Every response file used to be a bare ``write_text``. Three consequences,
# all observed in the shapes below: a crash part-way through left a truncated
# JSON file that ``--build-rubric`` would read as an answer; a re-run after a
# provider outage replaced a COMPLETE response with ``{"error": ...}``; and
# ``_usage.json`` was rewritten wholesale, so the billed totals from an
# earlier partial run were lost. Each response costs money to produce, so the
# default here is to keep what already exists.
# ---------------------------------------------------------------------------


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry so a rename survives a crash. Best effort.

    Without this the renamed name itself can be lost even though the file's
    contents reached the disk. Filesystems that refuse a directory fsync
    (some network mounts) are not an error: durability degrades to what the
    filesystem offers, and the write has already succeeded.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` beside ``path`` and ``os.replace`` it into position.

    On POSIX the rename is atomic, so a reader sees either the whole old file
    or the whole new one — never a half-written response.

    Raises:
        OSError: the directory could not be made, the temp file could not be
            created, or the write, flush, or rename failed. The exception
            keeps its original type and errno and gains the target path:
            this is called in a loop over a batch's responses, and an
            unadorned "No space left on device" leaves the operator without
            the one fact they need — which response is missing.
    """
    handle_fd: int | None = None
    tmp_name: str | None = None
    try:
        # Inside the try: mkdir and mkstemp are the likeliest places for a
        # full disk to bite, and they were the two lines whose failure said
        # nothing about which file was being written.
        path.parent.mkdir(parents=True, exist_ok=True)
        handle_fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            # Flush to the device before the rename. os.replace is atomic
            # with respect to readers, but on a crash the rename can reach
            # the disk before the contents do, leaving a file that is
            # present, named correctly, and empty.
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
        # Re-raise the SAME class with errno intact, rather than collapsing
        # every failure into a bare OSError: a caller distinguishing
        # FileNotFoundError from PermissionError, or reading errno, must
        # still be able to. The path goes into strerror, so the type and
        # the code survive and the message still names the file.
        raise type(exc)(
            exc.errno, f"{exc.strerror}: while writing {path}"
        ) from exc
    except BaseException:
        # Anything else (a KeyboardInterrupt, a caller's TypeError from
        # serialisation) is not a write failure: clean up the temp file and
        # let it through unchanged rather than relabelling it.
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
        raise
    # After the rename, not before: it is the directory entry that needs
    # flushing, and only once the entry exists.
    _fsync_directory(path.parent)


def write_json_atomic(path: Path, payload: Any) -> None:
    """Persist ``payload`` as indented JSON, atomically."""
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def response_is_complete(path: Path) -> bool:
    """True when ``path`` holds a parsed response object carrying no error."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and "error" not in payload


def record_failure(
    out_dir: Path, session_id: str, error: dict[str, Any], *, tag: str
) -> bool:
    """Persist an error record unless a complete response already exists.

    Deliberately unconditional, even under ``--force``: a re-run that fails
    must not destroy the answer an earlier run paid for. The refusal is
    printed, so a silently kept response cannot be mistaken for a fresh one.

    Returns:
        True when an error record was written, False when an existing
        complete response was kept instead. Callers count the True cases:
        the run summary reports files it actually created, and a kept
        response is not a failure this run produced.
    """
    path = out_dir / f"{session_id}.json"
    if response_is_complete(path):
        print(
            f"[{tag}]   a complete response for {session_id} is already on "
            "disk; keeping it rather than replacing it with this error"
        )
        return False
    write_json_atomic(path, error)
    return True


def report_kept(n_kept: int, *, tag: str) -> None:
    """Say how many earlier responses were kept in place of a failure.

    Without this line the summary would simply omit them, and a run whose
    calls all failed against an already-complete directory would report
    "0 successes and 0 failures" with no explanation.
    """
    if n_kept:
        print(
            f"[{tag}] kept {n_kept} earlier complete response(s) rather than "
            "recording a failure over them"
        )


def pending_requests(
    requests: list[SessionRequest], out_dir: Path, *, force: bool, tag: str
) -> list[SessionRequest]:
    """Drop requests whose complete response is already persisted.

    Args:
        requests: everything the manifest asked for.
        out_dir: the provider subdirectory holding ``<session_id>.json``.
        force: re-run even the sessions that already have a good response.
        tag: the log prefix for this arm.
    """
    if force:
        return list(requests)
    pending = [
        request
        for request in requests
        if not response_is_complete(out_dir / f"{request.session_id}.json")
    ]
    skipped = len(requests) - len(pending)
    if skipped:
        print(
            f"[{tag}] skipping {skipped} session(s) that already have a "
            "complete response (--force re-runs them)"
        )
    return pending


def merge_usage_log(
    out_dir: Path, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge usage rows into ``_usage.json``, keyed by session id.

    A resumed run only carries rows for the sessions it actually called, so
    replacing the file would discard the billed figures for everything the
    earlier run completed.
    """
    path = out_dir / "_usage.json"
    merged: dict[str, dict[str, Any]] = {}
    try:
        existing = json.loads(path.read_text())
    except (OSError, ValueError):
        existing = []
    if isinstance(existing, list):
        for row in existing:
            if isinstance(row, dict) and row.get("session_id"):
                merged[row["session_id"]] = row
    for row in entries:
        merged[row["session_id"]] = row
    ordered = [merged[session_id] for session_id in sorted(merged)]
    write_json_atomic(path, ordered)
    return ordered


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


class BatchStateExistsError(RuntimeError):
    """A batch has already been submitted into this output directory."""


class ManifestFormatError(RuntimeError):
    """A manifest could not be read, or is not shaped like a manifest."""


def file_sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_batch_state(out_dir: Path) -> dict[str, Any] | None:
    """Return the persisted batch state for ``out_dir``, or None if absent."""
    try:
        state = json.loads((out_dir / "batch-state.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or not state.get("batch_id"):
        return None
    return state


def haiku_retrieve_command(batch_id: str, out_dir: Path) -> str:
    """Return the exact command that retrieves ``batch_id`` from ``out_dir``.

    ``out_dir`` is the provider subdirectory; ``--haiku-apply`` takes the
    *root* output directory and navigates into it itself, so the printed
    command names the parent and copy-pastes as it stands.

    Every interpolated value goes through ``shlex.quote``. An output
    directory containing a space would otherwise split into separate
    arguments when the line is pasted back into a shell, and the operator
    would see "unrecognised arguments" at the one moment they are trying to
    collect a batch they have already paid for. Quoting a value that needs
    no quoting is a no-op, so the common case reads exactly as before.
    """
    return (
        "venv/bin/python3 scripts/bake-off-metadata.py --provider haiku "
        f"--haiku-apply {shlex.quote(batch_id)} "
        f"--out-dir {shlex.quote(str(out_dir.parent))}"
    )


#: A hashed custom_id is exactly the 40 hex characters build_custom_id
#: takes from the SHA-256 of the session id. Anything else after the prefix
#: is the session id itself, so it can be read straight back out.
_HASHED_CUSTOM_ID_RE = re.compile(r"^[0-9a-f]{40}$")


def state_manifest_path(
    state: dict[str, Any], *, report: bool = False
) -> str | None:
    """Return the manifest path a batch state records, if it is usable.

    One guard for every reader. The state is a JSON file an operator can
    edit, so ``manifest_path`` may be a number, a list, or absent; without
    this, ``rebuild_map_command`` interpolated whatever it found and raised
    TypeError at the END of a retrieval, after the responses were written.
    """
    path = state.get("manifest_path")
    if isinstance(path, str) and path:
        return path
    if path is not None and report:
        # Not silence: a state whose manifest_path is a number or a list
        # behaves exactly like one that records nothing, and the operator
        # would otherwise have no way to tell those apart.
        print(
            f"[haiku] the batch state records manifest_path as "
            f"{type(path).__name__} ({path!r}), which is not a usable path; "
            "treating it as unrecorded.",
            file=sys.stderr,
        )
    return None


def _read_manifest_session_ids(path: str) -> set[str] | None:
    """Return the session ids ``path`` lists, or None if it cannot be used.

    None and the empty set are deliberately different: a manifest that
    cannot be read must not look like one that lists nothing, because the
    caller falls back on the first and not on the second.
    """
    try:
        manifest = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        # Say so. Falling back in silence let the operator read "session id
        # not recoverable" and conclude the id was a digest, when in fact
        # the manifest that would have named it simply could not be read.
        print(
            f"[haiku] could not read the manifest at {path}: {exc}.",
            file=sys.stderr,
        )
        return None
    sessions = manifest.get("sessions") if isinstance(manifest, dict) else None
    if not isinstance(sessions, list):
        print(
            f"[haiku] {path} has no 'sessions' list, so it cannot name any "
            "session.",
            file=sys.stderr,
        )
        return None
    return {
        entry["session_id"]
        for entry in sessions
        if isinstance(entry, dict) and isinstance(entry.get("session_id"), str)
    }


def resolve_manifest(
    state: dict[str, Any], manifest_path: Path | None = None
) -> tuple[set[str], str | None]:
    """Return the session ids to recover with, and the manifest they came from.

    A manifest supplied on this invocation wins — a repair run must be able
    to see the file it was just handed, since the state's own record may be
    absent or stale. But winning is conditional on being READABLE: a typo'd
    ``--manifest`` used to defeat a perfectly good recorded one, so the run
    reported ids as unrecoverable that it could have named, and printed a
    remedy line repeating the typo. An unusable supplied path now falls
    back, and both paths are named.

    Returns:
        ``(session_ids, manifest_used)``. ``manifest_used`` is None when
        nothing readable was found, so a remedy line names the placeholder
        rather than a path already known to be broken.
    """
    recorded = state_manifest_path(state, report=True)
    supplied = str(manifest_path) if manifest_path is not None else None

    if supplied is not None:
        found = _read_manifest_session_ids(supplied)
        if found:
            return found, supplied
        # An empty result is as useless as an unreadable one, and used to
        # short-circuit here: a manifest that parsed but listed no session
        # defeated a perfectly good recorded one in silence, so every
        # stranded result "looked like a digest" and the remedy line named
        # the very file the rebuild path then refuses.
        if found is not None:
            print(
                f"[haiku] the supplied --manifest ({supplied}) lists no "
                "sessions, so it can name nothing.",
                file=sys.stderr,
            )
        if recorded is not None and recorded != supplied:
            print(
                f"[haiku] falling back to the manifest recorded in the batch "
                f"state ({recorded}) because the supplied --manifest "
                f"({supplied}) could not be used.",
                file=sys.stderr,
            )
            found = _read_manifest_session_ids(recorded)
            if found:
                return found, recorded
        return set(), None

    if recorded is None:
        return set(), None
    found = _read_manifest_session_ids(recorded)
    return (found, recorded) if found else (set(), None)


def custom_id_lookup(session_ids: Iterable[str]) -> dict[str, str]:
    """Map ``custom_id -> session id`` for a set of known session ids.

    Built once per retrieval rather than re-hashing every known id for
    every unmatched result. Where two ids collide the lexicographically
    first wins, which is what the previous linear scan did; the rebuild
    refuses such a manifest outright, so this only matters for a state
    whose manifest was never validated.
    """
    lookup: dict[str, str] = {}
    for session_id in sorted(session_ids):
        lookup.setdefault(build_custom_id(session_id), session_id)
    return lookup


def recover_session_id_from_custom_id(
    custom_id: str, lookup: dict[str, str] | None = None
) -> str | None:
    """Return the session id a custom_id was built from, if it is readable.

    The manifest, where one is available, is authoritative and answers both
    forms: ``build_custom_id`` is a pure function, so a lookup keyed on it
    reverses even the digest form. Shape is the fallback, and reads a
    40-character hex suffix as a digest.

    The manifest is consulted first only because it is the better answer,
    not because the order changes the result: the two agree wherever both
    speak. What matters is that shape is NOT consulted alone. A session id
    can ITSELF be 40 hex characters, in which case ``build_custom_id``
    emits it verbatim, and shape would tell the operator the id was "not
    recoverable" while it sat in plain sight in the custom_id.

    Args:
        custom_id: the id to reverse.
        lookup: ``custom_id -> session id`` from ``custom_id_lookup``, when
            a manifest could be read.

    Returns:
        The session id, or None when it genuinely cannot be determined.
    """
    if lookup:
        found = lookup.get(custom_id)
        if found is not None:
            return found
    if not custom_id.startswith("sess-"):
        return None
    suffix = custom_id[len("sess-"):]
    if not suffix or _HASHED_CUSTOM_ID_RE.match(suffix):
        return None
    return suffix


def rebuild_custom_id_map(out_dir: Path, manifest_path: Path) -> int:
    """Restore ``custom_id_to_session`` entries from a manifest.

    State files written before the map began accumulating lost the entries
    for a superseded batch the moment a top-up was submitted, which strands
    results that were already paid for. Every custom_id is a pure function
    of a session id, so the mapping can be rebuilt from any manifest that
    lists those sessions.

    Existing entries win: they were written by a real submission, whereas
    these are reconstructed.

    Args:
        out_dir: the provider subdirectory holding ``batch-state.json``.
        manifest_path: a manifest listing the sessions to restore.

    Returns:
        How many entries were added.

    Raises:
        FileNotFoundError: there is no batch state to repair.
        ManifestFormatError: the manifest is missing, unreadable, or not
            shaped like a manifest. This runs after a batch has been paid
            for, on a state file that is the only handle on it, so a
            half-understood manifest must stop the repair rather than write
            a partial map — and the operator has almost certainly just
            pasted a placeholder path.
    """
    state = read_batch_state(out_dir)
    if state is None:
        raise FileNotFoundError(
            f"no batch-state.json in {out_dir} — nothing to rebuild"
        )
    mapping = dict(state.get("custom_id_to_session", {}))
    before = len(mapping)
    #: What THIS manifest maps, used only to detect a collision within it.
    #: Conflicts against the stored map are not collisions: an existing
    #: entry was written by a real submission and deliberately wins.
    from_manifest: dict[str, str] = {}
    try:
        manifest = json.loads(manifest_path.read_text())
    except OSError as exc:
        raise ManifestFormatError(f"cannot read {manifest_path}: {exc}") from exc
    except ValueError as exc:
        raise ManifestFormatError(
            f"{manifest_path} is not valid JSON: {exc}"
        ) from exc
    sessions = manifest.get("sessions") if isinstance(manifest, dict) else None
    if not isinstance(sessions, list):
        raise ManifestFormatError(
            f"{manifest_path} has no 'sessions' list — is it a manifest?"
        )
    if not sessions:
        # Refused rather than reported. An empty manifest cannot repair
        # anything, so proceeding would rewrite batch-state.json, print
        # "restored 0", and leave the operator to work out that the file
        # they named was the wrong one -- most likely a manifest that has
        # itself been regenerated, or a placeholder path they edited badly.
        raise ManifestFormatError(
            f"{manifest_path} lists no sessions, so there is nothing to "
            "rebuild from; the batch state was left unchanged"
        )
    for position, entry in enumerate(sessions, 1):
        raw = entry.get("session_id") if isinstance(entry, dict) else None
        try:
            session_id = validate_session_id(
                raw, where=f"{manifest_path}: session {position}"
            )
        except SessionIdError as exc:
            raise ManifestFormatError(f"{exc}; no mapping was written") from exc
        custom_id = build_custom_id(session_id)
        clash = from_manifest.get(custom_id)
        if clash is not None and clash != session_id:
            # Two session ids in one manifest that produce one custom_id.
            # Reachable: build_custom_id hashes a long id to 40 hex
            # characters, and a session id that IS those 40 characters maps
            # to the same string. haiku_submit refuses this before paying
            # for a batch; a repair must refuse it too rather than pick one
            # with setdefault and write the other session's answers under
            # the wrong name.
            raise ManifestFormatError(
                f"{manifest_path}: sessions {clash!r} and {session_id!r} "
                f"both map to custom_id {custom_id!r}; no mapping was "
                "written"
            )
        from_manifest[custom_id] = session_id
        mapping.setdefault(custom_id, session_id)
    state["custom_id_to_session"] = mapping
    # Record the manifest so the NEXT retrieval can reverse a custom_id
    # without being handed it again. An existing record wins: it is the
    # provenance of the submission, whereas this is the file someone
    # happened to repair with.
    state.setdefault("manifest_path", str(manifest_path))
    write_json_atomic(out_dir / "batch-state.json", state)
    return len(mapping) - before


#: Stand-in for a manifest path the state does not record. Deliberately
#: free of shell metacharacters: the previous placeholder was ``<manifest>``,
#: which a shell reads as a redirection, so pasting the remedy line produced
#: "bash: manifest: No such file or directory" rather than running.
MANIFEST_PLACEHOLDER = "PATH-TO-MANIFEST"


def rebuild_map_command(batch_id: str, out_dir: Path, manifest: str | None) -> str:
    """Return the pastable command that repairs the map and retrieves again.

    ``manifest`` is the path recorded in ``batch-state.json`` when there is
    one; otherwise a placeholder the operator replaces.
    """
    manifest_arg = (
        shlex.quote(manifest) if manifest else MANIFEST_PLACEHOLDER
    )
    return (
        f"{haiku_retrieve_command(batch_id, out_dir)} "
        f"--manifest {manifest_arg} --rebuild-map"
    )


def batch_state_conflict(out_dir: Path, manifest_path: Path) -> str | None:
    """Explain why submitting into ``out_dir`` again would lose money.

    A Message Batch is billed when it is CREATED. The state file records the
    only handle on it, so a second submit both pays twice and overwrites the
    first batch's id, leaving the first job's results unreachable.

    Returns:
        A refusal message naming the stored batch id and the exact retrieval
        command, or None when the directory holds no batch state.
    """
    state = read_batch_state(out_dir)
    if state is None:
        return None
    batch_id = state["batch_id"]
    stored_hash = state.get("manifest_sha256")
    if stored_hash is None:
        provenance = "manifest unrecorded (state written by an older version)"
    elif stored_hash == file_sha256(manifest_path):
        provenance = "the SAME manifest as --manifest"
    else:
        provenance = "a DIFFERENT manifest from --manifest"
    return (
        f"[haiku] refused: a batch has already been submitted into {out_dir}.\n"
        f"  batch id:  {batch_id}\n"
        f"  submitted: {state.get('submitted_at', 'unknown')}\n"
        f"  requests:  {state.get('n_requests', 'unknown')} "
        f"({provenance})\n"
        "Submitting again would create a SECOND billed batch and replace the "
        "stored id, leaving the first job unretrievable. Retrieve the "
        "existing batch with:\n"
        f"  {haiku_retrieve_command(batch_id, out_dir)}\n"
        "Pass --resubmit to send only the sessions still missing (the "
        "top-up), or --force to send the whole manifest again. Either way "
        "the stored id is kept under superseded_batches."
    )


def haiku_submit(
    requests: list[SessionRequest],
    out_dir: Path,
    system_prompt: str,
    *,
    manifest_path: Path,
    allow_resubmit: bool = False,
) -> str:
    """Submit a single Batch API job; persist state; return the batch ID.

    Mirrors ``scripts/backfill-summaries.py:run_batch_submit``.

    Args:
        requests: the sessions to submit (already filtered for resume).
        out_dir: the provider subdirectory that holds ``batch-state.json``.
        system_prompt: the shared system layer.
        manifest_path: hashed into the state so a later submit can say
            whether the stored batch came from the same manifest.
        allow_resubmit: create a new batch even though a batch state
            already exists. It does NOT decide which sessions are sent —
            the caller has already filtered those — so a top-up and a full
            re-send both arrive here with this flag set.

    Raises:
        BatchStateExistsError: a batch is already recorded here and
            ``allow_resubmit`` is not set. Nothing is sent, nothing written.
        ValueError: two requests share a custom_id, which would silently
            collapse two sessions into one batch entry.
    """
    from anthropic import Anthropic  # type: ignore[import-not-found]

    previous = read_batch_state(out_dir)
    if previous is not None and not allow_resubmit:
        raise BatchStateExistsError(
            batch_state_conflict(out_dir, manifest_path) or "batch already submitted"
        )

    # Both checks happen BEFORE the billed create call. An unusable session
    # id cannot name a response file, and an id that collides would drop a
    # session from the state map and write one session's output under
    # another's name — either way, after the batch had been paid for.
    for position, request in enumerate(requests, 1):
        # Every request, not a sample: a manifest whose SECOND session
        # carries an unusable id would otherwise be submitted and billed.
        validate_session_id(
            request.session_id, where=f"manifest session {position}"
        )
    custom_to_session = {r.custom_id: r.session_id for r in requests}
    if len(custom_to_session) != len(requests):
        seen: dict[str, str] = {}
        clashes = []
        for request in requests:
            if request.custom_id in seen:
                clashes.append(
                    f"{request.custom_id} <- {seen[request.custom_id]} and "
                    f"{request.session_id}"
                )
            seen[request.custom_id] = request.session_id
        raise ValueError(
            "custom_id collision would lose a session in the batch state: "
            + "; ".join(clashes)
        )

    client = Anthropic()
    batch_requests = haiku_build_batch_requests(requests, system_prompt)
    batch_job = client.messages.batches.create(requests=batch_requests)

    superseded = list(previous.get("superseded_batches", [])) if previous else []
    if previous is not None:
        superseded.append(previous["batch_id"])
    # The custom_id map ACCUMULATES across submissions. A top-up carries
    # only the sessions still missing, so replacing the map would strand
    # every session from the superseded batch: `--haiku-apply <old id>`
    # would look each one up, find nothing, report "no session mapped to
    # custom_id" and skip it -- discarding results that were already paid
    # for (see the unmapped branch in haiku_apply). Both ids
    # are retrievable, so both maps must remain resolvable. The new
    # submission wins any key it shares, though it cannot disagree:
    # build_custom_id is a function of the session id.
    custom_id_map = dict(previous.get("custom_id_to_session", {})) if previous else {}
    custom_id_map.update(custom_to_session)
    state = {
        "batch_id": batch_job.id,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_requests": len(batch_requests),
        "manifest_path": str(manifest_path),
        "manifest_sha256": file_sha256(manifest_path),
        "superseded_batches": superseded,
        "custom_id_to_session": custom_id_map,
    }
    state_path = out_dir / "batch-state.json"
    write_json_atomic(state_path, state)
    print(f"[haiku] submitted batch {batch_job.id}")
    print(f"[haiku] state persisted to {state_path}")
    # ``out_dir`` here is the provider subdir (e.g. ``<root>/haiku``);
    # apply expects the user to pass the *root* ``--out-dir`` and
    # navigates into the provider subdir itself. Print the parent so
    # the hint copy-pastes cleanly.
    print(f"[haiku] retrieve with: {haiku_retrieve_command(batch_job.id, out_dir)}")
    return batch_job.id


def haiku_apply(
    batch_id: str,
    out_dir: Path,
    *,
    force: bool = False,
    manifest_path: Path | None = None,
) -> None:
    """Retrieve a completed Haiku batch and write per-session response files.

    Args:
        batch_id: the batch to fetch.
        out_dir: the provider subdirectory holding ``batch-state.json``.
        force: overwrite responses that are already complete on disk.
        manifest_path: the manifest supplied on this invocation, if any. It
            is what makes the printed repair command work in ONE run: the
            same invocation that rebuilds the map then uses that manifest
            to name any session the rebuild did not cover, and repeats it
            in any remedy line it still has to print.
    """
    from anthropic import Anthropic  # type: ignore[import-not-found]

    client = Anthropic()
    state_path = out_dir / "batch-state.json"
    state = json.loads(state_path.read_text())
    custom_to_session = state["custom_id_to_session"]

    # Read once, before the loop: it turns a guessed session id into a
    # confirmed one, and it is a file read.
    manifest_session_ids, effective_manifest = resolve_manifest(
        state, manifest_path
    )
    manifest_lookup = custom_id_lookup(manifest_session_ids)

    batch_job = client.messages.batches.retrieve(batch_id)
    if batch_job.processing_status != "ended":
        print(
            f"[haiku] batch {batch_id} not ready "
            f"(status: {batch_job.processing_status}); try later"
        )
        return

    n_ok = 0
    n_fail = 0
    n_kept = 0
    n_already = 0
    n_unmapped = 0
    for result in client.messages.batches.results(batch_id):
        session_id = custom_to_session.get(result.custom_id)
        if not session_id:
            # The result exists and was billed; only the mapping is missing.
            # Say which session it probably belongs to, say the money is
            # already spent, and print the remedy once at the end.
            n_unmapped += 1
            recovered = recover_session_id_from_custom_id(
                result.custom_id, manifest_lookup
            )
            which = (
                f"probably session {recovered}" if recovered
                else "session id not recoverable without a manifest — the "
                     "custom_id looks like a digest"
            )
            print(
                f"[haiku] no session mapped to custom_id {result.custom_id} "
                f"({which}) — skipping a result that was ALREADY PAID FOR"
            )
            continue
        if not force and response_is_complete(out_dir / f"{session_id}.json"):
            print(f"[haiku] {session_id} already complete — skipping")
            n_already += 1
            continue
        if result.result.type != "succeeded":
            if record_failure(
                out_dir, session_id, {"error": result.result.type}, tag="haiku"
            ):
                n_fail += 1
            else:
                n_kept += 1
            continue
        # An empty ``content`` list (rare but possible if the model
        # returns a successful result with no text blocks) would raise
        # IndexError below. Persist a structured failure record and
        # continue rather than crashing the whole retrieval loop.
        if not result.result.message.content:
            if record_failure(
                out_dir,
                session_id,
                {"error": "succeeded result had empty content list"},
                tag="haiku",
            ):
                n_fail += 1
            else:
                n_kept += 1
            print(
                f"[haiku] succeeded result for {session_id} carried no "
                "content blocks — recording empty-content error"
            )
            continue
        raw_text = result.result.message.content[0].text
        _atomic_write(out_dir / f"{session_id}.raw.txt", raw_text)
        try:
            parsed = parse_response_json(raw_text)
        except ValueError as exc:
            if record_failure(
                out_dir,
                session_id,
                {"error": str(exc), "raw": raw_text[:500]},
                tag="haiku",
            ):
                n_fail += 1
            else:
                n_kept += 1
        else:
            write_json_atomic(out_dir / f"{session_id}.json", parsed)
            n_ok += 1
    print(f"[haiku] wrote {n_ok} successes and {n_fail} failures to {out_dir}")
    if n_already or n_unmapped:
        print(
            f"[haiku] skipped {n_already} already-complete and {n_unmapped} "
            "unmapped result(s)"
        )
    if n_unmapped:
        # State files written before the custom_id map began accumulating
        # lose a superseded batch's entries as soon as a top-up is sent.
        print(
            f"[haiku] {n_unmapped} result(s) could not be matched to a "
            "session. This usually means the state file predates the "
            "accumulating custom_id map, so a later top-up replaced the "
            "entries for this batch. Restore them from the manifest and "
            "retrieve again:\n"
            f"  {rebuild_map_command(batch_id, out_dir, effective_manifest)}"
        )
    report_kept(n_kept, tag="haiku")


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
    *,
    force: bool = False,
) -> None:
    """Run all requests sequentially against Gemini Flex; persist responses.

    Sessions whose complete response is already on disk are skipped unless
    ``force`` is set — each one costs money to regenerate.
    """
    from google import genai  # type: ignore[import-not-found]

    requests = pending_requests(requests, out_dir, force=force, tag="gemini")
    if not requests:
        print("[gemini] nothing to do — every session already has a response")
        return
    client = genai.Client()
    n_ok = 0
    n_fail = 0
    n_kept = 0
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
            if record_failure(
                out_dir, r.session_id, {"error": str(exc)}, tag="gemini"
            ):
                n_fail += 1
            else:
                n_kept += 1
            print(f"[gemini]   failed: {exc}")
            continue
        _atomic_write(out_dir / f"{r.session_id}.raw.txt", raw_text)
        try:
            parsed = parse_response_json(raw_text)
        except ValueError as exc:
            if record_failure(
                out_dir,
                r.session_id,
                {"error": str(exc), "raw": raw_text[:500]},
                tag="gemini",
            ):
                n_fail += 1
            else:
                n_kept += 1
        else:
            write_json_atomic(out_dir / f"{r.session_id}.json", parsed)
            n_ok += 1
    print(f"[gemini] wrote {n_ok} successes and {n_fail} failures to {out_dir}")
    report_kept(n_kept, tag="gemini")


# ---------------------------------------------------------------------------
# OpenAI GPT-5.6 Luna adapter (Responses API, Flex tier)
# ---------------------------------------------------------------------------


def luna_call_once(
    user_message: str, system_prompt: str, *, service_tier: str = "flex",
    model: str = LUNA_MODEL,
) -> tuple[str, dict[str, Any], str]:
    """Single Responses-API call. Returns ``(text, usage, service_tier)``.

    The third element is the tier the request was actually served on —
    ``payload["service_tier"]`` when the API reports one, otherwise the tier
    that was asked for. It is recorded beside the usage figures because Flex
    and the default tier are priced differently, so a silent fallback would
    otherwise make the recorded cost wrong with nothing to show for it.

    Uses the **Responses API** (``POST /v1/responses``) rather than Chat
    Completions: OpenAI's guidance is that "Responses is recommended for all
    new projects", and reasoning models behave better on it. Verified
    2026-07-28 against developers.openai.com/api/docs/guides/migrate-to-responses.

    Deliberate parameter choices, each with a reason:

    - ``store=False`` — every call is independent; nothing is retained
      server-side. Keeps the arm stateless and avoids leaving transcript
      content in OpenAI's storage.
    - ``reasoning.effort="none"`` — **symmetry with the Gemini arm**, which
      sets ``thinking_config.thinking_level="minimal"`` (``thinking_budget=0``
      is rejected by gemini-3.6-flash; ``minimal`` is the closest available
      equivalent). Reasoning tokens bill at the *output* rate,
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

    api_key = resolve_openai_key("PA")
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
    return text, payload.get("usage", {}), payload.get("service_tier") or service_tier


def luna_call_with_retry(
    user_message: str, system_prompt: str, *, model: str = LUNA_MODEL
) -> tuple[str, dict[str, Any], str]:
    """Flex call with backoff on 429, falling back to the default tier.

    OpenAI documents Flex as returning ``429 Resource Unavailable`` under
    contention, explicitly *without* charging for the failed call. We retry on
    the same waits the Gemini arm uses, then degrade to the default tier so a
    busy Flex pool cannot stall the bake-off. The tier actually used is
    returned, and ``luna_run`` records it in ``_usage.json``, so the cost
    estimate can be corrected afterwards.
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
    force: bool = False,
) -> None:
    """Run all requests sequentially against Luna; persist responses + usage.

    Sequential by design, matching the Gemini arm: at ten requests the
    wall-clock saving from concurrency is irrelevant, and sequential execution
    keeps the two arms' timing comparable. For the production backfill this
    should become the Batch API (same 50% discount, 24h window) — see the
    plan doc; Tier-1 batch queue limits are 5M tokens, so a large run needs
    splitting into waves.
    """
    requests = pending_requests(requests, out_dir, force=force, tag=tag)
    if not requests:
        print(f"[{tag}] nothing to do — every session already has a response")
        return
    n_ok = 0
    n_fail = 0
    n_kept = 0
    usage_log: list[dict[str, Any]] = []
    for i, r in enumerate(requests, 1):
        print(
            f"[{tag}] {i}/{len(requests)}  {r.session_id[:8]}  "
            f"({r.bin}, {r.content_tokens:,} tokens) …"
        )
        try:
            raw_text, usage, service_tier = luna_call_with_retry(
                r.user_message, system_prompt, model=model
            )
        except Exception as exc:  # noqa: BLE001 — graceful per-session degrade
            if record_failure(
                out_dir, r.session_id, {"error": str(exc)}, tag=tag
            ):
                n_fail += 1
            else:
                n_kept += 1
            print(f"[{tag}]   failed: {exc}")
            continue
        _atomic_write(out_dir / f"{r.session_id}.raw.txt", raw_text)
        usage_log.append(
            {"session_id": r.session_id, "service_tier": service_tier, **usage}
        )
        try:
            parsed = parse_response_json(raw_text)
        except ValueError as exc:
            if record_failure(
                out_dir,
                r.session_id,
                {"error": str(exc), "raw": raw_text[:500]},
                tag=tag,
            ):
                n_fail += 1
            else:
                n_kept += 1
        else:
            write_json_atomic(out_dir / f"{r.session_id}.json", parsed)
            n_ok += 1
    # Real billed usage beats any estimate — record it for the cost
    # comparison, merged so a resumed run keeps the earlier rows.
    merge_usage_log(out_dir, usage_log)
    print(f"[{tag}] wrote {n_ok} successes and {n_fail} failures to {out_dir}")
    report_kept(n_kept, tag=tag)
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
    force: bool = False,
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

    requests = pending_requests(requests, out_dir, force=force, tag=tag)
    if not requests:
        print(f"[{tag}] nothing to do — every session already has a response")
        return
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    n_ok = n_fail = n_kept = 0
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
            if record_failure(
                out_dir, r.session_id, {"error": str(exc)}, tag=tag
            ):
                n_fail += 1
            else:
                n_kept += 1
            print(f"[{tag}]   failed: {exc}")
            continue
        _atomic_write(out_dir / f"{r.session_id}.raw.txt", raw_text)
        try:
            parsed = parse_response_json(raw_text)
        except ValueError as exc:
            if record_failure(
                out_dir,
                r.session_id,
                {"error": str(exc), "raw": raw_text[:500]},
                tag=tag,
            ):
                n_fail += 1
            else:
                n_kept += 1
        else:
            write_json_atomic(out_dir / f"{r.session_id}.json", parsed)
            n_ok += 1
    merge_usage_log(out_dir, usage_log)
    print(f"[{tag}] wrote {n_ok} successes and {n_fail} failures to {out_dir}")
    report_kept(n_kept, tag=tag)
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

    if requests:
        print()
        print("--- Example request body (first 400 chars of request 1) ---")
        print(requests[0].user_message[:400])
        print("…")

    # Write a dry-run-cost.json so the launch plan can include the figure
    # without re-running.
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out_dir / "dry-run-cost.json", cost)
    print(f"\nCost detail written to {out_dir / 'dry-run-cost.json'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


#: Markers delimiting the generated session blocks in the rubric template.
BEGIN_SESSIONS_MARKER = "<!--BEGIN-SESSIONS-->"
END_SESSIONS_MARKER = "<!--END-SESSIONS-->"

#: An **unpopulated** marker pair: the two markers with nothing between them
#: but whitespace. ``\s*`` deliberately tolerates a blank line, a trailing
#: space, and CRLF line endings — a template that differs from the canonical
#: one only in whitespace should still populate. It does NOT tolerate
#: content: see ``validate_rubric_template`` for why that must be a refusal.
SESSIONS_SPAN_RE = re.compile(
    re.escape(BEGIN_SESSIONS_MARKER) + r"\s*" + re.escape(END_SESSIONS_MARKER)
)


#: Fixed salt for the per-session blinding permutation: identical inputs must
#: regenerate an identical rubric and an identical key, so a re-run stays
#: comparable with the first run.
BLIND_SALT = "bakeoff-blind-2026-07-28"

#: Neutral labels for the arms. Twenty-six is far more than ``--provider``
#: offers; the length is what stops a discovered arm falling off the end.
BLIND_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class RubricTemplateError(RuntimeError):
    """The rubric template cannot be populated safely; nothing was written."""


def blind_order(session_id: str, available: list[str]) -> list[tuple[str, str]]:
    """Pair each available arm with a neutral letter, permuted per session.

    Two things were wrong with the previous scheme. It zipped against the
    literal tuple ``("A", "B", "C", "D")``, so a fifth arm was dropped from
    the rubric *and* from the key without a word — while ``--provider``
    offers six. And the "flip" was ``order.reverse()`` on an alphabetical
    list, which is two permutations, not n!: with four arms, letter A was
    always one of two providers, and a scorer who noticed could back-fill
    every earlier score.

    The permutation is drawn from a ``random.Random`` seeded with the salt
    and the session id. Seeding from a string is stable across runs and
    machines (CPython hashes the seed with SHA-512 rather than using the
    randomised ``hash()``), so the key regenerates byte for byte.

    Args:
        session_id: the session being blinded; the per-session entropy.
        available: arm names discovered on the filesystem, in any order.

    Returns:
        ``[(letter, arm), ...]`` covering every arm in ``available``.

    Raises:
        ValueError: more arms than there are letters to label them with.
    """
    if len(available) > len(BLIND_LETTERS):
        raise ValueError(
            f"{len(available)} arms exceed the {len(BLIND_LETTERS)} available "
            "blinding letters"
        )
    order = sorted(available)
    random.Random(f"{BLIND_SALT}:{session_id}").shuffle(order)
    return list(zip(BLIND_LETTERS, order))


def validate_rubric_template(template: str) -> None:
    """Refuse a rubric template that ``build_rubric`` cannot populate safely.

    The populate step is a *replacement* of the empty span between the two
    session markers. When that span is not empty — because the rubric has
    already been populated once — the replacement silently matches nothing
    and the old session blocks survive, while the blinding key beside the
    rubric is regenerated from the CURRENT filesystem. Add a provider arm,
    re-run, and every blinded score then decodes to the wrong model with no
    error and a cheerful "Wrote populated rubric" on stdout. So the only
    safe response to an already-populated (or malformed) template is to
    refuse before anything is written.

    Raises:
        RubricTemplateError: the markers are missing, duplicated, or already
            carry session blocks between them.
    """
    n_begin = template.count(BEGIN_SESSIONS_MARKER)
    n_end = template.count(END_SESSIONS_MARKER)
    if n_begin != 1 or n_end != 1:
        raise RubricTemplateError(
            f"the template must carry exactly one {BEGIN_SESSIONS_MARKER} and "
            f"one {END_SESSIONS_MARKER}; found {n_begin} and {n_end}"
        )
    if SESSIONS_SPAN_RE.search(template) is None:
        raise RubricTemplateError(
            "the session markers are not an empty pair — the template already "
            "carries session blocks. Populating it would leave the OLD blocks "
            "in place while writing a NEW blinding key, so every blinded score "
            "would decode to the wrong model. Re-run --build-rubric against "
            "the pristine template instead."
        )


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
    # Validate BEFORE any work: a refusal must leave the rubric, the
    # blinding key, and everything else on disk exactly as it found them.
    validate_rubric_template(template)

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
        # output. Each arm gets a neutral letter, permuted per session so a
        # scorer cannot learn "A is always the OpenAI one" halfway through
        # and back-fill their earlier scores. Deterministic (see
        # ``blind_order``) so a re-run is comparable with the first; the
        # mapping is written to a sidecar file, NOT into the rubric.
        labelled = blind_order(sid, available)
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
    # ``re.sub`` with a *function* replacement, not a string: the session
    # blocks carry JSON, and backslash sequences in a string replacement
    # would be interpreted as group references.
    replacement = (
        f"{BEGIN_SESSIONS_MARKER}\n{sessions_block}\n{END_SESSIONS_MARKER}"
    )
    populated, n_replaced = SESSIONS_SPAN_RE.subn(
        lambda _match: replacement, template, count=1
    )
    if n_replaced != 1:  # pragma: no cover — validate_rubric_template guards
        raise RubricTemplateError(
            "the session-marker span vanished between validation and "
            "substitution; nothing was written"
        )
    _atomic_write(rubric_out, populated)
    print(f"Wrote populated rubric to {rubric_out}")

    # The blinding key goes in a SIDECAR, never in the rubric — a scorer who
    # can see the mapping is not blind. Written next to the rubric so it is
    # trivially findable after scoring, and deliberately named so it is
    # obvious what not to open first.
    key_path = rubric_out.with_name(rubric_out.stem + ".blind-key.json")
    write_json_atomic(key_path, {
        "note": (
            "Model-letter -> provider mapping for the blinded rubric. Each "
            "session gets its own permutation of the arms, drawn from an RNG "
            "seeded with the salt and the session id, so the mapping is "
            "deterministic and re-generable but not guessable from the "
            "rubric itself. DO NOT read before scoring."
        ),
        "salt": BLIND_SALT,
        "redacted_errors": blind_key.pop("_redacted_errors", {}),
        "mapping": blind_key,
    })
    print(f"Wrote blinding key to {key_path} (do not open before scoring)")


def provider_model_id(provider: str) -> str:
    """Return the model id a provider name actually dispatches to."""
    if provider == "haiku":
        # The Batch adapter is the one arm not in PROVIDER_SPECS: that table
        # lists the real-time Haiku arm ("haiku-rt") at the standard rate.
        return HAIKU_MODEL
    if provider in PROVIDER_SPECS:
        return PROVIDER_SPECS[provider][0]
    raise ValueError(f"unknown provider: {provider}")


def provider_mode(provider: str) -> str:
    """Return "batch" or "real-time" — the second figure the gate must show."""
    return "batch" if provider == "haiku" else "real-time"


def gate_summary_lines(
    requests: list[SessionRequest], provider: str
) -> list[str]:
    """Render the API Call Review Gate figures for ``provider``.

    The gate (global CLAUDE.md) requires four things in front of the operator
    *before* any billed call: the model being called, batch versus real-time,
    the number of calls, and the estimated cost. These are the same numbers
    ``--dry-run`` prints, computed the same way, so approving here and
    approving after a dry run mean the same thing.
    """
    cost = estimate_cost_usd(requests, provider=provider)
    mode = provider_mode(provider)
    mode_detail = (
        "Message Batches API — ~24h SLA, 50% discount"
        if mode == "batch"
        else "synchronous request per session"
    )
    return [
        f"  model:          {provider_model_id(provider)}  (--provider {provider})",
        f"  mode:           {mode} ({mode_detail})",
        f"  requests:       {cost['n_requests']}",
        (
            f"  estimated cost: ${cost['total_cost_usd']} "
            f"(input ${cost['input_cost_usd']} over "
            f"{cost['input_tokens']:,} tokens @ "
            f"${cost['input_rate_per_mtok']}/Mtok; output "
            f"${cost['output_cost_usd']} assuming 350 tokens/call)"
        ),
    ]


def confirm_live_run(
    requests: list[SessionRequest], provider: str, *, assume_yes: bool
) -> bool:
    """Show the gate figures and return True only on an explicit approval.

    ``assume_yes`` still prints the figures: a ``--yes`` run leaves the same
    record in the terminal and the log as an interactive one, which is the
    point of the gate.

    A closed stdin (cron, a pipeline, a captured subprocess) raises
    ``EOFError`` from ``input()``. That must read as "no one is here to
    approve", not as an unhandled traceback — and the caller turns the
    False returned here into ``EXIT_REFUSED_AT_GATE``, so an unattended
    wrapper cannot mistake the refusal for a completed run.
    """
    print("\n--- API Call Review Gate — these calls are BILLED ---")
    for line in gate_summary_lines(requests, provider):
        print(line)
    if assume_yes:
        print(
            "  approval:       --yes given; recorded out-of-band. Proceeding."
        )
        return True
    try:
        answer = input(f"Type 'yes' to proceed with {provider} live calls: ")
    except EOFError:
        print(
            "Aborted: stdin is closed, so no approval can be given here. "
            "Re-run interactively, or pass --yes once the API Call Review "
            "Gate approval has been recorded."
        )
        return False
    if answer.strip().lower() != "yes":
        print("Aborted.")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` (default ``sys.argv[1:]``) and run the requested mode."""
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
    # --manifest and --prompt are NOT required at the parser level: the
    # retrieval path (--haiku-apply) can run without either, and demanding
    # them there made the recovery line this script prints un-runnable as
    # printed. The modes that do need them check for them explicitly, below.
    parser.add_argument(
        "--manifest",
        type=Path,
        help=(
            "Path to the sample manifest JSON. Required for a dry run, a "
            "live run, and --build-rubric. Optional but used by "
            "--haiku-apply: it names the sessions behind unmatched "
            "custom_ids and is what --rebuild-map restores the map from."
        ),
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        help=(
            "Path to the prompt markdown file. Required for a dry run, a "
            "live run, and --build-rubric; unused by --haiku-apply."
        ),
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
        "--force",
        action="store_true",
        help=(
            "Re-run sessions that already have a complete response on disk. "
            "Without it a re-run resumes: completed sessions are skipped, "
            "because each one cost money to produce."
        ),
    )
    parser.add_argument(
        "--resubmit",
        action="store_true",
        help=(
            "Batch arm only: permit a NEW submission into a directory that "
            "already holds batch-state.json, while still skipping sessions "
            "with a complete response. This is the top-up: after a partial "
            "--haiku-apply it sends only what is still missing. Use --force "
            "instead to send the whole manifest again."
        ),
    )
    parser.add_argument(
        "--rebuild-map",
        action="store_true",
        help=(
            "Batch arm only, with --haiku-apply and --manifest: restore the "
            "custom_id -> session entries in batch-state.json from the "
            "manifest before retrieving. Use it when a retrieval reports "
            "results it cannot match to a session."
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
    args = parser.parse_args(argv)

    # ``load_env`` hydrates provider secrets from the repository .env. Only
    # the paths that actually reach a provider call it, so a dry run or a
    # rubric build never pulls credentials into this process's environment.

    if args.build_rubric:
        if not (args.rubric_in and args.rubric_out):
            print("--build-rubric requires --rubric-in and --rubric-out")
            return 2
        if not (args.manifest and args.prompt):
            print(
                "--build-rubric requires --manifest and --prompt",
                file=sys.stderr,
            )
            return 2
        try:
            build_rubric(
                args.manifest, args.prompt, args.out_dir,
                args.rubric_in, args.rubric_out,
            )
        except RubricTemplateError as exc:
            print(f"--build-rubric refused: {exc}", file=sys.stderr)
            return 2
        return 0

    if not args.provider:
        print("--provider is required unless --build-rubric is set")
        return 2

    if args.rebuild_map and not args.haiku_apply:
        print(
            "--rebuild-map repairs the state a retrieval reads; use it with "
            "--haiku-apply",
            file=sys.stderr,
        )
        return 2

    if args.resubmit and args.provider != "haiku":
        # Silently ignoring it would let an operator believe they had asked
        # for a top-up on an arm that has no batch state to top up.
        print(
            "--resubmit is only valid with --provider haiku (the other arms "
            "resume per session by default; --force re-runs them)",
            file=sys.stderr,
        )
        return 2

    if args.haiku_apply:
        if args.provider != "haiku":
            print("--haiku-apply is only valid with --provider haiku")
            return 2
        if args.rebuild_map and not args.manifest:
            print(
                "--rebuild-map needs --manifest: the sessions to restore are "
                "read from it",
                file=sys.stderr,
            )
            return 2
        if args.resubmit:
            # Retrieval submits nothing, so there is no second submission
            # to permit. Accepting the flag here would let an operator
            # believe they had asked for a top-up when they had asked for
            # a retrieval — and then wonder why no new batch appeared.
            print(
                "--resubmit submits a new batch; it cannot be combined with "
                "--haiku-apply, which only retrieves an existing one. Run "
                "the retrieval first, then re-run with --resubmit to send "
                "whatever is still missing.",
                file=sys.stderr,
            )
            return 2
        # Retrieval is FREE: the batch was billed when it was submitted, and
        # `batches.retrieve` / `batches.results` cost nothing. So it is
        # deliberately not behind the API Call Review Gate — but it still
        # says what it is about to fetch and where the results will land,
        # because "ungated" must not mean "silent".
        target_dir = args.out_dir / "haiku"
        print(
            f"[haiku] retrieving batch {args.haiku_apply} into {target_dir} "
            "— retrieval is free and therefore ungated (the submission was "
            "the billed step)."
        )
        if args.rebuild_map:
            try:
                restored = rebuild_custom_id_map(target_dir, args.manifest)
            except (FileNotFoundError, ManifestFormatError) as exc:
                print(f"--rebuild-map refused: {exc}", file=sys.stderr)
                return 2
            state_after = read_batch_state(target_dir) or {}
            recorded = state_manifest_path(state_after)
            provenance = f" from {args.manifest}"
            if recorded and recorded != str(args.manifest):
                # The asymmetry is deliberate (the recorded path is the
                # submission's provenance and is never overwritten), but it
                # is confusing unseen: the map was rebuilt from one file
                # while the state still names another.
                provenance += (
                    f"; the state still records {recorded} as the manifest "
                    "it was submitted against"
                )
            print(
                f"[haiku] --rebuild-map restored {restored} custom_id "
                f"mapping(s) in {target_dir / 'batch-state.json'}{provenance}"
            )
        load_env()
        # submit persists batch-state.json under the provider subdir
        # (<out-dir>/haiku/), so apply must navigate to the same subdir.
        # --manifest is threaded through so a repair run can reverse a
        # custom_id in the same invocation that rebuilt the map.
        haiku_apply(
            args.haiku_apply, target_dir,
            force=args.force, manifest_path=args.manifest,
        )
        return 0

    if not (args.manifest and args.prompt):
        print(
            f"--provider {args.provider} requires --manifest and --prompt "
            "(only --haiku-apply runs without them)",
            file=sys.stderr,
        )
        return 2

    try:
        # Before the cost gate, deliberately: an unusable session id is a
        # manifest problem, and being told about it after approving a
        # billed run -- as a traceback -- helps nobody.
        requests = assemble_requests(args.manifest, args.prompt)
    except SessionIdError as exc:
        print(f"{args.manifest} cannot be used: {exc}", file=sys.stderr)
        return 2
    if not requests:
        # An empty manifest is a mistake upstream, not a run with nothing to
        # do: say so and stop before creating a provider directory or a
        # cost file that would later look like the record of a real run.
        print(
            f"{args.manifest} lists no sessions — nothing to do. "
            "(Re-sample the manifest, or check --manifest points at the "
            "right file.)"
        )
        return 0
    system_prompt = args.prompt.read_text()
    provider_dir = args.out_dir / args.provider
    provider_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        dry_run_report(requests, args.provider, provider_dir)
        return 0

    # Live mode — guarded by the API Call Review Gate. The gate prints the
    # model, the mode, the request count, and the estimated cost before it
    # asks anything, so an operator who has not run --dry-run still sees the
    # four figures the gate requires.
    #
    # The figures describe what will ACTUALLY be sent: sessions that
    # already have a complete response are dropped first, so the count and
    # the cost are the ones about to be incurred rather than the ones a
    # first run would have incurred. Only --force disables this filter, and
    # it means "send the whole manifest again".
    #
    # The Batch arm has a second gate on top (batch-state.json, below).
    # Permission to submit again and the choice of what to send are
    # deliberately separate flags: --resubmit unlocks the second submit and
    # keeps the filter, so a top-up after a partial --haiku-apply sends only
    # the missing sessions. Folding both into --force made the advertised
    # top-up unreachable -- the only way past the state check also re-sent
    # everything.
    requests = pending_requests(
        requests, provider_dir, force=args.force, tag=args.provider
    )
    if not requests:
        print(
            "Every session in the manifest already has a complete "
            "response; nothing to send. Pass --force to re-run them."
        )
        return 0

    # A Message Batch is billed at creation and its id lives only in
    # batch-state.json, so a second submit into the same directory pays
    # twice AND orphans the first job. Refused before the gate: there is
    # nothing to approve.
    if args.provider == "haiku" and not (args.force or args.resubmit):
        conflict = batch_state_conflict(provider_dir, args.manifest)
        if conflict:
            print(conflict, file=sys.stderr)
            return 2
    print(
        "Live mode requested. This will make billed API calls. "
        "Re-run with --dry-run first if you want the per-session breakdown."
    )
    if not confirm_live_run(requests, args.provider, assume_yes=args.yes):
        return EXIT_REFUSED_AT_GATE

    # Credentials are hydrated only once the run is approved.
    load_env()

    if args.provider == "haiku":
        try:
            haiku_submit(
                requests, provider_dir, system_prompt,
                manifest_path=args.manifest,
                allow_resubmit=args.force or args.resubmit,
            )
        except BatchStateExistsError as exc:
            # Unreachable via main (the check above fires first); kept so the
            # adapter is safe for any other caller.
            print(str(exc), file=sys.stderr)
            return 2
    elif args.provider == "gemini":
        gemini_run(requests, provider_dir, system_prompt, force=args.force)
    elif args.provider == "luna":
        luna_run(requests, provider_dir, system_prompt, force=args.force)
    elif args.provider == "terra":
        luna_run(
            requests, provider_dir, system_prompt,
            model=TERRA_MODEL, tag="terra", force=args.force,
        )
    elif args.provider == "haiku-rt":
        haiku_rt_run(requests, provider_dir, system_prompt, force=args.force)
    elif args.provider == "sonnet-5":
        haiku_rt_run(
            requests, provider_dir, system_prompt,
            model=SONNET_MODEL, tag="sonnet-5", disable_thinking=True,
            force=args.force,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
