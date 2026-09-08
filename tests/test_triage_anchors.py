"""
Tests for scripts/triage_anchors.py — the item-12 read-only triage classifier.

Covers the pure logic (``classify_anchor`` with an injected resolver, and
``dispose``). The heavy I/O paths (broad repo scan, corpus walk, git
subprocesses in ``main``) are not exercised here — they reuse already-tested
``anchor_verify`` resolvers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

_path = Path(__file__).parent.parent / "scripts" / "triage_anchors.py"
_spec = importlib.util.spec_from_file_location("triage_anchors", _path)
ta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ta)


class TestClassifyAnchor:
    def test_malformed_short_circuits_before_resolve(self):
        # A malformed anchor is tagged without ever calling the resolver.
        called = []

        def resolve(_a):
            called.append(1)
            return "true"

        tag = ta.classify_anchor({"type": "commit", "ref": "rome-script"}, resolve)
        assert tag == "malformed"
        assert called == []  # resolver not invoked for malformed anchors

    @pytest.mark.parametrize("result,expected", [
        ("true", "broad-true"),
        ("false", "broad-false"),
        ("pending", "pending"),
    ])
    def test_wellformed_uses_resolver_result(self, result, expected):
        anchor = {"type": "commit", "ref": "7078d39"}
        assert ta.classify_anchor(anchor, lambda _a: result) == expected


class TestDispose:
    def test_broad_false_is_unresolvable(self):
        assert ta.dispose(["broad-true", "broad-false"]) == "unresolvable"

    def test_malformed_only_is_clean_after_strip(self):
        assert ta.dispose(["malformed"]) == "clean-after-strip"

    def test_malformed_plus_good_is_clean_after_strip(self):
        # Strip the malformed one and the record re-verifies on the good anchor.
        assert ta.dispose(["malformed", "broad-true"]) == "clean-after-strip"

    def test_all_broad_true_is_cross_repo(self):
        # No malformed, no broad-false: false only under the narrow verifier.
        assert ta.dispose(["broad-true", "pending"]) == "cross-repo"

    def test_malformed_plus_broad_false_is_unresolvable(self):
        # Stripping the malformed one still leaves a well-formed anchor that
        # resolves nowhere → genuinely suspect, not clean.
        assert ta.dispose(["malformed", "broad-false"]) == "unresolvable"


class TestRecoveryStatus:
    """item-21b three-way prefix-recovery classification (read-only)."""

    INDEX = {
        "continuity.md": ["wiki/continuity.md"],
        "extraction.py": ["src/cc_session_toolkit/extraction.py", "hooks/extraction.py"],
        "anchor_verify.py": ["scripts/anchor_verify.py"],
    }

    def test_unique_match_is_recoverable(self):
        assert ta.recovery_status("continuity.md", self.INDEX) == (
            "recoverable", "wiki/continuity.md")

    def test_basename_collision_is_ambiguous(self):
        assert ta.recovery_status("extraction.py", self.INDEX) == ("ambiguous", None)

    def test_dir_context_disambiguates_to_recoverable(self):
        assert ta.recovery_status("cc_session_toolkit/extraction.py", self.INDEX) == (
            "recoverable", "src/cc_session_toolkit/extraction.py")

    def test_unknown_basename_is_absent(self):
        assert ta.recovery_status("ghost.md", self.INDEX) == ("absent", None)

    def test_empty_ref_is_absent(self):
        assert ta.recovery_status("", self.INDEX) == ("absent", None)


# ============================================================================
# Repo discovery — one source of truth, and never silently empty
# (findings ANT5 / AN7 / ANT-Md)
# ============================================================================


def _init_repo(path: Path, relpath: str = "README.md") -> Path:
    """Create a throwaway git repository at *path* tracking one file."""
    target = path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# seeded\n", encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "PATH": os.environ.get("PATH", ""), "HOME": str(path.parent),
    }
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-qm", "seed"], check=True, env=env,
    )
    return path


class TestBroadRepoSet:
    """One discovery pass, and an empty result is an error."""

    def test_it_delegates_to_project_id(self, tmp_path, monkeypatch) -> None:
        """Kills the mutation reinstating a second, independent discovery.

        The live hook resolves anchors through ``project_id.repo_set``; a
        privately-maintained copy here would desynchronise the moment a root
        was added to one of them (finding ANT5).
        """
        discovered = [_init_repo(tmp_path / "code" / "widget")]
        monkeypatch.setattr(ta.project_id, "repo_set", lambda: list(discovered))
        monkeypatch.setattr(ta, "PA_DIR", tmp_path / "no-such-checkout")
        assert ta.broad_repo_set() == discovered

    def test_a_worktree_copy_finds_its_own_checkout(
        self, tmp_path, monkeypatch,
    ) -> None:
        """A copy under ~/worktrees must resolve against ITS repository.

        Kills the mutation that drops the PA_DIR addition: HOME-based
        discovery cannot see a worktree, so the copy would verify anchors
        against a different checkout, or against nothing at all.
        """
        home_repo = _init_repo(tmp_path / "home" / "personal-assistant")
        worktree = _init_repo(tmp_path / "worktrees" / "pa-copy")
        monkeypatch.setattr(ta.project_id, "repo_set", lambda: [home_repo])
        monkeypatch.setattr(ta, "PA_DIR", worktree)
        repos = ta.broad_repo_set()
        assert home_repo in repos and worktree in repos

    def test_an_empty_discovery_raises(self, tmp_path, monkeypatch) -> None:
        """Kills the mutation returning [].

        An empty repo set makes every anchor resolve nowhere, which the drift
        sweep would record as a ~100 % drift spike in an append-only log
        (findings AN7 / C5).
        """
        monkeypatch.setattr(ta.project_id, "repo_set", list)
        monkeypatch.setattr(ta, "PA_DIR", tmp_path / "no-such-checkout")
        with pytest.raises(ta.RepoSetUnavailable):
            ta.broad_repo_set()


class TestBuildBasenameIndex:
    """The index carries attribution, and a failed repository is announced."""

    def test_entries_name_the_repository_they_came_from(self, tmp_path) -> None:
        """Kills the mutation pooling paths without attribution (AN2)."""
        repo_a = _init_repo(tmp_path / "a", "src/util.py")
        repo_b = _init_repo(tmp_path / "b", "pkg/src/util.py")
        index = ta.build_basename_index([repo_a, repo_b])
        assert {(c.repo, c.path) for c in index["util.py"]} == {
            (str(repo_a), "src/util.py"), (str(repo_b), "pkg/src/util.py"),
        }

    def test_a_repository_that_cannot_be_listed_is_logged(
        self, tmp_path, capsys,
    ) -> None:
        """Kills the mutation swallowing the failure silently (ANT-Md).

        A skipped repository narrows the recovery namespace invisibly, which
        looks exactly like a repository with no tracked files.
        """
        good = _init_repo(tmp_path / "good", "notes.md")
        missing = tmp_path / "not-a-repo"
        missing.mkdir()
        index = ta.build_basename_index([good, missing])
        assert "notes.md" in index
        assert "WARN" in capsys.readouterr().err


class TestResolverMemoisation:
    """The cache key has to carry the anchor type (finding ANT-L7)."""

    def test_a_commit_and_a_file_with_the_same_ref_do_not_share_an_answer(
        self, monkeypatch,
    ) -> None:
        """Kills the mutation memoising on the ref alone."""
        monkeypatch.setattr(ta.av, "verify_commit", lambda ref, repos: "true")
        monkeypatch.setattr(ta.av, "verify_file", lambda ref, repos: "false")
        resolve = ta._make_resolver([])
        ref = "abc1234"
        assert resolve({"type": "commit", "ref": ref}) == "true"
        assert resolve({"type": "file", "ref": ref}) == "false"


class TestMainNeverWrites:
    """The module docstring's central claim: a pure read path."""

    def test_a_triage_run_leaves_the_tree_byte_identical(
        self, tmp_path, monkeypatch, capsys,
    ) -> None:
        """Kills a mutation injecting any write into main().

        Snapshots every file under the fake HOME (path, size, mtime, bytes)
        before and after, so an appended line, a rewritten corpus, or a new
        report file all fail.
        """
        home = tmp_path / "home"
        corpus_dir = home / "personal-assistant" / "data" / "memories"
        corpus_dir.mkdir(parents=True)
        (corpus_dir / "memories.jsonl").write_text(
            json.dumps({
                "id": "2031-08-01-aaaabbbbcccc",
                "verified": "false",
                "anchors": [{"type": "file", "ref": "notes.md"},
                            {"type": "commit", "ref": "not-a-hash"}],
            }) + "\n",
            encoding="utf-8",
        )
        repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(ta, "broad_repo_set", lambda: [repo])

        def snapshot() -> dict:
            return {
                str(p): p.read_bytes()
                for p in sorted(home.rglob("*")) if p.is_file()
            }

        before = snapshot()
        ta.main()
        assert snapshot() == before
        assert "verified=false anchored records" in capsys.readouterr().out
