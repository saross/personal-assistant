"""Tests for scripts/tag-gardening.py."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import importlib

tag_gardening = importlib.import_module("tag-gardening")
# Also import the guard module so we can patch the original symbol as
# well as the one bound into tag_gardening's namespace.
_bulk_rewrite_guard = importlib.import_module("_bulk_rewrite_guard")


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def bypass_rewrite_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate one mutating test from the live data submodule's git state.

    ``cmd_merge`` and ``orphans --action clean`` call
    ``ensure_safe_to_rewrite`` to refuse running while
    ``data/memories/memories.jsonl`` or ``tag-vocabulary.txt`` have
    uncommitted changes. During development the extraction hook routinely
    appends to those files, so the guard correctly aborts and a test that
    only wants to exercise the merge algorithm fails through no fault of
    its own.

    This was AUTOUSE until audit round 4a (2026-09-08, finding B4). That
    made the guard a no-op for the WHOLE module, so a test that forgot to
    patch ``MEMORIES_JSONL`` rewrote the real canonical store and the suite
    stayed green — reproduced in a copy. It is now requested by name, so a
    test that has not thought about the guard meets the real one. Patching
    is applied at both the source module and the tag-gardening namespace
    binding to be robust against import-style changes.
    """
    noop = lambda *args, **kwargs: None  # noqa: E731
    monkeypatch.setattr(
        tag_gardening, "ensure_safe_to_rewrite", noop, raising=False,
    )
    monkeypatch.setattr(
        _bulk_rewrite_guard, "ensure_safe_to_rewrite", noop,
        raising=False,
    )

@pytest.fixture
def pg_recorder(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture the PostgreSQL reconciliation rather than opening a connection.

    A merge now issues a surgical UPDATE per touched id (audit finding A8).
    These tests are about the JSONL and the vocabulary, so they record the
    call and assert nothing about it; ``TestReconcilePostgres`` below drives
    the real SQL against a fake connection.
    """
    calls: list = []
    monkeypatch.setattr(
        tag_gardening, "reconcile_postgres",
        lambda updates, **kwargs: calls.append(updates),
    )
    return calls


SAMPLE_MEMORIES = [
    {
        "id": "mem-001",
        "content": "Test memory 1",
        "research_tags": ["pipeline", "validation", "data-quality"],
    },
    {
        "id": "mem-002",
        "content": "Test memory 2",
        "research_tags": ["pipeline", "pipelines", "api"],
    },
    {
        "id": "mem-003",
        "content": "Test memory 3",
        "research_tags": ["api", "api-integration", "testing"],
    },
    {
        "id": "mem-004",
        "content": "Test memory 4",
        "research_tags": ["validation", "api", "architecture"],
    },
    {
        "id": "mem-005",
        "content": "Memory with no tags",
        "research_tags": [],
    },
    {
        "id": "mem-006",
        "content": "Memory with tags field",
        "tags": ["singleton-tag"],
    },
]


def write_sample_jsonl(path: Path, memories: list[dict] | None = None) -> None:
    """Write sample memories to a JSONL file."""
    mems = memories or SAMPLE_MEMORIES
    with open(path, "w", encoding="utf-8") as fh:
        for mem in mems:
            fh.write(json.dumps(mem) + "\n")


def write_sample_vocab(path: Path, tags: list[str] | None = None) -> None:
    """Write a sample vocabulary file."""
    vocab = tags or [
        "api", "api-integration", "architecture", "data-quality",
        "orphaned-tag", "pipeline", "pipelines", "singleton-tag",
        "testing", "validation",
    ]
    path.write_text("\n".join(sorted(vocab)) + "\n", encoding="utf-8")


# -------------------------------------------------------------------------
# Stats tests
# -------------------------------------------------------------------------

class TestBuildTagCounts:
    """Tests for build_tag_counts()."""

    def test_counts_from_research_tags(self) -> None:
        """Tags from research_tags field are counted correctly."""
        counts = tag_gardening.build_tag_counts(SAMPLE_MEMORIES)
        assert counts["api"] == 3
        assert counts["pipeline"] == 2
        assert counts["validation"] == 2

    def test_counts_from_tags_field(self) -> None:
        """Tags from the 'tags' field (fallback) are also counted."""
        counts = tag_gardening.build_tag_counts(SAMPLE_MEMORIES)
        assert counts["singleton-tag"] == 1

    def test_empty_tags_ignored(self) -> None:
        """Memories with empty tags don't contribute."""
        counts = tag_gardening.build_tag_counts(SAMPLE_MEMORIES)
        # mem-005 has empty research_tags — total should be correct
        # 3 + 3 + 3 + 3 + 0 + 1 = 13
        total = sum(counts.values())
        assert total == 13

    def test_empty_memories_list(self) -> None:
        """Empty input returns empty counter."""
        counts = tag_gardening.build_tag_counts([])
        assert len(counts) == 0


class TestStats:
    """Integration tests for the stats subcommand output."""

    def test_load_and_count(self, tmp_path: Path) -> None:
        """Memories load correctly and tag counts are accurate."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
        ):
            memories = tag_gardening.load_memories()
            counts = tag_gardening.build_tag_counts(memories)

        assert len(memories) == 6
        assert counts["api"] == 3

    def test_stats_json_keys(self, tmp_path: Path, capsys) -> None:
        """Stats subcommand outputs JSON with all expected keys."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
        ):
            args = argparse.Namespace(command="stats")
            tag_gardening.cmd_stats(args)

        output = json.loads(capsys.readouterr().out)
        expected_keys = {
            "total_memories", "total_tag_usages", "unique_tags",
            "singletons", "singleton_pct", "used_2_3", "used_4_10",
            "used_11_plus", "top_20", "memories_with_no_tags",
            "vocab_file_count", "orphaned_vocab", "missing_from_vocab",
        }
        assert set(output.keys()) == expected_keys
        assert output["total_memories"] == 6
        assert output["memories_with_no_tags"] == 1


# -------------------------------------------------------------------------
# Plural detection tests
# -------------------------------------------------------------------------

