"""
Tests for session-start-accountability.py — markdown parsing,
date arithmetic, and SYSTEM.md parameter reading.

Tests pure functions only; does not execute the hook end-to-end.
"""

from datetime import datetime, timedelta

# conftest.py adds hooks/ to sys.path
import importlib

# Rename to avoid clash with Python's importlib
accountability = importlib.import_module("session-start-accountability")


# ============================================================================
# Inbox Counting
# ============================================================================


class TestCountInboxItems:
    """Tests for count_inbox_items() — regex-based checkbox counting."""

    def test_counts_unchecked_only(self, tmp_path, monkeypatch):
        inbox = tmp_path / "inbox.md"
        inbox.write_text(
            "# Inbox\n\n"
            "- [ ] Unchecked item 1\n"
            "- [x] Checked item\n"
            "- [ ] Unchecked item 2\n"
        )
        monkeypatch.setattr(accountability, "INBOX_FILE", inbox)
        assert accountability.count_inbox_items() == 2

    def test_empty_inbox(self, tmp_path, monkeypatch):
        inbox = tmp_path / "inbox.md"
        inbox.write_text("# Inbox\n\nQuick captures.\n\n---\n\n")
        monkeypatch.setattr(accountability, "INBOX_FILE", inbox)
        assert accountability.count_inbox_items() == 0

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(accountability, "INBOX_FILE", tmp_path / "nope.md")
        assert accountability.count_inbox_items() == 0


# ============================================================================
# Waiting-For Counting
# ============================================================================


class TestCountWaitingItems:
    """Tests for count_waiting_items() — table parsing with placeholder detection."""

    def test_counts_real_rows(self, tmp_path, monkeypatch):
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "# Waiting For\n\n"
            "| Item | Waiting On | Since | Last Poked | Next Action |\n"
            "|------|------------|-------|------------|-------------|\n"
            "| Canvas access | ANU IT | 2026-02-07 | 2026-02-07 | Follow up |\n"
            "| \u2014 | \u2014 | \u2014 | \u2014 | \u2014 |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        assert accountability.count_waiting_items() == 1

    def test_placeholder_only(self, tmp_path, monkeypatch):
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On | Since | Last Poked | Next Action |\n"
            "|------|------------|-------|------------|-------------|\n"
            "| \u2014 | \u2014 | \u2014 | \u2014 | \u2014 |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        assert accountability.count_waiting_items() == 0

    def test_multiple_real_rows(self, tmp_path, monkeypatch):
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On | Since | Last Poked | Next Action |\n"
            "|------|------------|-------|------------|-------------|\n"
            "| Canvas access | ANU IT | 2026-02-07 | - | Follow up |\n"
            "| Review feedback | Brian | 2026-02-10 | - | Chase |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        assert accountability.count_waiting_items() == 2

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            accountability, "WAITING_FILE", tmp_path / "nope.md"
        )
        assert accountability.count_waiting_items() == 0

    def test_empty_cell_rows_skipped(self, tmp_path, monkeypatch):
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On |\n"
            "|------|------------|\n"
            "|  |  |\n"
            "| -- | -- |\n"
            "| Real item | Someone |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        assert accountability.count_waiting_items() == 1


# ============================================================================
# Focus Slot Parsing
# ============================================================================


class TestParseFocusSlots:
    """Tests for parse_focus_slots() — FOCUS.md markdown parsing."""

    def test_parses_three_filled_slots(self, tmp_path, monkeypatch, sample_focus_md):
        focus = tmp_path / "FOCUS.md"
        focus.write_text(sample_focus_md)
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)

        slots = accountability.parse_focus_slots()
        assert len(slots) == 3
        assert slots[0]["name"] == "LLM-History-Paper"
        assert slots[0]["slot_number"] == 1
        assert slots[0]["started"] == "2026-02-06"
        assert slots[0]["deadline"] == "2026-02-28"
        assert slots[1]["name"] == "fieldmark-docs-staging"
        assert slots[1]["deadline"] is None
        assert slots[2]["name"] == "ANU Teaching Prep"
        assert slots[2]["deadline"] == "2026-02-25"

    def test_skips_empty_slots(self, tmp_path, monkeypatch):
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "# Current Focus\n\n"
            "## Slot 1: LLM-History-Paper\n\n"
            "- **Started:** 2026-02-08\n"
            "- **Deadline:** 2026-02-28\n\n"
            "---\n\n"
            "## Slot 2: [Empty]\n\n"
            "---\n\n"
            "## Slot 3: [Empty]\n\n"
            "---\n"
        )
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)

        slots = accountability.parse_focus_slots()
        assert len(slots) == 1
        assert slots[0]["name"] == "LLM-History-Paper"

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(accountability, "FOCUS_FILE", tmp_path / "nope.md")
        assert accountability.parse_focus_slots() == []

    def test_no_slots(self, tmp_path, monkeypatch):
        focus = tmp_path / "FOCUS.md"
        focus.write_text("# Current Focus\n\nNothing here.\n")
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        assert accountability.parse_focus_slots() == []


