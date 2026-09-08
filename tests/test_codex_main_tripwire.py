"""
Tests for session-start-codex-main-tripwire.py — the detection layer behind
the "Codex changes to PA arrive by branch + PR" norm (ruled 2026-09-07).

Builds a throwaway git repository per test and exercises the pure function
``flagged_commits``; the hook's fetch and output paths are not executed.
"""

import importlib
import os
import subprocess
from pathlib import Path

import pytest

# conftest.py adds hooks/ to sys.path; the filename is hyphenated.
tripwire = importlib.import_module("session-start-codex-main-tripwire")

SHAWN = {"GIT_AUTHOR_NAME": "Shawn Ross", "GIT_AUTHOR_EMAIL": "shawn@example.test",
         "GIT_COMMITTER_NAME": "Shawn Ross", "GIT_COMMITTER_EMAIL": "shawn@example.test"}
CODEX_TRAILER = "\n\nCo-Authored-By: Sol (OpenAI Codex) <shawn@example.test>"
CLAUDE_TRAILER = "\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    merged = {**os.environ, **SHAWN, **(env or {})}
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=merged,
    ).stdout


def commit(repo: Path, name: str, message: str, env: dict | None = None) -> str:
    (repo / name).write_text(f"{name}\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message, env=env)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "base", "chore: base")
    return tmp_path


def flagged(repo: Path, acked: frozenset[str] = frozenset()) -> list[str]:
    return [hit["sha"] for hit in tripwire.flagged_commits(repo, "main", "2000-01-01", acked)]


class TestFlaggedCommits:
    def test_plain_and_claude_commits_are_not_flagged(self, repo):
        commit(repo, "a", "docs: mentions Codex in the subject only")
        commit(repo, "b", "feat: claude work" + CLAUDE_TRAILER)
        assert flagged(repo) == []

    def test_direct_codex_trailer_commit_on_main_is_flagged(self, repo):
        sha = commit(repo, "a", "feat: pushed straight to main" + CODEX_TRAILER)
        assert flagged(repo) == [sha]

    def test_codex_author_identity_is_flagged_without_trailer(self, repo):
        sha = commit(repo, "a", "feat: authored as the agent",
                     env={"GIT_AUTHOR_NAME": "Astra (OpenAI Codex)"})
        assert flagged(repo) == [sha]

    def test_codex_commit_arriving_through_a_merge_is_not_flagged(self, repo):
        git(repo, "checkout", "-q", "-b", "sol/lane")
        commit(repo, "lane", "feat: lane work" + CODEX_TRAILER)
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #1 from sol/lane", "sol/lane")
        assert flagged(repo) == []

    def test_github_web_squash_by_shawn_is_not_flagged(self, repo):
        commit(repo, "a", "feat: squashed via the web UI" + CODEX_TRAILER,
               env={"GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply@github.com"})
        assert flagged(repo) == []

    def test_acknowledged_commit_is_silenced(self, repo):
        first = commit(repo, "a", "feat: first" + CODEX_TRAILER)
        second = commit(repo, "b", "feat: second" + CODEX_TRAILER)
        assert flagged(repo, frozenset({first})) == [second]

    def test_commits_before_the_ruling_are_ignored(self, repo):
        commit(repo, "a", "feat: old" + CODEX_TRAILER,
               env={"GIT_AUTHOR_DATE": "2026-01-01T00:00:00",
                    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00"})
        assert tripwire.flagged_commits(repo, "main", "2026-09-07") == []

    def test_oldest_first_order(self, repo):
        first = commit(repo, "a", "feat: first" + CODEX_TRAILER)
        second = commit(repo, "b", "feat: second" + CODEX_TRAILER)
        assert flagged(repo) == [first, second]


class TestAcknowledge:
    def test_ack_records_full_sha_and_rejects_unknown(self, repo, tmp_path, capsys):
        sha = commit(repo, "a", "feat: reviewed" + CODEX_TRAILER)
        ack = tmp_path / "cache" / "ack"
        assert tripwire.acknowledge(sha[:7], repo=repo, path=ack) == 0
        assert tripwire.read_acks(ack) == frozenset({sha})
        assert tripwire.acknowledge("deadbeef", repo=repo, path=ack) == 1
        assert "not a commit" in capsys.readouterr().err


def test_live_pa_history_is_clean_today():
    """Guard the calibration: nothing on the real main should be flagged."""
    pa = Path.home() / "personal-assistant"
    if not (pa / ".git").exists():
        pytest.skip("no PA checkout")
    ref = tripwire.resolve_ref(pa)
    assert ref is not None
    assert tripwire.flagged_commits(pa, ref) == []


# ---- added after the 2026-09-08 audit (Lens B findings C1, C2 and lows) ----

def test_main_reports_a_direct_codex_commit_through_the_default_path(repo, monkeypatch, capsys):
    """The real entry point with default SINCE and refs: commits made now are after the ruling."""
    sha = commit(repo, "a", "feat: direct push" + CODEX_TRAILER)
    monkeypatch.setenv("PA_TRIPWIRE_REPO", str(repo))
    monkeypatch.setattr(tripwire, "ACK_FILE", repo / "no-acks")
    monkeypatch.setattr("sys.argv", ["tripwire"])
    assert tripwire.main() == 0
    out = capsys.readouterr().out
    assert "Codex-on-main tripwire" in out and "RELAY THIS TO SHAWN" in out
    assert sha[:7] in out and "feat: direct push" in out
    assert "fetch failed; local refs only" in out              # throwaway repo has no origin
    assert "--ack <sha>" in out


def test_main_is_silent_on_a_clean_repo_and_ack_silences_a_hit(repo, monkeypatch, capsys):
    monkeypatch.setenv("PA_TRIPWIRE_REPO", str(repo))
    ack = repo / "acks"
    monkeypatch.setattr(tripwire, "ACK_FILE", ack)
    monkeypatch.setattr("sys.argv", ["tripwire"])
    assert tripwire.main() == 0 and capsys.readouterr().out == ""
    sha = commit(repo, "a", "feat: direct push" + CODEX_TRAILER)
    monkeypatch.setattr("sys.argv", ["tripwire", "--ack", sha[:7]])
    monkeypatch.setattr(tripwire, "REPO", repo)
    assert tripwire.main() == 0
    assert "acknowledged" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["tripwire"])
    assert tripwire.main() == 0 and capsys.readouterr().out == ""


def test_merge_commit_carrying_a_codex_trailer_is_not_flagged(repo):
    git(repo, "checkout", "-q", "-b", "sol/lane")
    commit(repo, "lane", "feat: lane work")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #1" + CODEX_TRAILER, "sol/lane")
    assert flagged(repo) == []


def test_codex_author_email_is_flagged(repo):
    sha = commit(repo, "a", "feat: by email", env={"GIT_AUTHOR_EMAIL": "bot@codex.example"})
    assert flagged(repo) == [sha]


def test_since_is_the_ruling_date():
    """Pin the activation date: moving it forward would silently disable the hook."""
    assert tripwire.SINCE.startswith("2026-09-07")


def test_window_starts_at_midnight_and_cap_keeps_the_oldest(repo):
    """SINCE must be a datetime (a bare date means 'now'); the cap must not drop old commits."""
    assert tripwire.SINCE.endswith("T00:00:00")
    first = commit(repo, "a", "feat: first" + CODEX_TRAILER)
    for i in range(3):
        commit(repo, f"b{i}", f"feat: later {i}" + CODEX_TRAILER)
    import unittest.mock as mock
    with mock.patch.object(tripwire, "MAX_COMMITS", 2):
        hits = tripwire.flagged_commits(repo, "main", "2000-01-01")
    assert [h["sha"] for h in hits][0] == first and len(hits) == 2


def test_control_characters_in_a_subject_do_not_split_or_forge_records(repo):
    sha = commit(repo, "a", "feat: odd\x01subject\n\x1b[31mfake line" + CODEX_TRAILER)
    hits = flagged(repo)
    assert hits == [sha]
    record = tripwire.flagged_commits(repo, "main", "2000-01-01")[0]
    assert "\x01" not in record["subject"] and "\x1b" not in record["subject"]


def test_ack_without_an_argument_is_a_usage_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["tripwire", "--ack"])
    assert tripwire.main() == 2
    assert "usage" in capsys.readouterr().err


def test_claude_session_commit_crediting_codex_is_not_flagged(repo):
    """A reviewed patch committed from a Claude session credits the Codex agent as
    co-author; the Claude-Session trailer marks it as Claude's own commit."""
    trailer = CODEX_TRAILER + "\nClaude-Session: https://claude.ai/code/session_x"
    commit(repo, "a", "fix: apply the peer's patch" + trailer)
    sha = commit(repo, "b", "feat: a real direct push" + CODEX_TRAILER)
    assert flagged(repo) == [sha]