class TestPluralDetection:
    """Tests for find_plural_pairs()."""

    def test_finds_simple_plural(self) -> None:
        """Detects pipeline/pipelines pair."""
        tag_set = {"pipeline", "pipelines", "api"}
        counts = Counter({"pipeline": 10, "pipelines": 3, "api": 5})
        pairs = tag_gardening.find_plural_pairs(tag_set, counts)

        assert len(pairs) == 1
        assert pairs[0]["suggested_winner"] == "pipeline"
        assert pairs[0]["type"] == "plural"
        assert pairs[0]["confidence"] == "high"

    def test_finds_ies_plural(self) -> None:
        """Detects library/libraries pair."""
        tag_set = {"library", "libraries", "other"}
        counts = Counter({"library": 5, "libraries": 2, "other": 1})
        pairs = tag_gardening.find_plural_pairs(tag_set, counts)

        assert len(pairs) == 1
        assert pairs[0]["suggested_winner"] == "library"

    def test_finds_es_plural(self) -> None:
        """Detects process/processes pair (-ses ending)."""
        tag_set = {"process", "processes"}
        counts = Counter({"process": 8, "processes": 2})
        pairs = tag_gardening.find_plural_pairs(tag_set, counts)

        assert len(pairs) == 1
        assert pairs[0]["suggested_winner"] == "process"

    def test_excludes_false_positives(self) -> None:
        """Words in the exclusion set are not treated as plurals.

        Uses tags that DO end in 's' and whose stem IS in the tag set,
        so without the exclusion set they would produce false pairs.
        """
        # "focus" ends in 's', stem "focu" is in tag_set, but "focus"
        # is in PLURAL_EXCLUSIONS so it should be skipped.
        # "status" → "statu", same logic.
        tag_set = {"focus", "focu", "status", "statu", "series", "serie"}
        counts = Counter({t: 5 for t in tag_set})
        pairs = tag_gardening.find_plural_pairs(tag_set, counts)

        assert len(pairs) == 0

    def test_no_self_match(self) -> None:
        """A tag does not match itself."""
        tag_set = {"test"}
        counts = Counter({"test": 10})
        pairs = tag_gardening.find_plural_pairs(tag_set, counts)
        assert len(pairs) == 0

    def test_no_match_without_singular(self) -> None:
        """Plural without singular in tag set produces no pair."""
        tag_set = {"pipelines", "models"}
        counts = Counter({"pipelines": 5, "models": 3})
        pairs = tag_gardening.find_plural_pairs(tag_set, counts)
        assert len(pairs) == 0

    def test_sorted_by_combined_usage(self) -> None:
        """Results sorted by combined usage descending."""
        tag_set = {"pipeline", "pipelines", "model", "models"}
        counts = Counter({
            "pipeline": 100, "pipelines": 50,
            "model": 5, "models": 2,
        })
        pairs = tag_gardening.find_plural_pairs(tag_set, counts)
        assert len(pairs) == 2
        assert pairs[0]["combined_usage"] > pairs[1]["combined_usage"]


# -------------------------------------------------------------------------
# Levenshtein similarity tests
# -------------------------------------------------------------------------

class TestSimilarTags:
    """Tests for find_similar_tags()."""

    def test_finds_near_duplicates(self) -> None:
        """Tags differing by 1 character are detected."""
        tag_set = {"api-key", "api-keys", "database"}
        counts = Counter({"api-key": 10, "api-keys": 3, "database": 5})
        similar = tag_gardening.find_similar_tags(tag_set, counts)

        matched_pairs = {
            frozenset(t[0] for t in c["tags"])
            for c in similar
        }
        assert frozenset({"api-key", "api-keys"}) in matched_pairs

    def test_does_not_match_dissimilar(self) -> None:
        """Tags that are very different are not matched."""
        tag_set = {"api-key", "database", "architecture"}
        counts = Counter({t: 5 for t in tag_set})
        similar = tag_gardening.find_similar_tags(tag_set, counts)
        assert len(similar) == 0

    def test_higher_usage_wins(self) -> None:
        """Winner is the tag with higher usage count."""
        tag_set = {"api-key", "api-kye"}  # typo
        counts = Counter({"api-key": 20, "api-kye": 1})
        similar = tag_gardening.find_similar_tags(
            tag_set, counts, threshold=0.80,
        )
        assert len(similar) >= 1, "Expected at least one similar pair"
        assert similar[0]["suggested_winner"] == "api-key"


# -------------------------------------------------------------------------
# Prefix detection tests
# -------------------------------------------------------------------------

class TestPrefixPairs:
    """Tests for find_prefix_pairs()."""

    def test_finds_prefix_relationship(self) -> None:
        """Detects when one tag is a prefix of another."""
        tag_set = {"api", "api-integration"}
        counts = Counter({"api": 10, "api-integration": 5})
        prefixes = tag_gardening.find_prefix_pairs(tag_set, counts)

        assert len(prefixes) == 1
        tags = {t[0] for t in prefixes[0]["tags"]}
        assert tags == {"api", "api-integration"}

    def test_ignores_singletons(self) -> None:
        """Prefix pairs where both are singletons are ignored."""
        tag_set = {"api", "api-integration"}
        counts = Counter({"api": 1, "api-integration": 1})
        prefixes = tag_gardening.find_prefix_pairs(
            tag_set, counts, min_count=2,
        )
        assert len(prefixes) == 0

    def test_requires_hyphen_separator(self) -> None:
        """Only flags 'X' → 'X-suffix', not 'ap' → 'api'."""
        tag_set = {"ap", "api"}
        counts = Counter({"ap": 5, "api": 10})
        prefixes = tag_gardening.find_prefix_pairs(tag_set, counts)
        assert len(prefixes) == 0


# -------------------------------------------------------------------------
# Merge tests
# -------------------------------------------------------------------------

