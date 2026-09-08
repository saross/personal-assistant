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
import os
import subprocess
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


# ============================================================================
# unique_suffix_match — collision-guarded prefix recovery (item 21b)
# ============================================================================


class TestUniqueSuffixMatch:
    """Pure suffix matcher: recovers a prefix-dropped ref only on a unique hit."""

    TRACKED = [
        "wiki/continuity.md",
        "src/cc_session_toolkit/extraction.py",
        "hooks/extraction.py",
        "scripts/anchor_verify.py",
    ]

    def test_unique_basename_recovers(self):
        match = av.unique_suffix_match("continuity.md", self.TRACKED)
        assert match.path == "wiki/continuity.md"
        # Unattributed candidates can never be proved same-project.
        assert match.scope == "cross-repo"

    def test_ambiguous_basename_returns_none(self):
        # Two tracked extraction.py → can't safely pick one.
        assert av.unique_suffix_match("extraction.py", self.TRACKED) is None

    def test_dir_qualified_ref_disambiguates(self):
        # The directory context narrows the ambiguous basename to one file.
        assert av.unique_suffix_match(
            "cc_session_toolkit/extraction.py", self.TRACKED
        ).path == "src/cc_session_toolkit/extraction.py"

    def test_absent_basename_returns_none(self):
        assert av.unique_suffix_match("ghost.md", self.TRACKED) is None

    def test_exact_path_matches(self):
        assert av.unique_suffix_match(
            "scripts/anchor_verify.py", self.TRACKED
        ).path == "scripts/anchor_verify.py"

    def test_partial_name_does_not_match_across_boundary(self):
        # "tion.py" must NOT match "extraction.py" — only whole path segments.
        assert av.unique_suffix_match("tion.py", self.TRACKED) is None

    def test_trailing_slash_normalised(self):
        # A directory-shaped ref recovers nothing (ls-files lists files).
        assert av.unique_suffix_match("wiki/", self.TRACKED) is None

    def test_empty_ref_returns_none(self):
        assert av.unique_suffix_match("", self.TRACKED) is None


# ============================================================================
# Pathspec magic — a glob must never verify as a file (finding AN1/AN11/AN12)
# ============================================================================


def _throwaway_repo(root: Path) -> Path:
    """Create a throwaway git repository with one committed file.

    The repository lives entirely under pytest's ``tmp_path``; nothing here
    touches a real checkout. It carries ``scripts/real.py`` at HEAD, which is
    what the glob refs below would match if git were allowed to read them as
    patterns.
    """
    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    # The marker keeps two repositories seeded in the same second from
    # producing byte-identical trees, and so identical commit hashes.
    (repo / "scripts" / "real.py").write_text(
        f"x = 1\n# {root.name}\n", encoding="utf-8",
    )
    env = {
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "PATH": os.environ.get("PATH", ""), "HOME": str(root),
    }
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "seed"], check=True, env=env,
    )
    return repo


class TestPathspecMagicNeverVerifies:
    """A ref git would read as a pattern must not resolve to "true".

    Against the real git binary in a throwaway repository. The mutation each
    test kills: dropping ``--literal-pathspecs`` from the ``git log`` probe in
    :func:`anchor_verify._git_knows_path` (every glob below then matches
    ``scripts/real.py`` in history and returns "true").
    """

    @pytest.mark.parametrize("ref", [
        "scripts/*.py",
        "*.py",
        "scripts/?eal.py",
        "scripts/[r]eal.py",
        ":(glob)**/real.py",
        ":(exclude)zzz",
    ])
    def test_glob_refs_resolve_false(self, tmp_path, ref):
        repo = _throwaway_repo(tmp_path)
        assert av.verify_file(ref, [repo]) == "false"

    def test_the_real_file_still_resolves_true(self, tmp_path):
        """The control: literal pathspecs must not break honest anchors."""
        repo = _throwaway_repo(tmp_path)
        assert av.verify_file("scripts/real.py", [repo]) == "true"

    def test_a_deleted_file_still_resolves_through_history(self, tmp_path):
        """The history probe survives literalisation (its whole purpose)."""
        repo = _throwaway_repo(tmp_path)
        (repo / "scripts" / "real.py").unlink()
        env = {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
        }
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-qm", "drop"], check=True, env=env,
        )
        assert av.verify_file("scripts/real.py", [repo]) == "true"

    def test_a_ref_that_escapes_the_repo_is_false(self, tmp_path):
        """``../outside`` must not stat a file that lives in no repository.

        Kills the AN11 mutation: ``(repo / expanded).exists()`` without
        normalisation, which returned "true" for the file below.
        """
        repo = _throwaway_repo(tmp_path)
        (tmp_path / "outside.txt").write_text("secret\n", encoding="utf-8")
        assert av.verify_file("../outside.txt", [repo]) == "false"

    def test_the_shape_gate_rejects_pathspec_magic(self):
        """The write-side half: such a ref never reaches the resolver."""
        for ref in ("scripts/*.py", "scripts/?eal.py", "scripts/[r]eal.py",
                    ":(glob)**/real.py", ":(exclude)zzz"):
            assert av._looks_like_file_ref(ref) is False
            assert av.wellformed_anchor({"type": "file", "ref": ref}) == (
                False, "malformed-file-ref")


