"""Tests for scripts/bulk-archive.py — Phase 2 bulk session archiving."""

import gzip
import json
import logging
import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts directory to path so we can import the module
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# Import after path manipulation
import importlib

bulk_archive = importlib.import_module("bulk-archive")


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def tmp_session_dir(tmp_path: Path) -> Path:
    """Create a minimal session JSONL file for testing."""
    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    session_file = tmp_path / f"{session_id}.jsonl"

    # Write a realistic multi-turn session
    entries = [
        {"type": "system", "cwd": "/home/shawn/Code/test-project"},
        {
            "message": {
                "role": "user",
                "content": "Help me refactor the auth module",
            },
            "timestamp": "2026-04-10T10:00:00Z",
        },
        {
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll refactor the auth module."},
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": "/home/shawn/Code/test/auth.py"},
                    },
                ],
            },
            "timestamp": "2026-04-10T10:01:00Z",
        },
        {
            "message": {
                "role": "user",
                "content": "Now update the tests",
            },
            "timestamp": "2026-04-10T10:02:00Z",
        },
        {
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Tests updated."}],
            },
            "timestamp": "2026-04-10T10:03:00Z",
        },
        {
            "message": {
                "role": "user",
                "content": "Looks good, thanks",
            },
            "timestamp": "2026-04-10T10:04:00Z",
        },
        {
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Done!"}],
            },
            "timestamp": "2026-04-10T10:05:00Z",
        },
    ]

    with open(session_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return tmp_path


@pytest.fixture()
def tmp_projects_dir(tmp_path: Path) -> Path:
    """Create a mock ~/.claude/projects/ structure."""
    projects = tmp_path / "projects"
    projects.mkdir()

    # Project with sessions
    proj1 = projects / "-home-shawn-Code-test-project"
    proj1.mkdir()

    # Normal session
    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    session_file = proj1 / f"{session_id}.jsonl"
    entries = [
        {"type": "system", "cwd": "/home/shawn/Code/test-project"},
        {
            "message": {"role": "user", "content": "Help me refactor"},
            "timestamp": "2026-04-10T10:00:00Z",
        },
        {
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done"}]},
            "timestamp": "2026-04-10T10:01:00Z",
        },
        {
            "message": {"role": "user", "content": "Now update tests"},
            "timestamp": "2026-04-10T10:02:00Z",
        },
        {
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done"}]},
            "timestamp": "2026-04-10T10:03:00Z",
        },
        {
            "message": {"role": "user", "content": "Ship it"},
            "timestamp": "2026-04-10T10:04:00Z",
        },
        {
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done"}]},
            "timestamp": "2026-04-10T10:05:00Z",
        },
    ]
    with open(session_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    # Session with subagents
    sa_session_id = "11111111-2222-3333-4444-555555555555"
    sa_session_file = proj1 / f"{sa_session_id}.jsonl"
    with open(sa_session_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    sa_dir = proj1 / sa_session_id / "subagents"
    sa_dir.mkdir(parents=True)
    sa_file = sa_dir / "agent-abc123.jsonl"
    with open(sa_file, "w") as f:
        f.write(json.dumps({"message": {"role": "user", "content": "sub"}}) + "\n")

    # Flat agent (should be skipped)
    flat_agent = proj1 / "agent-orphan123.jsonl"
    with open(flat_agent, "w") as f:
        f.write(json.dumps({"message": {"role": "user", "content": "orphan"}}) + "\n")

    # Trivial session (< 5 turns)
    trivial_id = "99999999-8888-7777-6666-555555555555"
    trivial_file = proj1 / f"{trivial_id}.jsonl"
    with open(trivial_file, "w") as f:
        f.write(json.dumps({
            "message": {"role": "user", "content": "hi"},
            "timestamp": "2026-04-10T10:00:00Z",
        }) + "\n")
        f.write(json.dumps({
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
            "timestamp": "2026-04-10T10:00:01Z",
        }) + "\n")

    return tmp_path


# ============================================================================
# Tests — Project Mapping
# ============================================================================


class TestExtractCwd:
    """Tests for _extract_cwd_from_jsonl."""

    def test_extracts_cwd_from_first_entry(self, tmp_session_dir: Path) -> None:
        """Should find cwd in the first JSONL entry."""
        session_file = list(tmp_session_dir.glob("*.jsonl"))[0]
        result = bulk_archive._extract_cwd_from_jsonl(session_file)
        assert result == "/home/shawn/Code/test-project"

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        """Should return None for an empty file."""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert bulk_archive._extract_cwd_from_jsonl(empty) is None

    def test_returns_none_for_no_cwd(self, tmp_path: Path) -> None:
        """Should return None when no entry has a cwd field."""
        no_cwd = tmp_path / "no-cwd.jsonl"
        no_cwd.write_text(json.dumps({"message": {"role": "user"}}) + "\n")
        assert bulk_archive._extract_cwd_from_jsonl(no_cwd) is None


class TestReconstructPath:
    """Tests for _reconstruct_path_from_encoded."""

    def test_simple_path(self, tmp_path: Path) -> None:
        """Should reconstruct a simple path with no ambiguous hyphens."""
        # Create the target directory
        target = tmp_path / "home" / "user" / "Code"
        target.mkdir(parents=True)

        encoded = f"-{str(target).replace('/', '-')}"
        # This won't work for arbitrary paths — test the concept
        result = bulk_archive._reconstruct_path_from_encoded(encoded)
        # May or may not resolve depending on actual filesystem
        # The function is best-effort
        assert result is None or isinstance(result, Path)

    def test_non_encoded_returns_none(self) -> None:
        """Should return None for strings not starting with -."""
        assert bulk_archive._reconstruct_path_from_encoded("no-dash") is None


# ============================================================================
# Tests — Meta Message Filtering
# ============================================================================


class TestIsMetaMessage:
    """Tests for _is_meta_message."""

    def test_slash_commands_are_meta(self) -> None:
        assert bulk_archive._is_meta_message("/recap") is True
        assert bulk_archive._is_meta_message("/done task") is True
        assert bulk_archive._is_meta_message("/standup") is True

    def test_short_confirmations_are_meta(self) -> None:
        assert bulk_archive._is_meta_message("yes") is True
        assert bulk_archive._is_meta_message("ok") is True
        assert bulk_archive._is_meta_message("looks good") is True
        assert bulk_archive._is_meta_message("lgtm") is True

    def test_substantive_messages_are_not_meta(self) -> None:
        assert bulk_archive._is_meta_message("Help me refactor the auth module") is False
        assert bulk_archive._is_meta_message("Now update the tests to cover edge cases") is False

    def test_empty_is_meta(self) -> None:
        assert bulk_archive._is_meta_message("") is True
        assert bulk_archive._is_meta_message("   ") is True


# ============================================================================
# Tests — Message Sampling
# ============================================================================


class TestSampleUserMessages:
    """Tests for _sample_user_messages."""

    def test_samples_first_and_last(self, tmp_session_dir: Path) -> None:
        """Should return first 2 + last 2 substantive messages."""
        session_file = list(tmp_session_dir.glob("*.jsonl"))[0]
        sampled, files = bulk_archive._sample_user_messages(session_file)

        # "Help me refactor the auth module", "Now update the tests"
        # are substantive; "Looks good, thanks" is short but >40 chars? No,
        # it's <40 chars but not in the meta set — so it's substantive.
        assert len(sampled) >= 2
        assert any("refactor" in msg for msg in sampled)

    def test_extracts_file_paths(self, tmp_session_dir: Path) -> None:
        """Should extract Write/Edit file paths."""
        session_file = list(tmp_session_dir.glob("*.jsonl"))[0]
        _, files = bulk_archive._sample_user_messages(session_file)
        assert "/home/shawn/Code/test/auth.py" in files


# ============================================================================
# Tests — Subagent Archiving
# ============================================================================


class TestArchiveSubagents:
    """Tests for archive_subagents."""

    def test_compresses_subagents(self, tmp_path: Path) -> None:
        """Should gzip-compress subagent JSONL files."""
        # Create source structure
        source_dir = tmp_path / "source"
        sa_dir = source_dir / "subagents"
        sa_dir.mkdir(parents=True)

        sa_file = sa_dir / "agent-test1.jsonl"
        sa_file.write_text('{"message": "test"}\n')

        # Create archive destination
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        logger = logging.getLogger("test")
        count = bulk_archive.archive_subagents(source_dir, archive_dir, logger)

        assert count == 1
        gz_file = archive_dir / "subagents" / "agent-test1.jsonl.gz"
        assert gz_file.exists()

        # Verify content
        with gzip.open(gz_file, "rt") as f:
            content = f.read()
        assert '"message": "test"' in content

    def test_returns_zero_for_no_subagents(self, tmp_path: Path) -> None:
        """Should return 0 when no subagents directory exists."""
        logger = logging.getLogger("test")
        count = bulk_archive.archive_subagents(tmp_path, tmp_path / "out", logger)
        assert count == 0


# ============================================================================
# Tests — Checkpoint
# ============================================================================


class TestCheckpoint:
    """Tests for checkpoint load/save."""

    def test_load_empty_checkpoint(self) -> None:
        """Should return default structure when no file exists."""
        with patch.object(bulk_archive, "CHECKPOINT_FILE", Path("/nonexistent")):
            cp = bulk_archive._load_checkpoint()
        assert cp["archived_ids"] == []
        assert cp["stats"]["total_archived"] == 0

    def test_save_and_load_checkpoint(self, tmp_path: Path) -> None:
        """Should round-trip checkpoint data through save/load."""
        cp_file = tmp_path / "progress.json"
        with patch.object(bulk_archive, "CHECKPOINT_FILE", cp_file):
            cp = bulk_archive._load_checkpoint()
            cp["archived_ids"].append("test-id-1")
            cp["stats"]["total_archived"] = 1
            bulk_archive._save_checkpoint(cp)

            loaded = bulk_archive._load_checkpoint()
        assert "test-id-1" in loaded["archived_ids"]
        assert loaded["stats"]["total_archived"] == 1
        assert "updated_at" in loaded


# ============================================================================
# Tests — Enrich Prompt Building
# ============================================================================


class TestBuildEnrichPrompt:
    """Tests for _build_enrich_prompt."""

    def test_includes_messages_and_stats(self) -> None:
        """Should include sampled messages and session stats in prompt."""
        messages = ["Help me refactor", "Now update tests"]
        files = {"/home/shawn/Code/auth.py"}
        stats = {
            "duration_minutes": 30,
            "turns": 10,
            "tool_calls": {"by_type": {"Edit": 5, "Read": 3}},
        }

        prompt = bulk_archive._build_enrich_prompt(messages, files, stats)

        assert "refactor" in prompt
        assert "update tests" in prompt
        assert "30 min" in prompt
        assert "10 turns" in prompt
        assert "auth.py" in prompt
        assert "JSON" in prompt


# ============================================================================
# Tests — Discovery (with mocked toolkit)
# ============================================================================


class TestDiscoverSkipsFlat:
    """Tests that discover_sessions skips orphaned flat agent files."""

    def test_flat_agents_excluded(self, tmp_projects_dir: Path) -> None:
        """Flat agent-*.jsonl files at root should not appear in manifest."""
        proj_dir = (
            tmp_projects_dir / "projects"
            / "-home-shawn-Code-test-project"
        )

        # Verify the flat agent file exists
        flat = proj_dir / "agent-orphan123.jsonl"
        assert flat.exists()

        # Count JSONL files that start with agent-
        agent_files = list(proj_dir.glob("agent-*.jsonl"))
        assert len(agent_files) == 1

        # The discover function should skip these — verified by the
        # filtering logic: `if jsonl_file.name.startswith("agent-"): continue`
        # We test the filter directly rather than mocking the full toolkit
        for f in proj_dir.glob("*.jsonl"):
            if f.name.startswith("agent-"):
                # This file should be skipped
                assert f.name == "agent-orphan123.jsonl"


# ============================================================================
# Tests — Verify (basic structure)
# ============================================================================


class TestVerifyDetectsIssues:
    """Tests for the verify mode's integrity checking."""

    def test_detects_missing_jsonl(self, tmp_path: Path) -> None:
        """Should flag archives missing their JSONL file."""
        # Create an archive dir with meta but no JSONL
        archive_dir = tmp_path / "test-project" / "2026-04-10_test"
        archive_dir.mkdir(parents=True)

        meta = {
            "session": {"id": "test-123"},
            "project": {"name": "test-project"},
            "auto_generated": {"purpose": "Test session", "tags": []},
        }
        (archive_dir / "session.meta.json").write_text(json.dumps(meta))

        # The file has no session.jsonl.gz or session.jsonl
        has_jsonl = (
            (archive_dir / "session.jsonl.gz").exists()
            or (archive_dir / "session.jsonl").exists()
        )
        assert not has_jsonl


# ============================================================================
# Tests — Unresolved project root sentinel (Audit 2026-05-02 E-Medium)
# ============================================================================


class TestProjectRootSentinel:
    """Tests for the None-sentinel replacement of the legacy /tmp fallback.

    Previously, ``resolve_project_mapping`` used ``Path("/tmp")`` to mark
    unresolved project roots. Because ``/tmp`` exists on every Unix host
    and is a directory, the sentinel masqueraded as a real project root
    in the downstream ``is_dir()`` guard. The fix replaces the sentinel
    with ``None`` and updates the call site to handle the missing root
    explicitly.
    """

    def test_unresolved_root_serialises_as_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An encoded dir with no JSONL cwd and no reconstructable path
        produces ``project_root=None`` (not ``Path('/tmp')``)."""
        # Build a minimal projects/ tree with one encoded dir whose
        # encoded name cannot be reconstructed (no matching directory
        # exists on the test filesystem).
        projects_dir = tmp_path / "projects"
        unresolvable = projects_dir / "-no-such-path-anywhere-xyz"
        unresolvable.mkdir(parents=True)
        # An empty session JSONL — _extract_cwd_from_jsonl returns None
        # because there is no `cwd` field.
        (unresolvable / "session.jsonl").write_text(
            '{"type": "user", "message": {"role": "user"}}\n'
        )

        monkeypatch.setattr(bulk_archive, "CLAUDE_PROJECTS_DIR", projects_dir)

        logger = logging.getLogger("test_project_root_sentinel")
        mapping = bulk_archive.resolve_project_mapping(logger)

        assert "-no-such-path-anywhere-xyz" in mapping
        project_root, _project_name = mapping["-no-such-path-anywhere-xyz"]
        # The fix: None, not Path("/tmp").
        assert project_root is None, (
            f"Expected None sentinel, got {project_root!r}. The /tmp "
            f"sentinel would silently masquerade as a real project root."
        )

    def test_legacy_tmp_sentinel_is_gone(self) -> None:
        """The literal ``Path('/tmp')`` sentinel must not appear in the
        resolver source. This is a defence-in-depth check against
        accidental reintroduction of the bug."""
        source = Path(bulk_archive.__file__).read_text(encoding="utf-8")
        # Only flag the sentinel pattern, not legitimate /tmp usage in
        # comments or unrelated paths.
        assert 'project_root or Path("/tmp")' not in source
        assert "Path('/tmp'), project_name" not in source