class TestMerge:
    """Tests for the merge operation."""

    def test_replaces_tags(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """Loser tags are replaced with winner tags."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        plan = [
            {"winner": "pipeline", "losers": ["pipelines"],
             "affected_memory_count": 1},
        ]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=False)
            tag_gardening.cmd_merge(args)

        # Verify JSONL
        memories = []
        with open(jsonl, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    memories.append(json.loads(line))

        # mem-002 had ["pipeline", "pipelines", "api"]
        # → should now be ["pipeline", "api"] (deduplicated)
        mem_002 = next(m for m in memories if m["id"] == "mem-002")
        assert "pipelines" not in mem_002["research_tags"]
        assert "pipeline" in mem_002["research_tags"]
        # No duplicates
        assert (
            len(mem_002["research_tags"])
            == len(set(mem_002["research_tags"]))
        )

    def test_preserves_line_count(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """JSONL line count is unchanged after merge."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)
        original_count = len(jsonl.read_text().splitlines())

        plan = [
            {"winner": "pipeline", "losers": ["pipelines"],
             "affected_memory_count": 1},
        ]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=False)
            tag_gardening.cmd_merge(args)

        new_count = len(jsonl.read_text().splitlines())
        assert new_count == original_count

    def test_valid_jsonl_after_merge(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """Every line in the merged file is valid JSON."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        plan = [
            {"winner": "pipeline", "losers": ["pipelines"],
             "affected_memory_count": 1},
        ]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=False)
            tag_gardening.cmd_merge(args)

        with open(jsonl, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        pytest.fail(f"Invalid JSON on line {i}")

    def test_dry_run_preserves_file(self, tmp_path: Path) -> None:
        """Dry run does not modify the JSONL file."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)
        original_content = jsonl.read_text()

        plan = [
            {"winner": "pipeline", "losers": ["pipelines"],
             "affected_memory_count": 1},
        ]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=True)
            tag_gardening.cmd_merge(args)

        assert jsonl.read_text() == original_content

    def test_vocabulary_updated(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """Vocabulary file has losers removed and winners present."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        plan = [
            {"winner": "pipeline", "losers": ["pipelines"],
             "affected_memory_count": 1},
        ]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=False)
            tag_gardening.cmd_merge(args)

        updated_vocab = {
            line.strip()
            for line in vocab.read_text().splitlines()
            if line.strip()
        }
        assert "pipelines" not in updated_vocab
        assert "pipeline" in updated_vocab


# -------------------------------------------------------------------------
# Orphans tests
# -------------------------------------------------------------------------

class TestOrphans:
    """Tests for orphan detection."""

    def test_detects_orphaned_vocab(self, tmp_path: Path) -> None:
        """Tags in vocab but not in JSONL are identified."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab, tags=[
            "api", "pipeline", "never-used-tag",
        ])

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
        ):
            memories = tag_gardening.load_memories()
            counts = tag_gardening.build_tag_counts(memories)
            used = set(counts.keys())
            loaded_vocab = tag_gardening.load_vocabulary()

        orphaned = loaded_vocab - used
        assert "never-used-tag" in orphaned

    def test_detects_missing_from_vocab(self, tmp_path: Path) -> None:
        """Tags in JSONL but not in vocab are identified."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        # Vocabulary missing "architecture"
        write_sample_vocab(vocab, tags=["api", "pipeline"])

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
        ):
            memories = tag_gardening.load_memories()
            counts = tag_gardening.build_tag_counts(memories)
            used = set(counts.keys())
            loaded_vocab = tag_gardening.load_vocabulary()

        missing = used - loaded_vocab
        assert "architecture" in missing


# -------------------------------------------------------------------------
# Edge case tests
# -------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_empty_jsonl(self, tmp_path: Path) -> None:
        """Empty JSONL file produces empty counts."""
        jsonl = tmp_path / "memories.jsonl"
        jsonl.write_text("", encoding="utf-8")

        with patch.object(tag_gardening, "MEMORIES_JSONL", jsonl):
            memories = tag_gardening.load_memories()

        assert len(memories) == 0
        assert len(tag_gardening.build_tag_counts(memories)) == 0

    def test_malformed_jsonl_lines_skipped(self, tmp_path: Path) -> None:
        """Malformed JSON lines are skipped without error."""
        jsonl = tmp_path / "memories.jsonl"
        jsonl.write_text(
            '{"research_tags": ["good"]}\n'
            'not valid json\n'
            '{"research_tags": ["also-good"]}\n',
            encoding="utf-8",
        )

        with patch.object(tag_gardening, "MEMORIES_JSONL", jsonl):
            memories = tag_gardening.load_memories()

        assert len(memories) == 2

    def test_duplicate_tags_in_single_memory(self) -> None:
        """Duplicate tags within one memory are counted per occurrence."""
        memories = [
            {"research_tags": ["api", "api", "testing"]},
        ]
        counts = tag_gardening.build_tag_counts(memories)
        # build_tag_counts counts each occurrence (not unique per memory)
        assert counts["api"] == 2


# -------------------------------------------------------------------------
# Additional coverage
# -------------------------------------------------------------------------

class TestMultiMerge:
    """Tests for multi-entry and conflicting merge plans."""

    def test_multi_entry_plan(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """Multiple merge groups in one plan are all applied."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        plan = [
            {"winner": "pipeline", "losers": ["pipelines"],
             "affected_memory_count": 1},
            {"winner": "api", "losers": ["api-integration"],
             "affected_memory_count": 1},
        ]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=False)
            tag_gardening.cmd_merge(args)

        memories = []
        with open(jsonl, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    memories.append(json.loads(line))

        # mem-002 had pipelines → pipeline (deduplicated)
        mem_002 = next(m for m in memories if m["id"] == "mem-002")
        assert "pipelines" not in mem_002["research_tags"]

        # mem-003 had api-integration → api (deduplicated)
        mem_003 = next(m for m in memories if m["id"] == "mem-003")
        assert "api-integration" not in mem_003["research_tags"]
        assert "api" in mem_003["research_tags"]

    def test_conflicting_losers_warns(
        self, tmp_path: Path, capsys,
    ) -> None:
        """A loser appearing in two entries triggers a warning."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        plan = [
            {"winner": "pipeline", "losers": ["pipelines"]},
            {"winner": "pipe", "losers": ["pipelines"]},  # conflict
        ]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=True)
            tag_gardening.cmd_merge(args)

        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "pipelines" in captured.err


class TestMergeWithTagsField:
    """Tests for merge operating on the fallback 'tags' field."""

    def test_merges_tags_field(
        self, tmp_path: Path, bypass_rewrite_guard: None,
    ) -> None:
        """Merge works on memories using 'tags' instead of 'research_tags'."""
        memories = [
            {"id": "m1", "tags": ["old-tag", "keep-tag"]},
        ]
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl, memories)
        write_sample_vocab(vocab, tags=["old-tag", "new-tag", "keep-tag"])

        plan = [{"winner": "new-tag", "losers": ["old-tag"]}]
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            args = argparse.Namespace(plan=str(plan_file), dry_run=False)
            tag_gardening.cmd_merge(args)

        with open(jsonl, "r", encoding="utf-8") as fh:
            mem = json.loads(fh.readline())

        assert "old-tag" not in mem["tags"]
        assert "new-tag" in mem["tags"]
        assert "keep-tag" in mem["tags"]


class TestSimilarOverlapRemoval:
    """Tests for overlap removal between detection stages."""

    def test_plurals_excluded_from_similar(self) -> None:
        """Pairs found as plurals are not repeated in similar results."""
        # "pipeline" / "pipelines" would match both plural detection
        # and Levenshtein similarity — should only appear once (as plural)
        tag_set = {"pipeline", "pipelines"}
        counts = Counter({"pipeline": 10, "pipelines": 3})

        plurals = tag_gardening.find_plural_pairs(tag_set, counts)
        similar = tag_gardening.find_similar_tags(
            tag_set, counts, threshold=0.80,
        )

        # Build the overlap filter (same logic as cmd_similar)
        plural_pairs = {
            frozenset(t[0] for t in group["tags"])
            for group in plurals
        }
        filtered = [
            c for c in similar
            if frozenset(t[0] for t in c["tags"]) not in plural_pairs
        ]

        assert len(plurals) == 1
        assert len(filtered) == 0


class TestOrphansClean:
    """Tests for the orphans --action clean path."""

    def test_clean_removes_orphaned_and_adds_missing(
        self, tmp_path: Path, bypass_rewrite_guard: None,
    ) -> None:
        """Clean action fixes vocabulary in both directions."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        # "orphan" is in vocab but unused; "architecture" is used but
        # missing from vocab
        write_sample_vocab(vocab, tags=["api", "pipeline", "orphan"])

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
        ):
            args = argparse.Namespace(action="clean")
            tag_gardening.cmd_orphans(args)

        updated = {
            line.strip()
            for line in vocab.read_text().splitlines()
            if line.strip()
        }
        assert "orphan" not in updated
        assert "architecture" in updated


