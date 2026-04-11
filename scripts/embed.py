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
import urllib.request
import urllib.error
from typing import Any

# ============================================================================
# Configuration
# ============================================================================

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = "nomic-embed-text"
# Timeout scales with batch size: base + per_item * count
TIMEOUT_BASE_S = 10
TIMEOUT_PER_ITEM_S = 0.5

logger = logging.getLogger("embed")


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
            # Match on model name prefix (handles tags like :latest)
            return any(model in m for m in models)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.debug("Ollama availability check failed: %s", exc)
        return False


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

        with urllib.request.urlopen(req, timeout=timeout) as resp:
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

            return embeddings

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
