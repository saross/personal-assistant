"""Tests for scripts/tag-gardening.py."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import importlib

tag_gardening = importlib.import_module("tag-gardening")


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------

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
            fh.write(json.dumps(mem, ensure_ascii=False) + "\n")


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

    def test_replaces_tags(self, tmp_path: Path) -> None:
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

    def test_preserves_line_count(self, tmp_path: Path) -> None:
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

    def test_valid_jsonl_after_merge(self, tmp_path: Path) -> None:
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

    def test_vocabulary_updated(self, tmp_path: Path) -> None:
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

    def test_multi_entry_plan(self, tmp_path: Path) -> None:
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

    def test_merges_tags_field(self, tmp_path: Path) -> None:
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
        self, tmp_path: Path,
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