class TestMergePlanValidation:
    """Tests for merge plan input validation."""

    def test_rejects_non_list(self, tmp_path: Path) -> None:
        """Plan file containing a JSON object (not array) is rejected."""
        plan_file = tmp_path / "plan.json"
        plan_file.write_text('{"winner": "x"}', encoding="utf-8")

        with pytest.raises(SystemExit):
            args = argparse.Namespace(
                plan=str(plan_file), dry_run=True,
            )
            tag_gardening.cmd_merge(args)

    def test_rejects_missing_keys(self, tmp_path: Path) -> None:
        """Plan entries missing required keys are rejected."""
        plan_file = tmp_path / "plan.json"
        plan_file.write_text('[{"winner": "x"}]', encoding="utf-8")

        with pytest.raises(SystemExit):
            args = argparse.Namespace(
                plan=str(plan_file), dry_run=True,
            )
            tag_gardening.cmd_merge(args)


# -------------------------------------------------------------------------
# Unicode line separators (audit 2026-09-08, finding A1)
# -------------------------------------------------------------------------

#: A Unicode LINE SEPARATOR — legal inside a JSON string, and a line break to
#: ``str.splitlines()`` but not to ``"\n"``-splitting or file iteration.
LINE_SEPARATOR = "\u2028"


class TestUnicodeLineSeparators:
    """A merge must not plant a raw line separator in the canonical."""

    def test_merge_keeps_separator_escaped(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """A rewritten record's U+2028 stays ``\\u2028`` on disk.

        Kills the mutation ``json.dumps(mem)`` ->
        ``json.dumps(mem, ensure_ascii=False)``: that writes the separator
        raw, and every reader that splits on Unicode line boundaries (the
        PostgreSQL sync cursor among them) then sees one line more than the
        file has.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        memories = [
            {
                "id": "mem-101",
                "content": f"Section one{LINE_SEPARATOR}section two.",
                "research_tags": ["pipelines", "api"],
            },
            {"id": "mem-102", "content": "Plain record.",
             "research_tags": ["api"]},
        ]
        write_sample_jsonl(jsonl, memories)
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        raw = jsonl.read_text(encoding="utf-8")
        assert LINE_SEPARATOR not in raw, "separator must stay escaped"
        assert raw.count("\n") == 2, "the file must still hold two records"
        rewritten = json.loads(raw.split("\n")[0])
        assert rewritten["content"] == f"Section one{LINE_SEPARATOR}section two."
        assert rewritten["research_tags"] == ["pipeline", "api"]


# -------------------------------------------------------------------------
# Bulk-rewrite guard wiring (audit 2026-09-08, findings A5 and B6)
# -------------------------------------------------------------------------


class TestGuardWiring:
    """Which merge paths may take the exclusive daily-sync lock."""

    @staticmethod
    def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
        """Write a corpus, a vocabulary, and a one-entry merge plan."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )
        return jsonl, vocab, plan_file

    def test_dry_run_does_not_invoke_the_guard(self, tmp_path: Path) -> None:
        """A preview must not contend for the daily-sync flock.

        Kills the mutation that calls ``ensure_safe_to_rewrite`` before the
        ``--dry-run`` branch: the stub here refuses the way the real guard
        refuses on a dirty tree, so the preview would exit 2.
        """
        jsonl, vocab, plan_file = self._fixture(tmp_path)

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise SystemExit(2)

        before = jsonl.read_bytes()
        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
            patch.object(tag_gardening, "ensure_safe_to_rewrite", refuse),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=True)
            )

        assert jsonl.read_bytes() == before

    def test_real_run_invokes_the_guard(
        self, tmp_path: Path, pg_recorder: list,
    ) -> None:
        """A mutating merge must take the guard before rewriting.

        Kills the mutation that deletes the ``ensure_safe_to_rewrite`` call
        from the real-run path.
        """
        jsonl, vocab, plan_file = self._fixture(tmp_path)
        calls: list[str] = []

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
            patch.object(
                tag_gardening, "ensure_safe_to_rewrite",
                lambda reason: calls.append(reason),
            ),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        assert len(calls) == 1
        assert "tag-gardening merge" in calls[0]