class TestCommitRefHexFloor:
    """Four hex characters is a word, not a commit (finding AN12)."""

    @pytest.mark.parametrize("ref", ["cafe", "beef", "face", "d0d0", "abcdef"])
    def test_short_hex_is_not_a_commit_ref(self, ref):
        """Kills the mutation restoring ``len(s) < 4`` in _looks_like_hash."""
        assert av._looks_like_hash(ref) is False
        assert av.wellformed_anchor({"type": "commit", "ref": ref}) == (
            False, "malformed-commit-ref")
        assert av.verify_commit(ref, [Path("/nonexistent-repo")]) == "false"

    def test_seven_hex_is_still_a_commit_ref(self):
        """The floor is seven, not eight: git's own abbreviation length."""
        assert av._looks_like_hash("abc1234") is True

    def test_a_short_word_is_still_a_plausible_filename(self):
        """The file gate keeps its looser six-character id floor."""
        assert av._looks_like_file_ref("cafe") is True


# ============================================================================
# "pending" vs "false" — a check that could not run is not an absent file
# (finding AN3)
# ============================================================================


class TestTransientFailureIsPending:
    """Every way a check can fail to complete must read "pending".

    ``"false"`` is committal: it demotes the memory's confidence, feeds the
    drift sweep's append-only trend log, and makes ``recover_anchors`` rewrite
    the anchor. It must mean "we looked everywhere and it was not there".

    The mutation each test kills: restoring ``except (FileNotFoundError,
    OSError): return "false"`` in ``_git_knows_path`` / ``verify_commit``, or
    the unconditional trailing ``return "false"`` in the history probe.
    """

    def test_missing_git_binary_is_pending(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("git")):
            assert av._git_knows_path(Path("/repo"), "a.py") == "pending"

    def test_unreadable_repository_is_pending(self):
        with patch("subprocess.run", side_effect=PermissionError("denied")):
            assert av._git_knows_path(Path("/repo"), "a.py") == "pending"

    def test_oserror_mid_history_probe_is_pending(self):
        results = [MagicMock(returncode=1), OSError("mount went away")]

        def run(*_a, **_kw):
            item = results.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch("subprocess.run", side_effect=run):
            assert av._git_knows_path(Path("/repo"), "a.py") == "pending"

    def test_unrecognised_git_exit_code_is_pending(self):
        """rc 128 without the "did not match" text: a broken repository."""
        results = [
            MagicMock(returncode=1),
            MagicMock(returncode=128, stdout="",
                      stderr="fatal: not a git repository"),
        ]
        with patch("subprocess.run", side_effect=results):
            assert av._git_knows_path(Path("/repo"), "a.py") == "pending"

    def test_unmatched_pathspec_is_a_completed_check(self):
        """rc 128 WITH the marker means "checked, and absent"."""
        results = [
            MagicMock(returncode=1),
            MagicMock(returncode=128, stdout="",
                      stderr="fatal: ghost.py: did not match any file(s) "
                             "known to git"),
        ]
        with patch("subprocess.run", side_effect=results):
            assert av._git_knows_path(Path("/repo"), "ghost.py") == "false"

    def test_verify_file_is_pending_when_every_repo_failed(self, tmp_path):
        """The aggregate: no repository could answer, so neither can we."""
        repo = tmp_path / "repo"
        repo.mkdir()
        with patch("subprocess.run", side_effect=OSError("unmounted")):
            assert av.verify_file("scripts/gone.py", [repo]) == "pending"

    def test_verify_file_relative_with_no_repos_is_pending(self):
        """An empty repo set checks nothing — it must not condemn the anchor.

        Kills the mutation that returns "false" when discovery yields [].
        """
        assert av.verify_file("scripts/gone.py", []) == "pending"

    def test_verify_file_is_false_only_when_every_repo_answered(self, tmp_path):
        """The control: a completed check that found nothing is still false."""
        repo = _throwaway_repo(tmp_path)
        assert av.verify_file("scripts/ghost.py", [repo]) == "false"

    def test_verify_commit_transient_failure_is_pending(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("git")):
            assert av.verify_commit("abc1234", [Path("/repo")]) == "pending"

    def test_verify_commit_broken_repo_is_pending(self):
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=128)
            assert av.verify_commit("abc1234", [Path("/repo")]) == "pending"

    def test_verify_commit_with_no_repos_is_pending(self):
        assert av.verify_commit("abc1234", []) == "pending"

    def test_verify_commit_absent_everywhere_is_false(self, tmp_path):
        """The control, against a real repository that lacks the object."""
        repo = _throwaway_repo(tmp_path)
        assert av.verify_commit("abc1234def", [repo]) == "false"

    def test_a_pending_memory_verdict_does_not_demote_confidence(self):
        """bind_confidence must not lower a record on an incomplete check.

        Kills the mutation ``return "medium"`` for the pending branch: a
        record that reads "high" today would be written back "medium" by the
        next recovery pass simply because a mount was missing.
        """
        assert av.bind_confidence("pending", current="high") == "high"
        assert av.bind_confidence("pending", current="low") == "medium"
        assert av.bind_confidence("pending") == "medium"
        # "false" is committal and still demotes, whatever the record says.
        assert av.bind_confidence("false", current="high") == "low"


