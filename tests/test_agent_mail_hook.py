"""
Tests for session-start-agent-mail.py — read-time validation of peer mail.

The hook lists unread messages other agents have sent to Claude. These
tests pin the validation rules shared with the Codex-side hook: plain
(non-symlink) directories and files only, bounded From/To headers, a size
cap, and receipts that count only when they are regular files.

Tests the pure function only; the hook is not executed end-to-end.
"""

import importlib
import os
from pathlib import Path

# conftest.py adds hooks/ to sys.path; the filename is hyphenated.
mail = importlib.import_module("session-start-agent-mail")

VALID = "From: codex\nTo: claude\nDate: 2026-09-07T00:00:00Z\nRe: test\n\nbody\n"


def make_mailbox(root: Path, sender: str = "codex") -> tuple[Path, Path]:
    """Create <root>/<sender>/outbox/claude and <root>/claude/seen/<sender>."""
    outbox = root / sender / "outbox" / "claude"
    seen = root / "claude" / "seen" / sender
    outbox.mkdir(parents=True)
    seen.mkdir(parents=True)
    return outbox, seen


class TestUnreadMessages:
    def test_valid_message_is_listed_until_receipted(self, tmp_path):
        outbox, seen = make_mailbox(tmp_path)
        message = outbox / "20260907T000000Z-codex-test.md"
        message.write_text(VALID)
        assert mail.unread_messages(tmp_path) == [message]

        (seen / message.name).write_text("read\n")
        assert mail.unread_messages(tmp_path) == []

    def test_wrong_from_or_to_header_is_not_mail(self, tmp_path):
        outbox, _ = make_mailbox(tmp_path)
        (outbox / "a-wrong-from.md").write_text(VALID.replace("From: codex", "From: shawn"))
        (outbox / "b-wrong-to.md").write_text(VALID.replace("To: claude", "To: codex"))
        (outbox / "c-no-headers.md").write_text("just a body\n")
        assert mail.unread_messages(tmp_path) == []

    def test_headers_after_first_blank_line_do_not_count(self, tmp_path):
        outbox, _ = make_mailbox(tmp_path)
        (outbox / "late-headers.md").write_text("Re: x\n\nFrom: codex\nTo: claude\n")
        assert mail.unread_messages(tmp_path) == []

    def test_only_the_header_prefix_is_read(self, tmp_path, monkeypatch):
        outbox, _ = make_mailbox(tmp_path)
        monkeypatch.setattr(mail, "MAX_HEADER_BYTES", 8)
        (outbox / "long-headers.md").write_text(VALID)
        # Eight bytes is "From: co" — the From header is truncated, so no match.
        assert mail.unread_messages(tmp_path) == []

    def test_symlinked_message_outbox_and_sender_are_ignored(self, tmp_path):
        outbox, _ = make_mailbox(tmp_path)
        real = tmp_path / "elsewhere.md"
        real.write_text(VALID)
        os.symlink(real, outbox / "linked.md")
        assert mail.unread_messages(tmp_path) == []

        # A whole sender subtree reached through a symlink is not a sender.
        other_root = tmp_path / "other"
        other_outbox, _ = make_mailbox(other_root, sender="third")
        (other_outbox / "real.md").write_text(VALID.replace("codex", "third"))
        os.symlink(other_root / "third", tmp_path / "third")
        assert mail.unread_messages(tmp_path) == []

    def test_symlinked_receipt_directory_does_not_hide_mail(self, tmp_path):
        outbox, seen = make_mailbox(tmp_path)
        message = outbox / "m.md"
        message.write_text(VALID)
        # Replace the receipt directory with a symlink holding a receipt.
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        (decoy / message.name).write_text("read\n")
        seen.rmdir()
        os.symlink(decoy, seen)
        assert mail.unread_messages(tmp_path) == [message]

    def test_symlinked_receipt_file_is_not_a_receipt(self, tmp_path):
        outbox, seen = make_mailbox(tmp_path)
        message = outbox / "m.md"
        message.write_text(VALID)
        target = tmp_path / "receipt-target"
        target.write_text("read\n")
        os.symlink(target, seen / message.name)
        assert mail.unread_messages(tmp_path) == [message]

    def test_oversized_and_non_markdown_files_are_ignored(self, tmp_path, monkeypatch):
        outbox, _ = make_mailbox(tmp_path)
        monkeypatch.setattr(mail, "MAX_MESSAGE_BYTES", len(VALID))
        (outbox / "fits.md").write_text(VALID)
        (outbox / "too-big.md").write_text(VALID + "x")
        (outbox / "notes.txt").write_text(VALID)
        assert [m.name for m in mail.unread_messages(tmp_path)] == ["fits.md"]

    def test_own_subtree_and_missing_root_are_skipped(self, tmp_path):
        # Claude's own outbox to itself is never mail.
        own = tmp_path / "claude" / "outbox" / "claude"
        own.mkdir(parents=True)
        (own / "self.md").write_text("From: claude\nTo: claude\n\nx\n")
        assert mail.unread_messages(tmp_path) == []
        assert mail.unread_messages(tmp_path / "absent") == []

    def test_ordered_by_sender_then_filename(self, tmp_path):
        outbox_c, _ = make_mailbox(tmp_path, sender="codex")
        outbox_a, _ = make_mailbox(tmp_path, sender="astra")
        (outbox_c / "2.md").write_text(VALID)
        (outbox_c / "1.md").write_text(VALID)
        (outbox_a / "9.md").write_text(VALID.replace("codex", "astra"))
        names = [f"{m.parent.parent.parent.name}/{m.name}" for m in mail.unread_messages(tmp_path)]
        assert names == ["astra/9.md", "codex/1.md", "codex/2.md"]