# -------------------------------------------------------------------------
# Vocabulary rewrites (audit 2026-09-08, findings A2 and A4)
# -------------------------------------------------------------------------

#: A vocabulary shaped like the live one: section headers, a blank line
#: between sections, and sorted tags underneath.
STRUCTURED_VOCAB = (
    "# Infrastructure\n"
    "api\n"
    "pipeline\n"
    "pipelines\n"
    "\n"
    "# Fieldwork\n"
    "orphaned-tag\n"
    "validation\n"
)

#: Holds a shared lock on a file, the way the extraction hook does while it
#: appends, and reports readiness on stdout so the test need not sleep.
_SHARED_LOCK_HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_SH)
print("locked", flush=True)
time.sleep(30)
"""


class TestVocabularyRewrite:
    """The vocabulary is a protected file; both writers must treat it so."""

    def test_merge_preserves_comments_and_blank_lines(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """Section headers and the blank line keep their positions.

        Kills the mutation that rewrites the file as a flat sorted list:
        that drops all eight section headers from the live vocabulary.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        vocab.write_text(STRUCTURED_VOCAB, encoding="utf-8")
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        # Retiring "pipelines" removes only its own line; the two headers
        # and the blank line still sit exactly where they were, each still
        # heading its own section.
        assert vocab.read_text(encoding="utf-8") == (
            "# Infrastructure\n"
            "api\n"
            "pipeline\n"
            "\n"
            "# Fieldwork\n"
            "orphaned-tag\n"
            "validation\n"
        )

    def test_orphans_clean_preserves_comments_and_blank_lines(
        self, tmp_path: Path, bypass_rewrite_guard: None,
    ) -> None:
        """``orphans --action clean`` keeps the file's structure too.

        Kills the mutation that replaces the structured rewrite with a bare
        ``write_text`` of a sorted tag list.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        vocab.write_text(STRUCTURED_VOCAB, encoding="utf-8")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
        ):
            tag_gardening.cmd_orphans(argparse.Namespace(action="clean"))

        # The unused "orphaned-tag" line goes; the tags the corpus uses but
        # the file lacks are appended, sorted, after the existing content.
        # Both headers and the blank line survive in place.
        assert vocab.read_text(encoding="utf-8") == (
            "# Infrastructure\n"
            "api\n"
            "pipeline\n"
            "pipelines\n"
            "\n"
            "# Fieldwork\n"
            "validation\n"
            "api-integration\n"
            "architecture\n"
            "data-quality\n"
            "singleton-tag\n"
            "testing\n"
        )

    def test_orphans_clean_invokes_the_guard(self, tmp_path: Path) -> None:
        """``clean`` mutates a protected file, so it must take the guard.

        Kills the mutation that deletes the ``ensure_safe_to_rewrite`` call
        from the clean branch.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)
        calls: list[str] = []

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(
                tag_gardening, "ensure_safe_to_rewrite",
                lambda reason: calls.append(reason),
            ),
        ):
            tag_gardening.cmd_orphans(argparse.Namespace(action="clean"))

        assert calls == ["tag-gardening orphans --action clean"]

    def test_orphans_list_does_not_invoke_the_guard(
        self, tmp_path: Path,
    ) -> None:
        """``list`` is read-only and must never touch the daily-sync lock."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise SystemExit(2)

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "ensure_safe_to_rewrite", refuse),
        ):
            tag_gardening.cmd_orphans(argparse.Namespace(action="list"))

    def test_orphans_clean_waits_for_a_shared_lock_holder(
        self, tmp_path: Path, bypass_rewrite_guard: None,
    ) -> None:
        """A concurrent ``LOCK_SH`` holder blocks the clean rewrite.

        Uses the real lock helper in a separate process — the extraction
        hook's append pattern. Kills the mutation that drops
        ``lock_jsonl_for_rewrite`` from the clean branch: without it the
        rewrite completes immediately and the append is lost.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        vocab.write_text(STRUCTURED_VOCAB, encoding="utf-8")

        holder = subprocess.Popen(
            [sys.executable, "-c", _SHARED_LOCK_HOLDER, str(vocab)],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            assert holder.stdout.readline().strip() == "locked"
            finished = threading.Event()

            def run_clean() -> None:
                with (
                    patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
                    patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
                ):
                    tag_gardening.cmd_orphans(
                        argparse.Namespace(action="clean")
                    )
                finished.set()

            worker = threading.Thread(target=run_clean, daemon=True)
            worker.start()
            assert not finished.wait(0.5), (
                "the rewrite proceeded while another process held LOCK_SH"
            )
        finally:
            holder.terminate()
            holder.wait(timeout=10)
            if holder.stdout is not None:
                holder.stdout.close()

        assert finished.wait(10), "the rewrite must proceed once unlocked"
        worker.join(timeout=10)


# -------------------------------------------------------------------------
# PostgreSQL reconciliation (audit 2026-09-08, finding A8; B1's class)
# -------------------------------------------------------------------------


#: The schema version the guard expects, read from the module it guards so a
#: bump does not silently turn these tests into no-ops.
SCHEMA_VERSION = importlib.import_module(
    "_schema_version"
).EXPECTED_SCHEMA_VERSION


class FakeCursor:
    """Records the SQL text and parameters it was actually handed."""

    def __init__(self, ledger: list[tuple[str, tuple]]) -> None:
        self.ledger = ledger
        self.rowcount = 1

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.ledger.append((sql, params))

    def fetchone(self) -> tuple:
        return (SCHEMA_VERSION,)


class FakeConnection:
    """A psycopg2-shaped connection that commits via the context manager."""

    def __init__(self, ledger: list[tuple[str, tuple]]) -> None:
        self.ledger = ledger
        self.entered = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.ledger)

    def __enter__(self) -> FakeConnection:
        self.entered += 1
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def close(self) -> None:
        self.closed = True




