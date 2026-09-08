#!/usr/bin/env python3
"""
Embedding generation via Ollama HTTP Application Programming Interface (API).

Provides batch embedding of text via the local Ollama service
(nomic-embed-text model). Designed for graceful degradation: returns
None per text when Ollama is unavailable, allowing callers to proceed
without embeddings.

Usage:
    from embed import generate_embeddings, embed_single, build_embed_text

    text = build_embed_text(memory_record)
    vector = embed_single(text)
    vectors = generate_embeddings(["text1", "text2"])
"""

import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

# Shared HTTP retry helper (audit IC7). Importing by absolute filesystem
# path because ``embed.py`` may be invoked from a working directory that
# does not contain ``scripts/`` on ``sys.path``.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _http_retry import urlopen_with_retry  # noqa: E402

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
# ``or`` rather than a ``.get`` default (audit round two, finding P3 /
# lens A-C3). ``scripts/ollama-endpoint.sh`` prints an empty string and
# exits 1 when no candidate endpoint answers, and the documented cron
# wrapper exports exactly that: ``OLLAMA_BASE_URL=$(ollama-endpoint.sh)``.
# ``os.environ.get(name, default)`` returns the empty string in that case
# — the key *exists* — so the request URL became the relative
# ``/api/tags`` and ``urllib.request.Request`` raised
# ``ValueError: unknown url type``, which falls outside this module's
# degradation ladder and tracebacks out of the caller. The wrapper's own
# header comment already promises this fallback; now it is true.
# ``.strip()`` also covers a stray newline from command substitution.
OLLAMA_BASE_URL = (
    os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL
)
DEFAULT_MODEL = "nomic-embed-text"
# Timeout scales with batch size: base + per_item * count
TIMEOUT_BASE_S = 10
TIMEOUT_PER_ITEM_S = 0.5

# The width the whole pipeline is built around: ``vector(768)`` in
# scripts/schema.sql, and therefore the shape of every embedding already
# in the canonical embedding space. Audit round two, finding P12 (lens
# A-M10): nothing validated this. A remote endpoint serving a different
# nomic-embed-text build makes PostgreSQL reject the UPDATE, the broad
# handler in sync-to-postgres.py turns that into a warning, and the same
# rows are re-fetched and re-embedded on every cron tick indefinitely —
# no quarantine, no escalation, and cosine distances that would be
# meaningless if they ever did land.
EXPECTED_EMBEDDING_DIM = 768

logger = logging.getLogger("embed")


class EmbeddingDimensionError(RuntimeError):
    """
    The endpoint returned vectors of the wrong width.

    Raised rather than returned because this is a configuration fault,
    not a transient failure: retrying reproduces it exactly, and every
    retry costs a full batch of inference. The caller is expected to stop
    and tell the operator which model is actually being served.
    """


# ============================================================================
# Text Construction
# ============================================================================


def build_embed_text(record: dict[str, Any]) -> str:
    """
    Construct the text to embed from a memory record.

    Concatenates content, summary, and source_context — the same fields
    indexed by PostgreSQL full-text search (FTS). This ensures semantic
    search covers the same surface as keyword search.

    Args:
        record: Memory record dict with at least a ``content`` field.

    Returns:
        Concatenated text string for embedding.
    """
    parts = [
        record.get("content", ""),
        record.get("summary", "") or "",
        record.get("source_context", "") or "",
    ]
    return " ".join(p for p in parts if p).strip()


# ============================================================================
# Ollama API
# ============================================================================


def is_ollama_available(model: str = DEFAULT_MODEL) -> bool:
    """
    Check whether Ollama is running and the specified model is loaded.

    Hits the ``/api/tags`` endpoint and checks the model list.

    The match is **exact** on the model name returned by Ollama, with
    one allowed concession: an Ollama tag suffix (``:latest``,
    ``:q8_0``) on the *installed* name is treated as the same model
    (because ``ollama pull nomic-embed-text`` installs it as
    ``nomic-embed-text:latest``). A bare ``nomic-embed-text`` request
    will therefore match ``nomic-embed-text`` or ``nomic-embed-text:*``,
    but **not** ``nomic-embed-text-v1.5`` or ``my-fork-of-nomic-embed-text``.

    Audit context (A-Medium #9, 2026-05-02): the previous implementation
    used a substring match (``model in m``), which would silently accept
    a fine-tuned variant with a different embedding dimension and break
    pgvector cosine-distance comparisons across the canonical embedding
    space.

    Args:
        model: Model name to check for (default: nomic-embed-text).

    Returns:
        True if Ollama is reachable and the model is available.
    """
    try:
        url = f"{OLLAMA_BASE_URL}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            # Exact match, or exact match with a tag suffix
            # (``nomic-embed-text:latest`` matches ``nomic-embed-text``).
            return any(
                installed == model or installed.startswith(model + ":")
                for installed in models
            )
    except (
        urllib.error.URLError, OSError, json.JSONDecodeError, ValueError,
    ) as exc:
        # ValueError covers a malformed OLLAMA_BASE_URL ("unknown url
        # type") — a configuration mistake must degrade like an outage,
        # not traceback out of a caller that has no handler (finding P3).
        logger.debug("Ollama availability check failed: %s", exc)
        return False


