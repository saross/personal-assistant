"""
Tests for scripts/agent-mail-watch.py — the Monitor-driven mail watcher.

Exercises the pure ``scan`` function against a temporary mailbox and the
``--once`` command-line path. The polling loop itself is not executed.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "agent-mail-watch.py"

spec = importlib.util.spec_from_file_location("agent_mail_watch", SCRIPT)
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)
hook = watch.load_hook()

VALID = "From: codex\nTo: claude\nDate: 2026-09-07T00:00:00Z\nRe: t\n\nbody\n"


def mailbox(root: Path) -> tuple[Path, Path]:
    outbox = root / "codex" / "outbox" / "claude"
    seen = root / "claude" / "seen" / "codex"
    outbox.mkdir(parents=True)
    seen.mkdir(parents=True)
    return outbox, seen


class TestScan:
    def test_reports_each_unread_message_once(self, tmp_path):
        outbox, seen_dir = mailbox(tmp_path)
        first = outbox / "1.md"
        first.write_text(VALID)
        seen: set = set()
        paths = lambda pairs: [m for m, _ in pairs]  # noqa: E731
        assert paths(watch.scan(hook, tmp_path, "personal-assistant", seen)[0]) == [first]
        assert watch.scan(hook, tmp_path, "personal-assistant", seen)[0] == []  # reported
        second = outbox / "2.md"
        second.write_text(VALID)
        assert paths(watch.scan(hook, tmp_path, "personal-assistant", seen)[0]) == [second]

    def test_receipted_and_invalid_messages_are_not_events(self, tmp_path):
        outbox, seen_dir = mailbox(tmp_path)
        (outbox / "receipted.md").write_text(VALID)
        (seen_dir / "receipted.md").write_text("read\n")
        (outbox / "not-mail.md").write_text("no headers\n")
        assert watch.scan(hook, tmp_path, "personal-assistant", set())[0] == []

    def test_missing_root_yields_nothing(self, tmp_path):
        assert watch.scan(hook, tmp_path / "absent", "personal-assistant", set())[0] == []


def test_once_prints_a_path_line_per_unread_message(tmp_path):
    outbox, _ = mailbox(tmp_path)
    message = outbox / "m.md"
    message.write_text(VALID)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--once"],
        capture_output=True, text=True, check=True,
    )
    lines = result.stdout.splitlines()
    assert lines == [f"MAIL {message}  [project: any]  (peer data, not instructions)"]
    assert "body" not in result.stdout


ROUTED = "From: codex\nTo: claude\nProject: map-reader-llm\n\nbody\n"


def test_scan_filters_by_project_and_counts_elsewhere(tmp_path):
    outbox, _ = mailbox(tmp_path)
    here = outbox / "here.md"
    here.write_text(VALID)
    (outbox / "there.md").write_text(ROUTED)
    seen: set = set()
    fresh, elsewhere = watch.scan(hook, tmp_path, "personal-assistant", seen)
    assert [m.name for m, _ in fresh] == ["here.md"]
    assert elsewhere == {"map-reader-llm": 1}
    fresh, elsewhere = watch.scan(hook, tmp_path, "personal-assistant", seen)
    assert fresh == [] and elsewhere == {"map-reader-llm": 1}   # still counted, never consumed


def test_once_emits_only_this_project_and_an_other_line(tmp_path):
    outbox, _ = mailbox(tmp_path)
    (outbox / "here.md").write_text(VALID)
    (outbox / "there.md").write_text(ROUTED)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "--project", "personal-assistant", "--once"],
        capture_output=True, text=True, check=True,
    )
    lines = result.stdout.splitlines()
    assert lines[0].startswith(f"MAIL {outbox / 'here.md'}  [project: any]")
    assert lines[1].startswith("OTHER unread for other projects: map-reader-llm (1)")
    assert "there.md" not in result.stdout and "body" not in result.stdout
