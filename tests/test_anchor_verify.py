"""
Tests for scripts/anchor_verify.py — the v2 mechanical anchor
verification module (Memory System v2, Phase 2).

Tests pure functions and dispatcher logic. Subprocess-bound paths
(verify_file, verify_commit) are exercised against mocked
subprocess.run; an integration test against a real git fixture is
deferred until Phase 0b.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# Import the module (under scripts/, hyphenated filename for some
# siblings — but anchor_verify is underscored so importlib isn't strictly
# needed; use it anyway to stay consistent with other test modules).
_av_path = Path(__file__).parent.parent / "scripts" / "anchor_verify.py"
_spec = importlib.util.spec_from_file_location("anchor_verify", _av_path)
av = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(av)


# ============================================================================
# _looks_like_hash — gate before launching git
# ============================================================================


class TestLooksLikeHash:
    """Cheap hash-shape predicate used by verify_commit."""

    @pytest.mark.parametrize("h", [
        "abc1234",                  # 7-char (typical short hash)
        "a1b2c3d4",                 # 8-char
        "1234567890abcdef" * 2 + "12345678",  # 40-char (full SHA-1)
        "ABCDEF12",                 # uppercase OK
        "DeadBeef",                 # mixed case
    ])
    def test_valid_hash_shapes(self, h):
        assert av._looks_like_hash(h) is True

    @pytest.mark.parametrize("h", [
        "",                         # empty
        "abc",                      # too short
        "g" * 8,                    # non-hex character
        "abc xyz",                  # whitespace
        "a" * 41,                   # too long
        "../../../etc/passwd",      # path-shaped, not hash-shaped
    ])
    def test_invalid_hash_shapes(self, h):
        assert av._looks_like_hash(h) is False


# ============================================================================
# wellformed_anchor — write-time structural gate (item 11)
# ============================================================================


class TestWellformedAnchor:
    """Pure, I/O-free shape gate applied before persisting anchors."""

    def test_valid_commit_hash_ok(self):
        ok, reason = av.wellformed_anchor({"type": "commit", "ref": "7078d39"})
        assert ok is True and reason == "ok"

    @pytest.mark.parametrize("ref", [
        "rome-verification-script",            # descriptive slug
        "audit-corrections-applied",           # descriptive slug
        "bb5r1pr54",                           # non-hex chars
        "feat(hooks): SessionStart sidecar",   # a commit *message*, not a ref
    ])
    def test_malformed_commit_refs_rejected(self, ref):
        ok, reason = av.wellformed_anchor({"type": "commit", "ref": ref})
        assert ok is False and reason == "malformed-commit-ref"

    def test_file_ref_shape_ok_even_if_nonexistent(self):
        # A path that doesn't exist *here* may resolve elsewhere — that's the
        # resolver's call, not the write-time gate's.
        ok, _ = av.wellformed_anchor({"type": "file", "ref": "scripts/nope.py"})
        assert ok is True

    def test_file_ref_with_newline_rejected(self):
        ok, reason = av.wellformed_anchor({"type": "file", "ref": "a\nb"})
        assert ok is False and reason == "malformed-file-ref"

    def test_zotero_key_ok_and_prose_rejected(self):
        assert av.wellformed_anchor({"type": "zotero", "ref": "ABCD1234"})[0] is True
        assert av.wellformed_anchor({"type": "zotero", "ref": "not a key!"})[0] is False

    def test_url_scheme_required(self):
        assert av.wellformed_anchor({"type": "url", "ref": "https://x.org"})[0] is True
        assert av.wellformed_anchor({"type": "url", "ref": "x.org"})[0] is False

    def test_unknown_type_passes_through(self):
        # Forward-compat: a future anchor type is never silently dropped.
        ok, reason = av.wellformed_anchor({"type": "dataset", "ref": "anything"})
        assert ok is True and reason == "unknown-type"

    @pytest.mark.parametrize("bad", [
        "not-a-dict",
        {"type": "commit"},                    # missing ref
        {"type": 5, "ref": "abc1234"},         # non-str type
        {"type": "commit", "ref": "   "},      # whitespace-only ref
    ])
    def test_structurally_invalid_rejected(self, bad):
        assert av.wellformed_anchor(bad)[0] is False

    def test_tightened_file_gate_rejects_prose(self):
        # item 21a: prose mis-typed as a file anchor now fails the gate.
        ok, reason = av.wellformed_anchor(
            {"type": "file", "ref": "scoring table (7 sessions, 42 cells)"})
        assert ok is False and reason == "malformed-file-ref"

    def test_tightened_file_gate_passes_real_path(self):
        ok, reason = av.wellformed_anchor(
            {"type": "file", "ref": "wiki/continuity.md"})
        assert ok is True and reason == "ok"


# ============================================================================
# _looks_like_file_ref — tightened file-anchor shape gate (item 21a)
# ============================================================================


class TestLooksLikeFileRef:
    """Shape gate that separates genuine paths from prose / ids / commands.

    Every ref here is drawn from the item-20 triage's residual broad-false
    ``file`` anchors (the junk we must now reject) or its legitimate-looking
    paths (which must still pass).
    """

    @pytest.mark.parametrize("ref", [
        # genuine paths — keyed on separator or extension, not on spaces
        "scripts/nope.py",
        "wiki/continuity.md",
        "continuity.md",                       # bare basename (resolver/21b's job)
        "decision-log.md",
        "session.meta.json",
        "~/.bash_aliases",
        "~/Zotero/storage/FGM4PVSX/Hanson - 2016 - urban geography.pdf",  # space+sep
        "/home/shawn/personal-assistant/scripts/x.py",  # multi-segment absolute
        "responses-round-1/",                  # directory ref
        "LICENSE",                             # extensionless real file
        "Makefile",
    ])
    def test_genuine_paths_pass(self, ref):
        assert av._looks_like_file_ref(ref) is True

    @pytest.mark.parametrize("ref", [
        # prose
        "scoring table (7 sessions, 42 cells)",
        "preregistration draft",
        "Round 4 tally table: H=7 (17%), G=17 (40%), T=18 (43%)",
        "Run-sheet Block B2",
        # slash-command names (single-segment absolute, prose tolerated)
        "/weekly-review",
        "/reflect",
        "/lit-scout-iterate — Iteration policy (settled 2026-05-22)",
        # bare object ids mis-typed as files
        "3825319a",
        "932f8ad0",
        "a6ba54fa",
        "msgbatch_016RZjdHMfWAtKcW2uBxkbgJ",
        # control chars / over-length
        "a\nb",
        "a\tb",
        "x" * 257,
    ])
    def test_junk_rejected(self, ref):
        assert av._looks_like_file_ref(ref) is False

    def test_short_hex_word_not_rejected(self):
        # <6 hex chars is an ordinary short token, not an object id.
        assert av._looks_like_file_ref("cafe") is True


# ============================================================================
# bind_confidence — the rubric that Phase 2 uses to override Haiku
# ============================================================================


class TestBindConfidence:
    """The mapping from verified-status to confidence label."""

    def test_verified_true_non_guidance_is_high(self):
        assert av.bind_confidence(
            "true", is_guidance_category=False,
        ) == "high"

    def test_verified_true_guidance_complete_is_high(self):
        assert av.bind_confidence(
            "true",
            has_why=True,
            has_how_to_apply=True,
            is_guidance_category=True,
        ) == "high"

    def test_verified_true_guidance_missing_why_is_medium(self):
        assert av.bind_confidence(
            "true",
            has_why=False,
            has_how_to_apply=True,
            is_guidance_category=True,
        ) == "medium"

    def test_verified_true_guidance_missing_how_is_medium(self):
        assert av.bind_confidence(
            "true",
            has_why=True,
            has_how_to_apply=False,
            is_guidance_category=True,
        ) == "medium"

    def test_verified_pending_is_medium(self):
        assert av.bind_confidence("pending") == "medium"

    def test_verified_tier3_is_medium(self):
        # tier3 reserved for Phase 0b transcript-grep fallback;
        # rubric handles it for forward compatibility.
        assert av.bind_confidence("tier3") == "medium"

    def test_verified_false_is_low(self):
        assert av.bind_confidence("false") == "low"

    def test_verified_none_is_low(self):
        # No anchors checked at all — pre-v2 memories land here.
        assert av.bind_confidence(None) == "low"

    def test_guidance_category_doesnt_help_when_verified_false(self):
        # Even with rationale, a failed-verification memory stays low.
        assert av.bind_confidence(
            "false",
            has_why=True,
            has_how_to_apply=True,
            is_guidance_category=True,
        ) == "low"


# ============================================================================
# verify_memory — aggregation across multiple anchors
# ============================================================================


class TestVerifyMemoryAggregation:
    """How verify_memory combines per-anchor verifier results."""

    def test_no_anchors_returns_none(self):
        record = {"id": "test", "content": "no anchors here"}
        assert av.verify_memory(record, []) is None

    def test_empty_anchors_returns_none(self):
        record = {"id": "test", "anchors": []}
        assert av.verify_memory(record, []) is None

    def test_all_true_returns_true(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "file", "ref": "a.py"},
                {"type": "file", "ref": "b.py"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda ref, _r: "true"}):
            assert av.verify_memory(record, []) == "true"

    def test_any_false_returns_false(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "file", "ref": "real.py"},
                {"type": "file", "ref": "invented.py"},
            ],
        }
        results = iter(["true", "false"])
        with patch.dict(av._VERIFIERS, {"file": lambda r, _: next(results)}):
            assert av.verify_memory(record, []) == "false"

    def test_pending_with_no_false_returns_pending(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "file", "ref": "a.py"},
                {"type": "zotero", "ref": "MPZHXY3P"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda r, _: "true"}):
            # zotero stub already returns "pending"
            assert av.verify_memory(record, []) == "pending"

    def test_unknown_anchor_type_is_ignored(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "telepathy", "ref": "alpha-centauri"},
                {"type": "file", "ref": "a.py"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda ref, _r: "true"}):
            assert av.verify_memory(record, []) == "true"

    def test_malformed_anchor_skipped(self):
        record = {
            "id": "test",
            "anchors": [
                "not a dict",
                {"type": "file"},          # missing ref
                {"ref": "a.py"},            # missing type
                {"type": "file", "ref": "a.py"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda ref, _r: "true"}):
            assert av.verify_memory(record, []) == "true"

    def test_verifier_exception_treated_as_pending(self):
        record = {
            "id": "test",
            "anchors": [{"type": "file", "ref": "a.py"}],
        }
        def boom(*_):
            raise RuntimeError("boom")
        with patch.dict(av._VERIFIERS, {"file": boom}):
            assert av.verify_memory(record, []) == "pending"


# ============================================================================
# verify_commit — hash-shape gate
# ============================================================================


class TestVerifyCommitHashGate:
    """verify_commit short-circuits before subprocess on non-hash strings."""

    def test_short_circuit_on_non_hash(self):
        # No subprocess call should happen for an obviously non-hash value.
        with patch("subprocess.run") as mock_run:
            result = av.verify_commit("not-a-hash-at-all !!!", [Path("/tmp")])
            assert result == "false"
            mock_run.assert_not_called()

    def test_empty_input(self):
        assert av.verify_commit("", []) == "false"


# ============================================================================
# verify_zotero — stub
# ============================================================================


class TestVerifyZoteroStub:
    """The Zotero verifier is stubbed until Phase 5 — pending always."""

    def test_returns_pending(self):
        assert av.verify_zotero("MPZHXY3P") == "pending"

    def test_returns_pending_even_for_empty(self):
        # The stub doesn't try to validate the key shape.
        assert av.verify_zotero("") == "pending"


# ============================================================================
# verify_file — path/history hardening (item 20)
# ============================================================================
#
# These exercise the filesystem (stat) path against a real tmp_path, which
# needs no git and is fully deterministic. The git-history fallback is unit-
# tested via a mocked subprocess (_git_knows_path); a full integration test
# against a real git fixture remains deferred to Phase 0b per the module note.


class TestRelpathInRepo:
    """Lexical repo-prefix helper used for the absolute-path git fallback."""

    def test_path_inside_repo(self):
        assert av._relpath_in_repo(
            "/home/u/repo/scripts/x.py", Path("/home/u/repo")
        ) == "scripts/x.py"

    def test_path_outside_repo_is_none(self):
        assert av._relpath_in_repo(
            "/home/u/other/x.py", Path("/home/u/repo")
        ) is None

    def test_repo_root_itself_is_none(self):
        # The repo root is a directory, not a file anchor.
        assert av._relpath_in_repo("/home/u/repo", Path("/home/u/repo")) is None

    def test_sibling_prefix_not_matched(self):
        # /home/u/repo must not match /home/u/repo-backup (no false prefix).
        assert av._relpath_in_repo(
            "/home/u/repo-backup/x.py", Path("/home/u/repo")
        ) is None

    def test_normalises_dot_segments(self):
        assert av._relpath_in_repo(
            "/home/u/repo/./a/../scripts/x.py", Path("/home/u/repo")
        ) == "scripts/x.py"


class TestVerifyFileFilesystem:
    """Tilde expansion + absolute/relative stat resolution (no git needed)."""

    def test_empty_path_false(self):
        assert av.verify_file("", []) == "false"

    def test_tilde_expands_to_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "notes.md").write_text("hi", encoding="utf-8")
        # The repo_set is irrelevant: ~ expands to an absolute, existing path.
        assert av.verify_file("~/notes.md", []) == "true"

    def test_tilde_missing_file_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert av.verify_file("~/nope.md", []) == "false"

    def test_absolute_existing_file_true(self, tmp_path):
        f = tmp_path / "real.py"
        f.write_text("x", encoding="utf-8")
        assert av.verify_file(str(f), []) == "true"

    def test_absolute_missing_file_outside_any_repo_false(self, tmp_path):
        # Not under any repo in repo_set and not on disk → false (no git hit).
        missing = tmp_path / "gone.py"
        assert av.verify_file(str(missing), [tmp_path / "unrelated"]) == "false"

    def test_relative_existing_under_repo_true(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "a.py").write_text("x", encoding="utf-8")
        assert av.verify_file("scripts/a.py", [tmp_path]) == "true"


class TestGitKnowsPath:
    """The HEAD + history probe, with subprocess mocked."""

    def test_empty_relpath_false(self):
        assert av._git_knows_path(Path("/repo"), "") == "false"

    def test_head_hit_returns_true_without_log(self):
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            assert av._git_knows_path(Path("/repo"), "a.py") == "true"
            # Only the cat-file probe should have fired.
            assert run.call_count == 1

    def test_history_hit_when_not_at_head(self):
        # cat-file miss (rc=1), then git log finds a commit touching the path.
        results = [
            MagicMock(returncode=1),                       # cat-file -e HEAD
            MagicMock(returncode=0, stdout="deadbee log"),  # git log --all
        ]
        with patch("subprocess.run", side_effect=results):
            assert av._git_knows_path(Path("/repo"), "deleted.py") == "true"

    def test_absent_everywhere_false(self):
        results = [
            MagicMock(returncode=1),               # cat-file miss
            MagicMock(returncode=0, stdout=""),     # empty log → never existed
        ]
        with patch("subprocess.run", side_effect=results):
            assert av._git_knows_path(Path("/repo"), "ghost.py") == "false"

    def test_timeout_is_pending(self):
        import subprocess as _sp
        with patch("subprocess.run", side_effect=_sp.TimeoutExpired("git", 3)):
            assert av._git_knows_path(Path("/repo"), "slow.py") == "pending"

    def test_deleted_since_absolute_resolves_via_history(self, tmp_path):
        # An absolute path under a repo, gone from disk, found in git history.
        repo = tmp_path / "repo"
        repo.mkdir()
        abspath = str(repo / "deleted.py")  # never created on disk
        results = [
            MagicMock(returncode=1),                       # cat-file miss
            MagicMock(returncode=0, stdout="abc123 log"),   # history hit
        ]
        with patch("subprocess.run", side_effect=results):
            assert av.verify_file(abspath, [repo]) == "true"