# ============================================================================
# Focus Limit from SYSTEM.md
# ============================================================================


class TestGetFocusLimit:
    """Tests for get_focus_limit() — SYSTEM.md parameter reading."""

    def test_reads_limit_from_file(self, tmp_path, monkeypatch, sample_system_md):
        system = tmp_path / "SYSTEM.md"
        system.write_text(sample_system_md)
        monkeypatch.setattr(accountability, "SYSTEM_FILE", system)
        assert accountability.get_focus_limit() == 3

    def test_default_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(accountability, "SYSTEM_FILE", tmp_path / "nope.md")
        assert accountability.get_focus_limit() == accountability.DEFAULT_FOCUS_LIMIT

    def test_default_when_no_match(self, tmp_path, monkeypatch):
        system = tmp_path / "SYSTEM.md"
        system.write_text("# System Configuration\n\nNo parameters here.\n")
        monkeypatch.setattr(accountability, "SYSTEM_FILE", system)
        assert accountability.get_focus_limit() == accountability.DEFAULT_FOCUS_LIMIT

    def test_reads_different_values(self, tmp_path, monkeypatch):
        for limit in (1, 2, 5, 10):
            system = tmp_path / "SYSTEM.md"
            system.write_text(f"| focus_limit | {limit} | 2 | Max items |\n")
            monkeypatch.setattr(accountability, "SYSTEM_FILE", system)
            assert accountability.get_focus_limit() == limit


# ============================================================================
# Deadline Formatting
# ============================================================================


class TestFormatDeadlineStatus:
    """Tests for format_deadline_status() — date arithmetic and display."""

    def test_no_deadline(self):
        assert accountability.format_deadline_status(None) == ""

    def test_future_deadline_within_week(self):
        future = (datetime.now().date() + timedelta(days=5)).strftime("%Y-%m-%d")
        result = accountability.format_deadline_status(future)
        assert "in 5 days" in result

    def test_future_deadline_beyond_week(self):
        future = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
        result = accountability.format_deadline_status(future)
        assert "deadline" in result
        assert future in result  # Shows the date string for >7 days

    def test_today_deadline(self):
        today = datetime.now().date().strftime("%Y-%m-%d")
        result = accountability.format_deadline_status(today)
        assert "TODAY" in result

    def test_overdue_deadline(self):
        past = (datetime.now().date() - timedelta(days=3)).strftime("%Y-%m-%d")
        result = accountability.format_deadline_status(past)
        assert "OVERDUE" in result
        assert "3" in result

    def test_overdue_singular(self):
        yesterday = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
        result = accountability.format_deadline_status(yesterday)
        assert "1 day" in result
        assert "days" not in result

    def test_future_singular(self):
        tomorrow = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
        result = accountability.format_deadline_status(tomorrow)
        assert "1 day" in result
        assert "days" not in result

    def test_far_future_shows_date(self):
        far = (datetime.now().date() + timedelta(days=30)).strftime("%Y-%m-%d")
        result = accountability.format_deadline_status(far)
        assert "deadline" in result
        assert far in result

    def test_invalid_date(self, capsys):
        # Audit C-M4 (2026-05-02): unparseable deadlines used to return
        # an empty string, hiding the parse failure on the very surface
        # the banner exists to make loud. The fix surfaces the bad value
        # in the banner and emits a stderr WARN.
        result = accountability.format_deadline_status("not-a-date")
        assert "not-a-date" in result
        assert "UNPARSEABLE" in result
        captured = capsys.readouterr()
        assert "[accountability] WARN" in captured.err
        assert "not-a-date" in captured.err


# ============================================================================
# Days in Focus
# ============================================================================


class TestDaysInFocus:
    """Tests for days_in_focus() — 1-indexed day counting."""

    def test_today_is_day_1(self):
        today = datetime.now().date().strftime("%Y-%m-%d")
        assert accountability.days_in_focus(today) == 1

    def test_yesterday_is_day_2(self):
        yesterday = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert accountability.days_in_focus(yesterday) == 2

    def test_week_ago(self):
        week_ago = (datetime.now().date() - timedelta(days=7)).strftime("%Y-%m-%d")
        assert accountability.days_in_focus(week_ago) == 8

    def test_none_input(self):
        assert accountability.days_in_focus(None) is None

    def test_invalid_date(self):
        assert accountability.days_in_focus("garbage") is None