class TestReconcilePostgres:
    """The surgical UPDATE a merge must issue, and what it does on failure."""

    def test_update_targets_one_id_with_the_merged_tags(self) -> None:
        """The real SQL string is executed, keyed on id, in parameter order.

        Kills the mutations ``WHERE id = %s`` -> ``WHERE id != %s`` and a
        swapped parameter order: the fake cursor records what it was handed,
        rather than the test comparing a constant with itself.
        """
        ledger: list[tuple[str, tuple]] = []
        conn = FakeConnection(ledger)

        tag_gardening.reconcile_postgres(
            [("mem-001", ["pipeline", "api"]), ("mem-004", ["api"])],
            connect=lambda: conn,
        )

        updates = [(sql, params) for sql, params in ledger
                   if sql.startswith("UPDATE")]
        assert len(updates) == 2
        sql, params = updates[0]
        assert sql == "UPDATE memories SET research_tags = %s WHERE id = %s"
        assert params == (["pipeline", "api"], "mem-001")
        assert updates[1][1] == (["api"], "mem-004")
        assert conn.entered == 1, "the UPDATEs must run inside `with conn`"
        assert conn.closed

    def test_nothing_to_reconcile_opens_no_connection(self) -> None:
        """An empty update list must not connect at all."""

        def explode() -> None:
            raise AssertionError("connected with nothing to do")

        tag_gardening.reconcile_postgres([], connect=explode)

    def test_unreachable_server_reports_the_rebuild_remedy(
        self, capsys: pytest.CaptureFixture,
    ) -> None:
        """A connection failure exits non-zero naming a full rebuild.

        Kills the mutation that restores the old "Run sync-to-postgres.py"
        advice: that script is INSERT ... ON CONFLICT DO NOTHING and will
        never propagate an edit to an existing row.
        """

        def refuse() -> None:
            raise OSError("connection refused")

        with pytest.raises(SystemExit) as excinfo:
            tag_gardening.reconcile_postgres(
                [("mem-001", ["api"])], connect=refuse,
            )

        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "rebuild-postgres.py" in err
        assert "sync-to-postgres.py" not in err

    def test_failed_update_reports_the_rebuild_remedy(
        self, capsys: pytest.CaptureFixture,
    ) -> None:
        """A query failure is reported the same way, after the JSONL is safe."""

        class ExplodingCursor(FakeCursor):
            def execute(self, sql: str, params: tuple | None = None) -> None:
                if sql.startswith("UPDATE"):
                    raise RuntimeError("column research_tags does not exist")
                super().execute(sql, params)

        class ExplodingConnection(FakeConnection):
            def cursor(self) -> FakeCursor:
                return ExplodingCursor(self.ledger)

        with pytest.raises(SystemExit) as excinfo:
            tag_gardening.reconcile_postgres(
                [("mem-001", ["api"])],
                connect=lambda: ExplodingConnection([]),
            )

        assert excinfo.value.code == 1
        assert "rebuild-postgres.py" in capsys.readouterr().err

    def test_merge_passes_only_research_tags_rows_to_postgres(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """A merge hands PG exactly the ids whose mirror column changed.

        Kills the mutation that deletes the reconcile call from cmd_merge,
        and the one that also queues records whose tags live in the ``tags``
        field (schema.sql has no such column, so PG has nothing to update).
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl, [
            {"id": "mem-201", "content": "Research-tagged record.",
             "research_tags": ["pipelines", "api"]},
            {"id": "mem-202", "content": "Legacy tags field.",
             "tags": ["pipelines"]},
            {"id": "mem-203", "content": "Untouched.",
             "research_tags": ["api"]},
        ])
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        assert pg_recorder == [[("mem-201", ["pipeline", "api"])]]

    def test_dry_run_reconciles_nothing(
        self, tmp_path: Path, pg_recorder: list,
    ) -> None:
        """A preview must not touch PostgreSQL either."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=True)
            )

        assert pg_recorder == []


# -------------------------------------------------------------------------
# Case handling (audit 2026-09-08, findings A12, B16 and B17)
# -------------------------------------------------------------------------


class TestCaseHandling:
    """Tags are compared case-insensitively; the plan must be too."""

    def test_mixed_case_loser_is_actually_retired(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """A plan naming "API-Integration" retires "api-integration".

        Kills the mutation ``replacements[loser.lower()]`` ->
        ``replacements[loser]``: the rewrite loop matches on ``tag.lower()``,
        so an upper-cased loser replaced nothing while the run still
        reported "Tags retired: 1".
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl, [
            {"id": "mem-301", "content": "Mixed-case tag in the record.",
             "research_tags": ["API-Integration", "kiln"]},
        ])
        write_sample_vocab(vocab, ["api", "api-integration", "kiln"])
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "api", "losers": ["API-Integration"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        written = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert written["research_tags"] == ["api", "kiln"]
        assert pg_recorder == [[("mem-301", ["api", "kiln"])]]

    def test_mixed_case_record_tag_matches_a_lower_case_plan(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """A record's "Pipelines" is retired by a plan naming "pipelines".

        Kills the mutation that removes ``tag.lower()`` from the rewrite
        loop's comparison.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl, [
            {"id": "mem-302", "content": "Upper-cased tag in the record.",
             "research_tags": ["Pipelines"]},
        ])
        write_sample_vocab(vocab, ["pipeline", "pipelines"])
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        written = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert written["research_tags"] == ["pipeline"]

    def test_research_tags_wins_over_tags_when_both_are_present(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """``research_tags`` is authoritative even when empty.

        Kills the mutation that inverts ``_get_tags``'s field precedence:
        no fixture carried both fields before, so the inversion was silent.
        """
        both = {"id": "mem-303", "content": "Carries both tag fields.",
                "research_tags": ["pipelines"], "tags": ["kiln"]}
        assert tag_gardening._get_tags(both) == ["pipelines"]
        empty_research = {"id": "mem-304", "content": "Empty research_tags.",
                          "research_tags": [], "tags": ["kiln"]}
        assert tag_gardening._get_tags(empty_research) == []

        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl, [both])
        write_sample_vocab(vocab, ["pipeline", "pipelines", "kiln"])
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        written = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert written["research_tags"] == ["pipeline"]
        assert written["tags"] == ["kiln"], "the legacy field is untouched"


