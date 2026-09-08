"""
Tests for session-start-code-state.py — the commit_at_start sidecar.

Added after the 2026-09-08 audit (H2, H24): the hook had no tests, and
SessionStart fires again with the same session_id on resume and compact,
which had been overwriting the starting commit with a later HEAD in 37 of
42 multi-write sessions. Drives main() through the real stdin payload.
"""

import importlib
import io
import json
import os
import subprocess
from pathlib import Path

# conftest.py adds hooks/ to sys.path; the filename is hyphenated.
code_state = importlib.import_module("session-start-code-state")

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.test",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.test"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env={**os.environ, **ENV}).stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a").write_text("1\n")
    git(repo, "add", "a")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def run_hook(monkeypatch, payload: dict) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return code_state.main()


def test_first_write_wins_across_resume_and_compact(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    first = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(code_state, "SIDECAR_DIR", tmp_path / "sidecars")
    monkeypatch.setattr(code_state, "LOG_FILE", tmp_path / "log.txt")
    assert run_hook(monkeypatch, {"session_id": "s1", "cwd": str(repo), "source": "startup"}) == 0
    sidecar = tmp_path / "sidecars" / "s1.json"
    assert json.loads(sidecar.read_text())["commit_at_start"] == first

    (repo / "a").write_text("2\n")
    git(repo, "commit", "-q", "-am", "second")
    assert git(repo, "rev-parse", "HEAD") != first
    for source in ("resume", "compact", "clear"):
        assert run_hook(monkeypatch, {"session_id": "s1", "cwd": str(repo), "source": source}) == 0
        assert json.loads(sidecar.read_text())["commit_at_start"] == first


def test_separate_sessions_get_separate_sidecars(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setattr(code_state, "SIDECAR_DIR", tmp_path / "sidecars")
    monkeypatch.setattr(code_state, "LOG_FILE", tmp_path / "log.txt")
    assert run_hook(monkeypatch, {"session_id": "s1", "cwd": str(repo)}) == 0
    assert run_hook(monkeypatch, {"session_id": "s2", "cwd": str(repo)}) == 0
    assert sorted(p.name for p in (tmp_path / "sidecars").glob("*.json")) == ["s1.json", "s2.json"]


def test_malformed_and_incomplete_payloads_fail_open(tmp_path, monkeypatch):
    monkeypatch.setattr(code_state, "SIDECAR_DIR", tmp_path / "sidecars")
    monkeypatch.setattr(code_state, "LOG_FILE", tmp_path / "log.txt")
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert code_state.main() == 0
    assert run_hook(monkeypatch, {"cwd": str(tmp_path)}) == 0          # no session_id
    assert run_hook(monkeypatch, {"session_id": "s3"}) == 0            # no cwd
    assert run_hook(monkeypatch, {"session_id": "s4", "cwd": str(tmp_path)}) == 0  # not a repo
    assert not (tmp_path / "sidecars").exists() or not list((tmp_path / "sidecars").glob("*"))