# ============================================================================
# verify_commit across a real repo set, and the zero-valid-anchor guard
# (findings ANT-L1 / ANT-Mh)
# ============================================================================


class TestVerifyCommitAcrossARepoSet:
    """The repo set is searched, not just its first member."""

    def _head(self, repo: Path) -> str:
        """The full hash of *repo*'s tip commit."""
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    def test_a_hash_in_the_second_repository_resolves(self, tmp_path):
        """Kills the mutation checking only ``repo_set[0]``."""
        first = _throwaway_repo(tmp_path / "one")
        second = _throwaway_repo(tmp_path / "two")
        target = self._head(second)
        assert av.verify_commit(target, [first, second]) == "true"

    def test_the_repo_set_is_not_ignored(self, tmp_path):
        """Kills the mutation that drops the repo_set argument entirely."""
        first = _throwaway_repo(tmp_path / "one")
        second = _throwaway_repo(tmp_path / "two")
        target = self._head(second)
        assert av.verify_commit(target, [first]) == "false"

    def test_a_short_prefix_of_a_real_commit_resolves(self, tmp_path):
        """Seven characters is a genuine abbreviation git can disambiguate."""
        repo = _throwaway_repo(tmp_path)
        assert av.verify_commit(self._head(repo)[:7], [repo]) == "true"


class TestZeroValidAnchorsIsNotVerified:
    """An anchors list with nothing checkable is None, never "true"."""

    def test_only_unknown_types_returns_none(self):
        """Kills the mutation removing the saw_any_valid_anchor guard.

        Without it the loop checks nothing, falls through to the trailing
        branch, and reports "true" — a memory verified on the strength of
        anchors no verifier ever looked at (finding ANT-Mh).
        """
        record = {
            "id": "x",
            "anchors": [
                {"type": "telepathy", "ref": "alpha-centauri"},
                {"type": "vibes", "ref": "a good feeling"},
            ],
        }
        assert av.verify_memory(record, []) is None

    def test_only_malformed_entries_returns_none(self):
        record = {"id": "x", "anchors": ["not a dict", {"type": "file"}]}
        assert av.verify_memory(record, []) is None
