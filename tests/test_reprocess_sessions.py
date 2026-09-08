"""
Tests for ``scripts/reprocess-sessions.py`` — historical memory extraction.

Only two things about this script were pinned before 2026-09-08: that its
command markers match the hook's, and the shape of its timestamps. Everything
that decides what gets sent to a paid model, and what the reply is credited
to, was untested — the already-extracted skip, the transcript reader's
filters, the custom_id, and the batch-state check (lens B finding 8).

Pinned here: AR6 (a second run selects nothing), AR7 (two sessions sharing an
8-character prefix get different request ids), AR8 (applying a batch through
another batch's map is refused), AR11 (isMeta and isSidechain are dropped as
the hook drops them), and the partial-last-line tolerance.

Every transcript and memory record is invented. No API client is constructed:
the Anthropic module is stubbed and the tests assert on whether it was used.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_fixtures import (  # noqa: E402
    make_archive_entry,
    prose_record,
    substantive_records,
)


def _load():
    """Import the hyphenated script by path."""
    spec = importlib.util.spec_from_file_location(
        "reprocess_sessions_under_test", str(SCRIPTS_DIR / "reprocess-sessions.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reprocess = _load()

LOGGER = logging.getLogger("reprocess-sessions-test")

SID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
#: Same first eight hex characters as SID_A — the AR7 collision case.
SID_A_TWIN = "aaaaaaaa-2222-4222-8222-bbbbbbbbbbbb"


def _write_gz(path: Path, records: list[dict]) -> Path:
    """Write records as a gzipped JSONL transcript."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(record) + "\n" for record in records)
    with gzip.open(path, "wb") as handle:
        handle.write(body.encode("utf-8"))
    return path


# ---------------------------------------------------------------------------
# AR11 — the transcript reader must filter exactly as the hook does
# ---------------------------------------------------------------------------


class TestTranscriptFiltering:
    """Harness prose and subagent turns are not the operator's words."""

    def test_meta_and_sidechain_records_are_dropped(
        self, tmp_path: Path
    ) -> None:
        """Both flags the hook honours, honoured here too."""
        path = _write_gz(tmp_path / "session.jsonl.gz", [
            prose_record("user", "Real question about the terrace.", index=1),
            prose_record(
                "assistant", "Real answer about the terrace.", index=2
            ),
            prose_record(
                "user", "Injected system reminder text.", index=3,
                is_meta=True,
            ),
            prose_record(
                "assistant", "A subagent's own reasoning.", index=4,
                is_sidechain=True,
            ),
            prose_record(
                "user", "A subagent's own question.", index=5,
                is_sidechain=True,
            ),
        ])

        messages = reprocess.parse_archived_transcript(path)

        texts = [message["content"] for message in messages]
        assert texts == [
            "Real question about the terrace.",
            "Real answer about the terrace.",
        ], (
            "harness-injected or subagent prose reached the extractor and "
            "would become memories attributed to the operator"
        )

    def test_a_slash_command_still_arms_the_skip(self, tmp_path: Path) -> None:
        """Commands arrive as isMeta user entries; the marker branch runs first."""
        marker = sorted(reprocess.COMMAND_MARKERS)[0]
        path = _write_gz(tmp_path / "session.jsonl.gz", [
            prose_record("user", f"{marker} please", index=1, is_meta=True),
            prose_record("assistant", "Command output, not a memory.", index=2),
            prose_record("user", "A genuine question.", index=3),
            prose_record("assistant", "A genuine answer.", index=4),
        ])

        messages = reprocess.parse_archived_transcript(path)

        assert [message["content"] for message in messages] == [
            "A genuine question.",
            "A genuine answer.",
        ]

    def test_a_partial_last_line_is_skipped_not_emptied(
        self, tmp_path: Path
    ) -> None:
        """A truncated final record must not become an empty entry."""
        path = tmp_path / "session.jsonl.gz"
        body = "".join(
            json.dumps(record) + "\n" for record in [
                prose_record("user", "Complete question.", index=1),
                prose_record("assistant", "Complete answer.", index=2),
            ]
        ) + '{"type": "user", "message": {"role"'
        with gzip.open(path, "wb") as handle:
            handle.write(body.encode("utf-8"))

        messages = reprocess.parse_archived_transcript(path)

        assert [message["content"] for message in messages] == [
            "Complete question.", "Complete answer.",
        ]


