"""
Tests pinning the embedding-queue ordering after the B-M10 fix.

Audit context (2026-05-02): the previous ``ORDER BY created_at DESC``
walked the unembedded queue newest-first, which under sustained load
left older rows permanently outside the HNSW partial index. Both
``sync-to-postgres.py`` and ``backfill-embeddings.py`` now order the
queue ascending so older rows can never be starved.

These tests inspect the SQL string literal in each script — there is no
running PostgreSQL in the test environment and a behavioural test would
require it. Pinning the literal is sufficient to catch a regression
where a future maintainer flips the ordering back without realising.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYNC_TO_POSTGRES = PROJECT_ROOT / "scripts" / "sync-to-postgres.py"
BACKFILL_EMBEDDINGS = PROJECT_ROOT / "scripts" / "backfill-embeddings.py"


class TestEmbeddingQueueOrdering:
    """Both embedding queues walk oldest-first."""

    def test_sync_to_postgres_uses_asc(self) -> None:
        """The cron loop in sync-to-postgres.py must order ASC."""
        source = SYNC_TO_POSTGRES.read_text(encoding="utf-8")
        # Locate the embedding-queue query specifically (there are
        # multiple ORDER BY clauses in the file overall).
        marker = "WHERE embedding IS NULL"
        idx = source.find(marker)
        assert idx >= 0, "embedding-queue query not found in sync-to-postgres.py"
        # Examine a window of ~200 chars after the marker.
        window = source[idx : idx + 200]
        assert "ORDER BY created_at ASC" in window, (
            "sync-to-postgres.py embedding queue must walk oldest-first "
            "(ASC). Found: " + window
        )
        assert "ORDER BY created_at DESC" not in window, (
            "sync-to-postgres.py embedding queue must not walk DESC — "
            "B-M10 regression. Found: " + window
        )

    def test_backfill_embeddings_uses_asc(self) -> None:
        """The catch-up tool in backfill-embeddings.py must order ASC."""
        source = BACKFILL_EMBEDDINGS.read_text(encoding="utf-8")
        # The script has two queries containing ``WHERE embedding IS
        # NULL``: one in ``count_missing`` (no ORDER BY) and one in
        # ``fetch_batch`` (the one we care about). Pin the latter.
        marker = "WHERE embedding IS NULL"
        idx_first = source.find(marker)
        assert idx_first >= 0, "embedding queue query not found"
        idx_second = source.find(marker, idx_first + len(marker))
        assert idx_second >= 0, (
            "expected two ``WHERE embedding IS NULL`` queries in "
            "backfill-embeddings.py (count + fetch); found only one"
        )
        window = source[idx_second : idx_second + 200]
        assert "ORDER BY created_at ASC" in window, (
            "backfill-embeddings.py must walk oldest-first (ASC). "
            "Found: " + window
        )
        assert "ORDER BY created_at DESC" not in window, (
            "backfill-embeddings.py must not walk DESC — B-M10 "
            "regression. Found: " + window
        )