def _assert_embedding_dimension(
    embeddings: list[list[float] | None],
    model: str,
) -> None:
    """
    Fail loudly when the endpoint returns vectors of an unexpected width.

    Checked once per batch, on the first non-None vector: within a single
    response every vector comes from the same model, so a second check
    would cost time without adding information.

    ``is_ollama_available``'s docstring names dimension mismatch as the
    risk it guards against, but it can only compare the model *name* —
    the endpoint may be a different machine serving a different build
    under the same name. This is the check that actually holds
    (audit round two, finding P12 / lens A-M10).

    Args:
        embeddings: The vectors returned for one batch (may contain None).
        model: The model name requested, for the error message.

    Raises:
        EmbeddingDimensionError: If a vector's width is not
            :data:`EXPECTED_EMBEDDING_DIM`.
    """
    for vector in embeddings:
        if vector is None:
            continue
        if len(vector) != EXPECTED_EMBEDDING_DIM:
            raise EmbeddingDimensionError(
                f"{model} at {OLLAMA_BASE_URL} returned {len(vector)}-"
                f"dimensional vectors; this pipeline stores "
                f"vector({EXPECTED_EMBEDDING_DIM}) and every existing "
                f"embedding is that width. Refusing to embed: check which "
                f"model the endpoint is actually serving."
            )
        return


def generate_embeddings(
    texts: list[str],
    model: str = DEFAULT_MODEL,
) -> list[list[float] | None]:
    """
    Generate embeddings for a batch of texts via Ollama.

    Calls the ``/api/embed`` endpoint which supports batch input.
    On failure, returns a list of None values (same length as input)
    so callers can handle partial results gracefully.

    Args:
        texts: List of text strings to embed.
        model: Ollama model name (default: nomic-embed-text).

    Returns:
        List of embedding vectors (list[float]) or None per text on
        failure. Always the same length as the input.
    """
    if not texts:
        return []

    timeout = TIMEOUT_BASE_S + TIMEOUT_PER_ITEM_S * len(texts)

    try:
        url = f"{OLLAMA_BASE_URL}/api/embed"
        payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # Audit IC7: route the Ollama call through the shared retry
        # helper so a brief outage (model swap, ollama serve restart) no
        # longer leaves rows permanently unembedded. The helper retries
        # transient errors with exponential backoff plus jitter; final
        # failures still propagate to the existing except ladder below
        # so the graceful-degradation contract is preserved.
        with urlopen_with_retry(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            embeddings = data.get("embeddings", [])

            # Validate length matches input
            if len(embeddings) != len(texts):
                logger.warning(
                    "Ollama returned %d embeddings for %d inputs",
                    len(embeddings), len(texts),
                )
                # Truncate if too many, pad with None if too few
                embeddings = embeddings[:len(texts)]
                while len(embeddings) < len(texts):
                    embeddings.append(None)

            _assert_embedding_dimension(embeddings, model)
            return embeddings

    except EmbeddingDimensionError:
        # Configuration fault, not a transient one: re-raise past the
        # degradation handlers below so the caller stops instead of
        # silently re-queueing the same rows forever (finding P12).
        raise
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Embedding generation failed: %s", exc)
        return [None] * len(texts)
    except Exception as exc:
        logger.error("Unexpected embedding error: %s", exc)
        return [None] * len(texts)


def embed_single(
    text: str,
    model: str = DEFAULT_MODEL,
) -> list[float] | None:
    """
    Generate an embedding for a single text string.

    Convenience wrapper around :func:`generate_embeddings`.

    Args:
        text: Text to embed.
        model: Ollama model name.

    Returns:
        Embedding vector or None on failure.
    """
    results = generate_embeddings([text], model=model)
    return results[0] if results else None
