"""
Tests for scripts/archive-memories.py — the item-13 category-retention sweep.

Covers the pure planning logic (``should_archive``, ``partition_corpus``,
``effective_windows``, ``parse_iso``, ``_reference_time``). The I/O paths
(corpus rewrite, bulk-rewrite guard, git commit, postgres update) are not
exercised here — they reuse already-tested modules (``_bulk_rewrite_guard``,
``_schema_version``).
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load(name, rel):
    path = Path(__file__).parent.parent / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


am = _load("archive_memories", "scripts/archive-memories.py")

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
# A representative ephemeral window set (mirrors the signed-off policy).
WINDOWS = am.effective_windows({
    "progress": 30, "context": 30, "waiting_for": 14, "commitment": 30,
    "gotcha": 180, "pattern": 180, "decision": None,
})


def _days_ago(n: int) -> str:
    """ISO timestamp n days before NOW (aware UTC)."""
    return (NOW.replace(hour=0) - timedelta(days=n)).isoformat()


def _rec(category, created_days_ago, **extra):
    r = {"id": f"id-{category}-{created_days_ago}", "category": category,
         "created_at": _days_ago(created_days_ago)}
    r.update(extra)
    return r


class TestParseIso:
    def test_z_suffix(self):
        assert am.parse_iso("2026-06-01T00:00:00Z").tzinfo is not None

    def test_naive_assumed_utc(self):
        dt = am.parse_iso("2026-06-01T00:00:00")
        assert dt.tzinfo == timezone.utc

    def test_none_and_garbage(self):
        assert am.parse_iso(None) is None
        assert am.parse_iso("not-a-date") is None


class TestReferenceTime:
    def test_standard_uses_created_at(self):
        rec = {"category": "progress", "created_at": "C", "deadline_at": "D"}
        assert am._reference_time(rec) == "C"

    def test_commitment_prefers_deadline(self):
        rec = {"category": "commitment", "created_at": "C", "deadline_at": "D"}
        assert am._reference_time(rec) == "D"

    def test_commitment_falls_back_to_created(self):
        rec = {"category": "commitment", "created_at": "C"}
        assert am._reference_time(rec) == "C"


class TestEffectiveWindows:
    def test_gotcha_pattern_forced_permanent(self):
        w = am.effective_windows({"gotcha": 180, "pattern": 180, "progress": 30})
        assert w["gotcha"] is None
        assert w["pattern"] is None
        assert w["progress"] == 30

    def test_does_not_mutate_input(self):
        # The module-level WINDOWS is shared across tests; effective_windows
        # must copy, not mutate its argument.
        src = {"gotcha": 180, "progress": 30}
        am.effective_windows(src)
        assert src == {"gotcha": 180, "progress": 30}

    def test_override_added_when_category_absent(self):
        # pattern not in the input dict is still forced permanent.
        w = am.effective_windows({"progress": 30})
        assert w["pattern"] is None and w["gotcha"] is None


class TestShouldArchive:
    def test_permanent_category_never_archives(self):
        assert am.should_archive(_rec("decision", 9999), WINDOWS, NOW) is False

    def test_progress_past_window_archives(self):
        assert am.should_archive(_rec("progress", 45), WINDOWS, NOW) is True

    def test_progress_within_window_kept(self):
        assert am.should_archive(_rec("progress", 10), WINDOWS, NOW) is False

    def test_boundary_is_strict(self):
        # age exactly == window → NOT archived (matches apply-decay's strict >).
        assert am.should_archive(_rec("progress", 30), WINDOWS, NOW) is False
        assert am.should_archive(_rec("progress", 31), WINDOWS, NOW) is True

    def test_fractional_age_past_window_archives(self):
        # A record 30d 12h old is past a 30d window (PG decays it via the
        # fractional interval); the truncated-.days bug would wrongly keep it.
        rec = {"id": "x", "category": "progress",
               "created_at": (NOW - timedelta(days=30, hours=12)).isoformat()}
        assert am.should_archive(rec, WINDOWS, NOW) is True

    def test_fractional_age_within_window_kept(self):
        rec = {"id": "x", "category": "progress",
               "created_at": (NOW - timedelta(days=29, hours=23)).isoformat()}
        assert am.should_archive(rec, WINDOWS, NOW) is False

    def test_commitment_ages_from_deadline(self):
        # created recently, but deadline 40 days past → archived on window 30.
        rec = _rec("commitment", 5, deadline_at=_days_ago(40))
        assert am.should_archive(rec, WINDOWS, NOW) is True

    def test_commitment_future_deadline_kept(self):
        rec = _rec("commitment", 200, deadline_at=_days_ago(-10))  # 10d in future
        assert am.should_archive(rec, WINDOWS, NOW) is False

    def test_gotcha_override_keeps_old_record(self):
        # 200 days old but gotcha is forced permanent by the override.
        assert am.should_archive(_rec("gotcha", 200), WINDOWS, NOW) is False

    def test_unparseable_timestamp_is_kept(self):
        rec = {"id": "x", "category": "progress", "created_at": "garbage"}
        assert am.should_archive(rec, WINDOWS, NOW) is False

    def test_missing_timestamp_is_kept(self):
        assert am.should_archive({"id": "x", "category": "progress"},
                                 WINDOWS, NOW) is False

    def test_unknown_category_is_kept(self):
        assert am.should_archive(_rec("mystery", 9999), WINDOWS, NOW) is False


class TestPartitionCorpus:
    def _lines(self, records):
        return [json.dumps(r) + "\n" for r in records]

    def test_splits_and_counts(self):
        records = [
            _rec("progress", 45),   # archive
            _rec("progress", 5),    # keep (young)
            _rec("decision", 999),  # keep (permanent)
            _rec("context", 60),    # archive
        ]
        lines = self._lines(records)
        kept, archived, counts = am.partition_corpus(lines, WINDOWS, NOW)
        assert len(archived) == 2
        assert len(kept) == 2
        assert counts == {"progress": 1, "context": 1}

    def test_only_categories_filter(self):
        records = [_rec("progress", 45), _rec("context", 60)]
        lines = self._lines(records)
        kept, archived, counts = am.partition_corpus(
            lines, WINDOWS, NOW, only_categories=frozenset({"progress"}))
        # context is past its window but out of scope → kept.
        assert [a["record"]["category"] for a in archived] == ["progress"]
        assert any("context" in k for k in kept)

    def test_verbatim_lines_preserved(self):
        # An archived line is preserved byte-for-byte (incl. exotic spacing).
        raw = json.dumps(_rec("progress", 45)) + "\n"
        weird = raw.replace(", ", ",   ")  # extra whitespace, still valid JSON
        kept, archived, counts = am.partition_corpus([weird], WINDOWS, NOW)
        assert len(archived) == 1
        assert archived[0]["raw"] == weird

    def test_blank_and_unparseable_lines_kept(self):
        lines = ["\n", "not json\n", json.dumps(_rec("progress", 45)) + "\n"]
        kept, archived, counts = am.partition_corpus(lines, WINDOWS, NOW)
        assert "\n" in kept
        assert "not json\n" in kept
        assert len(archived) == 1

    def test_every_line_lands_in_exactly_one_bucket(self):
        records = [_rec("progress", 45), _rec("decision", 999),
                   _rec("context", 60), _rec("progress", 5)]
        lines = self._lines(records) + ["\n", "junk\n"]
        kept, archived, counts = am.partition_corpus(lines, WINDOWS, NOW)
        # No record dropped or duplicated: kept + archived == input.
        assert len(kept) + len(archived) == len(lines)

    def test_empty_only_categories_archives_nothing(self):
        records = [_rec("progress", 45), _rec("context", 60)]
        lines = self._lines(records)
        kept, archived, counts = am.partition_corpus(
            lines, WINDOWS, NOW, only_categories=frozenset())
        assert archived == []
        assert len(kept) == 2
        assert counts == {}

    def test_counts_accumulate_per_category(self):
        records = [_rec("progress", 40), _rec("progress", 50),
                   _rec("progress", 60)]
        # distinct ids so they are distinct records
        for i, r in enumerate(records):
            r["id"] = f"p{i}"
        kept, archived, counts = am.partition_corpus(
            self._lines(records), WINDOWS, NOW)
        assert counts["progress"] == 3


class TestPartitionIds:
    def test_missing_partition_is_empty_set(self, tmp_path):
        assert am._partition_ids(tmp_path / "nope.jsonl") == set()

    def test_reads_ids_skipping_blank_and_garbage(self, tmp_path):
        p = tmp_path / "part.jsonl"
        p.write_text(
            json.dumps({"id": "a", "category": "progress"}) + "\n"
            + "\n"                       # blank
            + "not json\n"               # unparseable
            + json.dumps({"category": "progress"}) + "\n"  # id-less
            + json.dumps({"id": "b"}) + "\n",
            encoding="utf-8",
        )
        assert am._partition_ids(p) == {"a", "b"}


# ===========================================================================
# apply_archive — the write path
#
# Added by audit round two (2026-09-08), findings S8/C4 (apply_archive was
# untested: evicting without archiving, or archiving without evicting, passed
# the whole suite), S15 (the daily-sync flock was released before the commit),
# S16 (the commit carried no pathspec), M3 (the write paths went through
# module globals, so a naive test could append to the REAL cold archive), and
# M5 (fixtures did not match production record shapes).
#
# Everything here runs against a throwaway corpus and a throwaway archive
# directory under tmp_path; the module-level CORPUS / ARCHIVE_DIR constants
# are never used, because every write path now takes the directory as a
# parameter.
# ===========================================================================

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import importlib  # noqa: E402

guard = importlib.import_module("_bulk_rewrite_guard")


def _production_record(category: str, created_days_ago: int, **extra) -> dict:
    """Build a memory record with the field set a REAL record carries.

    The field list is taken from the writer — ``hooks/extraction-hook.py``
    (the ``record = {...}`` literal plus the optional fields appended after
    it) — not from the older ``conftest.sample_memories`` fixture, which
    carries only ten of them (audit finding M5). A partition round-trip that
    only ever sees ten-field records cannot catch a write path that drops the
    fields the corpus actually holds.
    """
    record = {
        "id": f"2026-06-01-{category}-{created_days_ago}",
        "session_id": "11111111-2222-3333-4444-555555555555",
        "project": "-home-shawn-personal-assistant",
        "source": "extraction",
        "category": category,
        "content": f"A {category} record captured {created_days_ago} days ago.",
        "confidence": "high",
        "research_tags": ["memory-system", "archival"],
        "source_context": "Session transcript, tail of the window",
        "created_at": _days_ago(created_days_ago),
        "licence": None,
        "extractor_model_id": "claude-haiku-4-5-20251001",
        "source_message_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "summary": f"{category} summary",
        "why": "Because the write path must preserve every field verbatim.",
        "how_to_apply": "Only relevant to guidance categories; harmless here.",
    }
    record.update(extra)
    return record


def _write_corpus(corpus: Path, records: list[dict]) -> None:
    """Write records to *corpus* as JSONL, creating parent directories."""
    corpus.parent.mkdir(parents=True, exist_ok=True)
    corpus.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


def _ids_in(path: Path) -> list[str]:
    """Ids of every JSON record in a JSONL file (empty list if absent)."""
    if not path.exists():
        return []
    return [json.loads(line)["id"]
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture()
def apply_env(tmp_path, monkeypatch):
    """A throwaway corpus + archive, with the bulk guard's git probes stubbed.

    The guard's *lock* is real (an flock on a tmp lock file) so the lock
    ordering can be asserted; only the three git-state probes and the config
    path are replaced, because they interrogate the live data submodule.
    """
    monkeypatch.setattr(guard, "LOCK_FILE", tmp_path / "daily-sync.lock")
    monkeypatch.setattr(guard, "CONFIG_FILE", tmp_path / "no-such-config.json")
    monkeypatch.setattr(guard, "_fetch_origin", lambda: True)
    monkeypatch.setattr(guard, "_head_matches_origin", lambda: True)
    monkeypatch.setattr(guard, "_working_tree_clean_on", lambda files: True)
    data_dir = tmp_path / "data"
    corpus = data_dir / "memories" / "memories.jsonl"
    archive_dir = data_dir / "memories" / "archive"
    return corpus, archive_dir, tmp_path / "daily-sync.lock"


class TestApplyArchiveWritePath:
    """``apply_archive`` must both APPEND to the partition and EVICT from the
    corpus. Either half alone is a data-loss shape: eviction without the
    append destroys records; the append without eviction duplicates them."""

    def test_archives_and_evicts_past_decay_records(self, apply_env, monkeypatch):
        corpus, archive_dir, _ = apply_env
        old_a = _production_record("progress", 45)
        old_b = _production_record("context", 60)
        young = _production_record("progress", 5)
        permanent = _production_record("decision", 999)
        _write_corpus(corpus, [old_a, young, permanent, old_b])
        commits: list[tuple] = []
        monkeypatch.setattr(am, "_git_commit",
                            lambda *a, **k: commits.append(a))

        am.apply_archive(corpus, WINDOWS, NOW, None, "test sweep",
                         do_postgres=False, archive_dir=archive_dir)

        partition = archive_dir / "memories-archive-2026-06.jsonl"
        assert _ids_in(partition) == [old_a["id"], old_b["id"]]
        assert _ids_in(corpus) == [young["id"], permanent["id"]]
        assert commits, "the archival must be committed"

    def test_archived_line_is_preserved_verbatim(self, apply_env, monkeypatch):
        """Every production field survives the move (M5): the partition line
        must be the corpus line, byte for byte."""
        corpus, archive_dir, _ = apply_env
        old = _production_record("progress", 45)
        raw = json.dumps(old) + "\n"
        corpus.parent.mkdir(parents=True, exist_ok=True)
        corpus.write_text(raw, encoding="utf-8")
        monkeypatch.setattr(am, "_git_commit", lambda *a, **k: None)

        am.apply_archive(corpus, WINDOWS, NOW, None, "test sweep",
                         do_postgres=False, archive_dir=archive_dir)

        partition = archive_dir / "memories-archive-2026-06.jsonl"
        assert partition.read_text(encoding="utf-8") == raw
        assert json.loads(raw)["extractor_model_id"] == old["extractor_model_id"]

    def test_nothing_due_leaves_the_corpus_byte_identical(self, apply_env,
                                                          monkeypatch):
        """The negative case: nothing past decay ⇒ no partition, no commit,
        and not one byte of the corpus rewritten."""
        corpus, archive_dir, _ = apply_env
        _write_corpus(corpus, [_production_record("progress", 5),
                               _production_record("decision", 999)])
        before = corpus.read_bytes()
        commits: list[tuple] = []
        monkeypatch.setattr(am, "_git_commit",
                            lambda *a, **k: commits.append(a))

        am.apply_archive(corpus, WINDOWS, NOW, None, "test sweep",
                         do_postgres=False, archive_dir=archive_dir)

        assert corpus.read_bytes() == before
        assert not (archive_dir / "memories-archive-2026-06.jsonl").exists()
        assert commits == []

    def test_retry_does_not_duplicate_an_already_archived_record(
        self, apply_env, monkeypatch
    ):
        """Crash-then-retry shape: the record is already in the partition but
        still in the corpus. It must be evicted without a second append."""
        corpus, archive_dir, _ = apply_env
        old = _production_record("progress", 45)
        _write_corpus(corpus, [old])
        archive_dir.mkdir(parents=True)
        partition = archive_dir / "memories-archive-2026-06.jsonl"
        partition.write_text(json.dumps(old) + "\n", encoding="utf-8")
        monkeypatch.setattr(am, "_git_commit", lambda *a, **k: None)

        am.apply_archive(corpus, WINDOWS, NOW, None, "retry sweep",
                         do_postgres=False, archive_dir=archive_dir)

        assert _ids_in(partition) == [old["id"]]
        assert _ids_in(corpus) == []

    def test_run_manifest_records_the_sweep(self, apply_env, monkeypatch):
        corpus, archive_dir, _ = apply_env
        _write_corpus(corpus, [_production_record("progress", 45),
                               _production_record("context", 60)])
        monkeypatch.setattr(am, "_git_commit", lambda *a, **k: None)

        am.apply_archive(corpus, WINDOWS, NOW, None, "manifest sweep",
                         do_postgres=False, archive_dir=archive_dir)

        entries = [json.loads(line) for line in
                   (archive_dir / "archive-runs.jsonl").read_text().splitlines()]
        assert len(entries) == 1
        assert entries[0]["total"] == 2
        assert entries[0]["reason"] == "manifest sweep"

    def test_holds_the_daily_sync_lock_across_the_commit(self, apply_env,
                                                         monkeypatch):
        """Audit S15. The corpus is already truncated and replaced when the
        commit runs, so the daily-sync flock must still be held: a SessionStart
        daily-sync acquiring it in that gap would commit the shrunk corpus
        WITHOUT the ``Rewrite-Class: bulk`` trailer and trip its own shrink
        detector."""
        corpus, archive_dir, lock_file = apply_env
        _write_corpus(corpus, [_production_record("progress", 45)])
        probe: dict[str, int] = {}

        def _probe_lock(*args, **kwargs):
            # A separate process: flock(2) is per open file description, so
            # this fails iff apply_archive still holds the lock.
            probe["rc"] = subprocess.run(
                ["flock", "-n", str(lock_file), "true"], check=False
            ).returncode

        monkeypatch.setattr(am, "_git_commit", _probe_lock)
        am.apply_archive(corpus, WINDOWS, NOW, None, "lock sweep",
                         do_postgres=False, archive_dir=archive_dir)

        assert "rc" in probe, "_git_commit was never reached"
        assert probe["rc"] != 0, (
            "the daily-sync lock was NOT held while the archival was "
            "committed — daily-sync can commit the shrunk corpus in that gap"
        )
        # And it is released once apply_archive returns.
        assert subprocess.run(["flock", "-n", str(lock_file), "true"],
                              check=False).returncode == 0


class TestArchiveDirIsAParameter:
    """Audit M3: the cold-store path is a parameter, so a test that passes a
    throwaway corpus cannot append to the real archive by forgetting to patch
    a module global."""

    def test_partition_path_honours_the_argument(self, tmp_path):
        assert am._partition_path(NOW, tmp_path) == (
            tmp_path / "memories-archive-2026-06.jsonl")

    def test_partition_path_defaults_to_the_module_archive_dir(self):
        assert am._partition_path(NOW).parent == am.ARCHIVE_DIR

    def test_run_manifest_honours_the_argument(self, tmp_path):
        am._write_run_manifest(tmp_path / "part.jsonl", am.Counter({"progress": 1}),
                               "why", NOW, tmp_path)
        assert (tmp_path / "archive-runs.jsonl").exists()


class TestGitCommitPathspec:
    """Audit S16: the commit must name its pathspec. A bare ``git commit``
    publishes whatever a concurrent session has already staged in the shared
    index — under this script's bulk-rewrite subject and trailer."""

    def test_leaves_another_sessions_staged_file_alone(self, tmp_path,
                                                       monkeypatch):
        for key, value in {
            "GIT_AUTHOR_NAME": "Test Bot",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test Bot",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }.items():
            monkeypatch.setenv(key, value)
        data_dir = tmp_path / "data"
        archive_dir = data_dir / "memories" / "archive"
        corpus = data_dir / "memories" / "memories.jsonl"
        archive_dir.mkdir(parents=True)
        corpus.write_text("{}\n", encoding="utf-8")
        partition = archive_dir / "memories-archive-2026-06.jsonl"
        partition.write_text("{}\n", encoding="utf-8")
        (archive_dir / "archive-runs.jsonl").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(data_dir), "init", "-q", "-b", "main"],
                       check=True)
        subprocess.run(["git", "-C", str(data_dir), "commit", "-q",
                        "--allow-empty", "-m", "seed"], check=True)
        # Another session's work-in-progress, already staged in the index.
        (data_dir / "unrelated.md").write_text("half-written prose\n",
                                               encoding="utf-8")
        subprocess.run(["git", "-C", str(data_dir), "add", "unrelated.md"],
                       check=True)

        am._git_commit(corpus, partition, 2, None,
                       guard.mark_bulk_rewrite_commit_msg, archive_dir)

        committed = subprocess.run(
            ["git", "-C", str(data_dir), "show", "--name-only",
             "--pretty=format:", "HEAD"],
            capture_output=True, text=True, check=True).stdout.split()
        assert "memories/memories.jsonl" in committed
        assert "unrelated.md" not in committed, (
            "the archival commit swept another session's staged file"
        )
        staged = subprocess.run(
            ["git", "-C", str(data_dir), "diff", "--cached", "--name-only"],
            capture_output=True, text=True, check=True).stdout.split()
        assert staged == ["unrelated.md"], "the other session's staging was lost"