# ---------------------------------------------------------------------------
# AR6 — selection must be idempotent
# ---------------------------------------------------------------------------


class TestSelectionIdempotence:
    """A reprocessed session must not be reprocessed again.

    The writer stamps ``source: "reprocessing"``; selection counted only
    ``source: "extraction"``. So every run re-selected everything it had
    already done, paid for it again, and appended byte-identical duplicate
    rows (the memory ids are a deterministic hash).
    """

    @pytest.fixture()
    def store(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        archive_root = tmp_path / "cc-archives"
        archive_root.mkdir()
        memories = tmp_path / "memories.jsonl"
        memories.write_text("", encoding="utf-8")
        monkeypatch.setattr(reprocess, "ARCHIVE_ROOT", archive_root)
        monkeypatch.setattr(reprocess, "MEMORIES_FILE", memories)
        make_archive_entry(archive_root, SID_A)
        return types.SimpleNamespace(
            archive_root=archive_root, memories=memories
        )

    def _memory_row(self, source: str) -> str:
        return json.dumps({
            "id": "2026-03-02-abc123abc123",
            "session_id": SID_A,
            "project": "lantern-survey",
            "source": source,
            "category": "decision",
            "content": "Grid runs along the contour.",
            "confidence": "medium",
            "research_tags": ["survey-design"],
            "created_at": "2026-03-02T09:30:00+00:00",
        }) + "\n"

    def test_an_unmined_session_is_selected(self, store) -> None:
        """The positive control: with no memories, the session is work."""
        selected = reprocess.find_sessions_needing_reprocessing(LOGGER)
        assert [entry["session_id"] for entry in selected] == [SID_A]

    def test_a_reprocessed_session_is_not_selected_again(self, store) -> None:
        """This script's own output counts as already mined."""
        store.memories.write_text(
            self._memory_row("reprocessing"), encoding="utf-8"
        )

        selected = reprocess.find_sessions_needing_reprocessing(LOGGER)

        assert selected == [], (
            "a session this script already reprocessed was selected again; "
            "the second run re-spends and appends duplicate rows"
        )

    def test_a_hook_extracted_session_is_still_not_selected(
        self, store
    ) -> None:
        """The original skip must survive the widening."""
        store.memories.write_text(
            self._memory_row("extraction"), encoding="utf-8"
        )

        assert reprocess.find_sessions_needing_reprocessing(LOGGER) == []

    def test_a_manual_memory_does_not_count_as_mined(self, store) -> None:
        """``/remember`` output is not evidence the session was extracted."""
        store.memories.write_text(
            self._memory_row("manual"), encoding="utf-8"
        )

        selected = reprocess.find_sessions_needing_reprocessing(LOGGER)
        assert [entry["session_id"] for entry in selected] == [SID_A]


# ---------------------------------------------------------------------------
# AR7 — request ids must identify a session uniquely
# ---------------------------------------------------------------------------


class StubAnthropic:
    """Records batch submissions instead of making them."""

    submitted: list[list[dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        self.messages = types.SimpleNamespace(
            batches=types.SimpleNamespace(create=self._create)
        )

    def _create(self, requests):
        StubAnthropic.submitted.append(list(requests))
        return types.SimpleNamespace(
            id="msgbatch_stub", processing_status="in_progress"
        )


class TestCustomIdUniqueness:
    """Two sessions sharing an 8-character prefix are two sessions."""

    def test_prefix_twins_get_different_custom_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        archive_root = tmp_path / "cc-archives"
        archive_root.mkdir()
        memories = tmp_path / "memories.jsonl"
        memories.write_text("", encoding="utf-8")
        state_file = tmp_path / "batch-state.json"
        for index, sid in enumerate((SID_A, SID_A_TWIN)):
            make_archive_entry(
                archive_root, sid, entry_name=f"2026-03-0{index + 2}_entry",
                records=substantive_records(sid, turns=2),
            )
        monkeypatch.setattr(reprocess, "ARCHIVE_ROOT", archive_root)
        monkeypatch.setattr(reprocess, "MEMORIES_FILE", memories)
        monkeypatch.setattr(reprocess, "BATCH_STATE_FILE", state_file)
        monkeypatch.setattr(reprocess, "load_env", lambda: None)
        monkeypatch.setattr(reprocess, "load_seed_tags", lambda n: [])
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        stub_module = types.ModuleType("anthropic")
        stub_module.Anthropic = StubAnthropic
        StubAnthropic.submitted = []
        monkeypatch.setitem(sys.modules, "anthropic", stub_module)

        reprocess.cmd_submit(
            types.SimpleNamespace(mode="submit", limit=0, dry_run=False),
            LOGGER,
        )

        assert StubAnthropic.submitted, "no batch was built"
        custom_ids = [
            request["custom_id"] for request in StubAnthropic.submitted[0]
        ]
        assert len(custom_ids) == len(set(custom_ids)), (
            f"colliding custom_ids: {custom_ids}"
        )
        state = json.loads(state_file.read_text(encoding="utf-8"))
        mapped = {
            entry["session_id"] for entry in state["request_map"].values()
        }
        assert mapped == {SID_A, SID_A_TWIN}
        for custom_id in custom_ids:
            assert len(custom_id) <= 64, (
                "custom_id exceeds the Batch API's 64-character limit"
            )


# ---------------------------------------------------------------------------
# AR8 — apply must refuse a batch the state does not describe
# ---------------------------------------------------------------------------


class ApplyStub:
    """A client that would answer, so a refusal is visible as no call."""

    calls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        self.messages = types.SimpleNamespace(
            batches=types.SimpleNamespace(
                retrieve=self._retrieve, results=self._results
            )
        )

    def _retrieve(self, batch_id: str):
        ApplyStub.calls.append(f"retrieve:{batch_id}")
        return types.SimpleNamespace(
            processing_status="ended",
            request_counts=types.SimpleNamespace(
                succeeded=0, errored=0, processing=0
            ),
        )

    def _results(self, batch_id: str):
        ApplyStub.calls.append(f"results:{batch_id}")
        return iter(())


class TestApplyRefusesTheWrongBatch:
    """Applying batch A through batch B's map misfiles every memory."""

    @pytest.fixture()
    def applied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        state_file = tmp_path / "batch-state.json"
        state_file.write_text(json.dumps({
            "batch_id": "msgbatch_first",
            "n_requests": 1,
            "request_map": {
                f"rp-{SID_A}-c0": {
                    "session_id": SID_A,
                    "project": "lantern-survey",
                    "started_at": "2026-03-02T09:00:00Z",
                    "chunk_index": 0,
                }
            },
        }), encoding="utf-8")
        monkeypatch.setattr(reprocess, "BATCH_STATE_FILE", state_file)
        monkeypatch.setattr(reprocess, "MEMORIES_FILE", tmp_path / "mem.jsonl")
        monkeypatch.setattr(reprocess, "load_env", lambda: None)
        monkeypatch.setattr(
            reprocess, "ensure_safe_to_rewrite", lambda reason: None
        )
        monkeypatch.setattr(reprocess, "release_lock", lambda: None)
        stub_module = types.ModuleType("anthropic")
        stub_module.Anthropic = ApplyStub
        ApplyStub.calls = []
        monkeypatch.setitem(sys.modules, "anthropic", stub_module)
        return state_file

    def test_a_different_batch_id_is_refused(self, applied) -> None:
        with pytest.raises(SystemExit) as exit_info:
            reprocess.cmd_apply(
                types.SimpleNamespace(mode="apply", batch_id="msgbatch_second"),
                LOGGER,
            )

        assert exit_info.value.code != 0
        assert ApplyStub.calls == [], (
            "the wrong batch's results were retrieved before the check"
        )

    def test_the_matching_batch_id_proceeds(self, applied) -> None:
        """The positive control: the refusal must not block the real case."""
        reprocess.cmd_apply(
            types.SimpleNamespace(mode="apply", batch_id="msgbatch_first"),
            LOGGER,
        )

        assert ApplyStub.calls[0] == "retrieve:msgbatch_first"