# -------------------------------------------------------------------------
# Durability and the merge log (audit 2026-09-08, findings A15, A16, B19)
# -------------------------------------------------------------------------


class TestMergeDurabilityAndLog:
    """The corpus rewrite is fsynced, and the log entry is UTC ISO."""

    @staticmethod
    def _run_merge(tmp_path: Path) -> Path:
        """Run a one-entry merge in ``tmp_path``; return the log directory."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        log_dir = tmp_path / "logs"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )
        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", log_dir),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )
        return log_dir

    def test_both_rewrites_are_fsynced_before_the_rename(
        self, tmp_path: Path, pg_recorder: list,
        monkeypatch: pytest.MonkeyPatch, bypass_rewrite_guard: None,
    ) -> None:
        """The corpus and the vocabulary reach disk before they are renamed.

        Kills the mutation that drops ``os.fsync`` from either rewrite: the
        rename would then be durable while the bytes behind it were not.
        """
        events: list[str] = []
        real_fsync = os.fsync
        real_rename = os.rename

        def recording_fsync(fd: int) -> None:
            events.append("fsync")
            return real_fsync(fd)

        def recording_rename(src, dst, **kwargs):
            events.append(f"rename:{Path(dst).name}")
            return real_rename(src, dst, **kwargs)

        monkeypatch.setattr(os, "fsync", recording_fsync)
        monkeypatch.setattr(os, "rename", recording_rename)

        self._run_merge(tmp_path)

        assert events[:2] == ["fsync", "rename:memories.jsonl"]
        assert events[2:] == ["fsync", "rename:tag-vocabulary.txt"]

    def test_merge_log_entry_is_utc_iso(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """The log stamp parses as an aware UTC instant.

        Kills the mutation ``datetime.now(timezone.utc).isoformat()`` ->
        ``datetime.now().strftime("%Y-%m-%d %H:%M:%S")``: a naive local
        stamp cannot be lined up with any other log in the system.
        """
        log_dir = self._run_merge(tmp_path)

        entry = (log_dir / "tag-gardening.log").read_text(encoding="utf-8")
        stamp, _, rest = entry.partition(" MERGE: ")
        parsed = datetime.fromisoformat(stamp)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)
        assert rest.startswith("1 groups, 1 memories, 1 replacements")


# -------------------------------------------------------------------------
# Merge preservation (audit 2026-09-08, finding B5)
# -------------------------------------------------------------------------


class TestMergePreservesEverythingElse:
    """What a merge must leave exactly as it found it."""

    def test_malformed_and_blank_lines_survive_verbatim(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """A line the merge cannot parse is written back byte for byte.

        Kills the mutation that drops ``lines.append(line)`` from the
        ``JSONDecodeError`` branch: the malformed line would be deleted from
        the canonical, shrinking the corpus behind the sync cursor.
        archive-memories has the equivalent test; the merge had none.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        jsonl.write_text(
            json.dumps({"id": "mem-401", "content": "Tagged.",
                        "research_tags": ["pipelines"]}) + "\n"
            + "\n"
            + "{truncated record, no closing brace\n"
            + json.dumps({"id": "mem-402", "content": "Untagged."}) + "\n",
            encoding="utf-8",
        )
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        lines = jsonl.read_text(encoding="utf-8").split("\n")[:-1]
        assert len(lines) == 4, "the merge changed the corpus line count"
        assert lines[1] == "", "the blank line was not preserved"
        assert lines[2] == "{truncated record, no closing brace"

    def test_untouched_records_are_byte_identical(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """A record with no retired tag is not re-serialised.

        Kills a mutation that re-dumps every record: key order, spacing, and
        any field the merge does not understand would silently change, and
        the diff would name every line in the corpus.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        # Deliberately non-canonical spacing and key order: a re-dump would
        # normalise both.
        untouched = '{"content":"Left alone.",  "id":"mem-403", "research_tags":["api"]}'
        jsonl.write_text(
            json.dumps({"id": "mem-404", "content": "Rewritten.",
                        "research_tags": ["pipelines"]}) + "\n"
            + untouched + "\n",
            encoding="utf-8",
        )
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
        ):
            tag_gardening.cmd_merge(
                argparse.Namespace(plan=str(plan_file), dry_run=False)
            )

        lines = jsonl.read_text(encoding="utf-8").split("\n")[:-1]
        assert lines[1] == untouched, "an untouched record was re-serialised"


class TestMergeHoldsTheCorpusLock:
    """The merge's read-modify-rename window must exclude the appender."""

    def test_merge_waits_for_a_shared_lock_holder(
        self, tmp_path: Path, pg_recorder: list, bypass_rewrite_guard: None,
    ) -> None:
        """A concurrent ``LOCK_SH`` on memories.jsonl blocks the rewrite.

        Uses the real lock helper from a second process — the extraction
        hook's append pattern. Kills the mutation that replaces
        ``lock_jsonl_for_rewrite(MEMORIES_JSONL)`` with a nullcontext: an
        append landing between the read and the rename is then overwritten.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        write_sample_vocab(vocab)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(
            json.dumps([{"winner": "pipeline", "losers": ["pipelines"]}]),
            encoding="utf-8",
        )

        holder = subprocess.Popen(
            [sys.executable, "-c", _SHARED_LOCK_HOLDER, str(jsonl)],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            assert holder.stdout.readline().strip() == "locked"
            finished = threading.Event()

            def run_merge() -> None:
                with (
                    patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
                    patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
                    patch.object(tag_gardening, "LOG_DIR", tmp_path / "logs"),
                ):
                    tag_gardening.cmd_merge(
                        argparse.Namespace(plan=str(plan_file), dry_run=False)
                    )
                finished.set()

            worker = threading.Thread(target=run_merge, daemon=True)
            worker.start()
            assert not finished.wait(0.5), (
                "the merge rewrote the corpus while another process held "
                "LOCK_SH on it"
            )
        finally:
            holder.terminate()
            holder.wait(timeout=10)
            if holder.stdout is not None:
                holder.stdout.close()

        assert finished.wait(10), "the merge must proceed once unlocked"
        worker.join(timeout=10)


# -------------------------------------------------------------------------
# The in-lock re-read (audit 2026-09-08, round 4a-2, finding M4)
# -------------------------------------------------------------------------

#: Takes LOCK_SH on the vocabulary the way the extraction hook does, waits
#: for a go signal on stdin, appends a tag, then exits (releasing the lock).
#: The signal makes the interleaving deterministic: the appending process is
#: holding the lock before the rewrite starts waiting for it, and appends
#: while the rewrite is blocked.
_APPENDING_LOCK_HOLDER = """
import fcntl, os, sys
path = sys.argv[1]
tag = sys.argv[2]
fd = os.open(path, os.O_RDWR | os.O_APPEND)
fcntl.flock(fd, fcntl.LOCK_SH)
print("locked", flush=True)
sys.stdin.readline()
os.write(fd, (tag + "\\n").encode("utf-8"))
os.fsync(fd)
fcntl.flock(fd, fcntl.LOCK_UN)
os.close(fd)
print("appended", flush=True)
"""


class TestOrphansCleanRereadsInsideTheLock:
    """The counts are taken without the lock; the rewrite must not use them."""

    def test_a_tag_appended_while_the_lock_is_awaited_survives(
        self, tmp_path: Path,
    ) -> None:
        """An extraction-hook append landing during the wait is not dropped.

        Kills the mutation ``vocab_now = load_vocabulary()`` ->
        ``vocab_now = vocab``: the pre-lock snapshot does not contain the
        appended tag, so the rewrite would silently delete it -- the exact
        lost-append this lock exists to prevent.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        vocab.write_text(STRUCTURED_VOCAB, encoding="utf-8")
        appended_tag = "kiln-firing-log"
        assert appended_tag not in vocab.read_text(encoding="utf-8")

        holder = subprocess.Popen(
            [sys.executable, "-c", _APPENDING_LOCK_HOLDER,
             str(vocab), appended_tag],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        try:
            assert holder.stdout.readline().strip() == "locked"
            finished = threading.Event()

            def run_clean() -> None:
                with (
                    patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
                    patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
                    patch.object(
                        tag_gardening, "ensure_safe_to_rewrite",
                        lambda reason: None),
                ):
                    tag_gardening.cmd_orphans(
                        argparse.Namespace(action="clean"))
                finished.set()

            worker = threading.Thread(target=run_clean, daemon=True)
            worker.start()
            # The rewrite is now blocked on LOCK_EX; let the holder append.
            assert not finished.wait(0.5), "the rewrite did not wait"
            holder.stdin.write("go\n")
            holder.stdin.flush()
            assert holder.stdout.readline().strip() == "appended"
        finally:
            holder.terminate()
            holder.wait(timeout=10)
            for stream in (holder.stdin, holder.stdout):
                if stream is not None:
                    stream.close()

        assert finished.wait(10), "the rewrite never completed"
        worker.join(timeout=10)

        written = vocab.read_text(encoding="utf-8").split("\n")
        assert appended_tag in written, (
            "a tag appended while the rewrite waited for the lock was lost: "
            "the rewrite used its pre-lock snapshot"
        )


# -------------------------------------------------------------------------
# A missing vocabulary (audit 2026-09-08, round 4a-2, finding M6)
# -------------------------------------------------------------------------


class TestOrphansCleanWithNoVocabulary:
    """An absent vocabulary is a refusal, not a traceback under the lock."""

    def test_clean_refuses_before_taking_the_guard(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """No vocabulary means no rewrite, and no daily-sync lock taken.

        Kills the mutation that removes the existence check: the run then
        reaches lock_jsonl_for_rewrite, which opens the target without
        O_CREAT by design, and dies with a bare FileNotFoundError -- with
        the exclusive daily-sync flock already held.
        """
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)
        assert not vocab.exists()

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "the guard was taken before the vocabulary was checked")

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
            patch.object(tag_gardening, "ensure_safe_to_rewrite", refuse),
            pytest.raises(SystemExit) as excinfo,
        ):
            tag_gardening.cmd_orphans(argparse.Namespace(action="clean"))

        assert excinfo.value.code == 1
        assert not vocab.exists(), "the refusal must not create the file"
        assert "does not exist" in capsys.readouterr().err

    def test_list_with_no_vocabulary_still_reports(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """The read-only action is unaffected: everything reads as missing."""
        jsonl = tmp_path / "memories.jsonl"
        vocab = tmp_path / "tag-vocabulary.txt"
        write_sample_jsonl(jsonl)

        with (
            patch.object(tag_gardening, "MEMORIES_JSONL", jsonl),
            patch.object(tag_gardening, "VOCABULARY_FILE", vocab),
        ):
            tag_gardening.cmd_orphans(argparse.Namespace(action="list"))

        out = capsys.readouterr().out
        assert "Tags in vocabulary but unused in JSONL: 0" in out
        assert not vocab.exists()
