"""Synthetic transcripts, manifests, responses, and memory records.

Builders used by ``test_bake_off_metadata.py``,
``test_resample_bake_off_manifest.py``, and
``test_analyse_wiki_vocabulary.py``. Every literal here is invented (see the
package docstring): the fixtures imitate the *shape* of the real artefacts
and none of their content.

The transcripts are written in the on-disk JSON Lines (JSONL) form the real
distiller consumes, so tests run them through the production extractor
(``scripts/extract-transcript-text.py`` re-exporting
``cc_session_toolkit.transcript_text``) rather than through a stand-in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Invented prose. Long enough that a handful of records clears the
# 1,000-token floor the re-sampler applies.
# ---------------------------------------------------------------------------

#: One invented sentence per turn, rotated through so the distilled text is
#: not a single repeated string (a repeated string would compress oddly and
#: make token estimates unrepresentative).
FILLER_SENTENCES: tuple[str, ...] = (
    "The Thornhollow survey grid was walked at twenty-metre intervals and "
    "every ceramic scatter was bagged by collection unit.",
    "Magnetometry over the western terrace returned three anomalies that do "
    "not correspond to any mapped field boundary.",
    "The 1974 aerial photographs show a cropmark enclosure south of the "
    "modern track, invisible on the ground today.",
    "Sherd weights were recorded to the nearest gram and the fabric groups "
    "follow the invented Middle Vale type series.",
    "Radiocarbon determinations from the ditch fill were calibrated with the "
    "southern-hemisphere curve and reported at two sigma.",
    "The landscape phase model treats terrace construction and abandonment "
    "as separate events rather than one continuous episode.",
)


def _turn_text(index: int, *, repeats: int = 1) -> str:
    """Build one turn's text: a numbered line plus ``repeats`` sentences."""
    body = " ".join(
        FILLER_SENTENCES[(index + offset) % len(FILLER_SENTENCES)]
        for offset in range(repeats)
    )
    return f"Turn {index}. {body}"


def session_records(n_records: int = 60, *, repeats: int = 1) -> list[dict]:
    """Return ``n_records`` alternating user / assistant transcript records.

    Args:
        n_records: how many records to emit (alternating roles).
        repeats: invented sentences per turn — the knob that grows a
            transcript past a token floor without changing its shape.
    """
    records: list[dict] = []
    for index in range(n_records):
        text = _turn_text(index, repeats=repeats)
        if index % 2 == 0:
            records.append(
                {"type": "user", "message": {"role": "user", "content": text}}
            )
        else:
            records.append({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
            })
    return records


def write_session_transcript(
    path: Path, *, n_records: int = 60, repeats: int = 1
) -> Path:
    """Write a synthetic session JSONL transcript and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record) for record in session_records(n_records, repeats=repeats)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest rows — the exact key set ``write_manifest`` emits and
# ``assemble_requests`` reads.
# ---------------------------------------------------------------------------


def manifest_row(
    session_id: str,
    transcript_path: Path | str,
    *,
    project: str = "thornhollow-survey",
    bin_label: str = "short",
    content_tokens: int = 1_200,
    meta_path: str | None = None,
    three_ps_state: str = "empty",
    source: str = "archive",
    started_at: str | None = "2026-01-05T09:15:00+00:00",
) -> dict[str, Any]:
    """Return one manifest session row with every key the writer emits."""
    return {
        "session_id": session_id,
        "project": project,
        "transcript_path": str(transcript_path),
        "meta_path": meta_path,
        "content_tokens": content_tokens,
        "bin": bin_label,
        "current_three_ps_state": three_ps_state,
        "source": source,
        "started_at": started_at,
    }


def write_manifest(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Write a manifest JSON file wrapping ``rows`` and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": "2026-01-06T00:00:00+00:00",
        "rng_seed": 42,
        "extractor": "scripts/extract-transcript-text.py",
        "token_estimator": "chars / 4",
        "sessions": rows,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Provider responses — the four shapes the parser and the rubric must handle.
# ---------------------------------------------------------------------------

#: A well-formed response object, emitted bare as the prompt demands.
RESPONSE_OBJECT: dict[str, Any] = {
    "title": "Thornhollow terrace phasing",
    "purpose": "Decide whether the terrace episodes are one event or two.",
    "tags": ["survey", "phasing", "invented-site"],
    "three_ps": {
        "prompt_summary": "Asked for a phase model of the western terrace.",
        "process_summary": "Compared magnetometry anomalies with the grid walk.",
        "provenance_summary": "Feeds the invented Middle Vale synthesis chapter.",
    },
}

RESPONSE_BARE = json.dumps(RESPONSE_OBJECT, indent=2)
RESPONSE_FENCED = f"```json\n{RESPONSE_BARE}\n```"
RESPONSE_FENCED_WITH_PROSE = (
    f"```json\n{RESPONSE_BARE}\n```\n\nHappy to refine the tag list."
)
RESPONSE_PROSE_ONLY = "I had a look at the transcript and here is my summary."
RESPONSE_ERROR: dict[str, Any] = {
    "error": "context window exceeded: 200000 maximum input tokens"
}


# ---------------------------------------------------------------------------
# Memory records for the wiki-vocabulary analyser.
# ---------------------------------------------------------------------------


def memory_record(
    record_id: str,
    *,
    research_tags: list[Any],
    created_at: str = "2026-01-05T10:00:00+00:00",
    category: str = "insight",
    content: str = "Terrace phasing needs a separate abandonment event.",
) -> dict[str, Any]:
    """Return one memory record with the keys the analyser reads."""
    return {
        "id": record_id,
        "session_id": "invented-session",
        "category": category,
        "content": content,
        "confidence": "high",
        "research_tags": research_tags,
        "created_at": created_at,
    }


def write_memories_jsonl(path: Path, records: list[Any]) -> Path:
    """Write memory records as JSONL; a plain string is written verbatim.

    Passing a string lets a test insert a deliberately malformed line
    without building a record for it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        record if isinstance(record, str) else json.dumps(record)
        for record in records
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
