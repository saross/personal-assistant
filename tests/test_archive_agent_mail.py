"""
Tests for scripts/archive-agent-mail.py — the append-only mail archive.

Builds a throwaway mailbox and archive per test. The ``--commit`` path is
exercised against a throwaway git repository, never the real data submodule.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "archive-agent-mail.py"
spec = importlib.util.spec_from_file_location("archive_agent_mail", SCRIPT)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)

MESSAGE = ("From: codex\nTo: claude\nProject: map-reader-llm\nLane: fable\n"
           "Date: 2026-09-08T00:00:00Z\nRe: hello\n\nbody text\n")


def mailbox(root: Path) -> tuple[Path, Path]:
    outbox = root / "codex" / "outbox" / "claude"
    seen = root / "claude" / "seen" / "codex"
    outbox.mkdir(parents=True)
    seen.mkdir(parents=True)
    return outbox, seen


def test_copies_messages_and_receipts_and_indexes_them(tmp_path):
    root, store = tmp_path / "mail", tmp_path / "archive"
    outbox, seen = mailbox(root)
    (outbox / "m1.md").write_text(MESSAGE)
    (seen / "m1.md").write_text("read 2026-09-08T00:05Z by claude — acted\n")
    (outbox / "m2.md").write_text(MESSAGE.replace("Re: hello", "Re: second"))
    assert archive.copy_new(root, store) == (3, 0)
    records = archive.build_index(store)
    assert [r["subject"] for r in records] == ["hello", "second"]
    first = records[0]
    assert first["from"] == "codex" and first["to"] == "claude"
    assert first["project"] == "map-reader-llm" and first["lane"] == "fable"
    assert first["receipt"]["path"] == "claude/seen/codex/m1.md"
    assert first["receipt"]["note"].startswith("read 2026-09-08T00:05Z")
    assert first["receipt"]["when"] == "2026-09-08T00:05Z"
    assert records[1]["receipt"] is None
    assert "body text" not in json.dumps(records)


def test_append_only_and_idempotent(tmp_path):
    root, store = tmp_path / "mail", tmp_path / "archive"
    outbox, _ = mailbox(root)
    (outbox / "m1.md").write_text(MESSAGE)
    assert archive.copy_new(root, store) == (1, 0)
    assert archive.copy_new(root, store) == (0, 0)          # nothing new
    (outbox / "m1.md").unlink()                             # source vanishes
    assert archive.copy_new(root, store) == (0, 0)
    assert (store / "codex/outbox/claude/m1.md").exists()   # archive keeps it
    (outbox / "m1.md").write_text(MESSAGE + "edited\n")     # bytes change
    assert archive.copy_new(root, store) == (0, 1)


def test_symlinks_and_non_markdown_are_ignored(tmp_path):
    root, store = tmp_path / "mail", tmp_path / "archive"
    outbox, _ = mailbox(root)
    (outbox / "m1.md").write_text(MESSAGE)
    (outbox / "notes.txt").write_text(MESSAGE)
    (tmp_path / "elsewhere.md").write_text(MESSAGE)
    os.symlink(tmp_path / "elsewhere.md", outbox / "linked.md")
    assert archive.copy_new(root, store) == (1, 0)


def test_index_is_regenerated_and_stable(tmp_path):
    root, store = tmp_path / "mail", tmp_path / "archive"
    outbox, _ = mailbox(root)
    (outbox / "m1.md").write_text(MESSAGE)
    archive.copy_new(root, store)
    assert archive.write_index(store, archive.build_index(store)) is True
    path = store / "index.jsonl"
    first = path.read_text()
    assert archive.write_index(store, archive.build_index(store)) is False
    assert path.read_text() == first
    record = json.loads(first.splitlines()[0])
    assert record["sent"] == ""            # fixture name carries no timestamp
    (outbox / "20260908T010203.000000Z-codex-x.md").write_text(MESSAGE)
    archive.copy_new(root, store)
    stamped = [r for r in archive.build_index(store) if r["path"].endswith("codex-x.md")]
    assert stamped[0]["sent"] == "2026-09-08T01:02:03Z"
    assert json.loads(first.splitlines()[0])["path"] == "codex/outbox/claude/m1.md"


def test_commit_uses_an_explicit_pathspec(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.test",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.test"}
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, env=env)
    (repo / "unrelated.txt").write_text("pending edit, must not be swept\n")
    store = repo / "agent-mail"
    root = tmp_path / "mail"
    outbox, _ = mailbox(root)
    (outbox / "m1.md").write_text(MESSAGE)
    archive.copy_new(root, store)
    archive.write_index(store, archive.build_index(store))
    assert archive.commit(store, "test") is True
    assert archive.commit(store, "test") is False            # nothing new to commit
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True,
                             text=True, check=True).stdout.split()
    assert "agent-mail/index.jsonl" in tracked
    assert "unrelated.txt" not in tracked


def test_cli_reports_summary_without_bodies(tmp_path):
    root, store = tmp_path / "mail", tmp_path / "archive"
    outbox, _ = mailbox(root)
    (outbox / "m1.md").write_text(MESSAGE)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--archive", str(store)],
        capture_output=True, text=True, check=True)
    assert result.stdout.strip() == (
        "agent-mail archive: 1 added, 0 changed; 1 messages, 0 receipted")
    assert "body text" not in result.stdout
