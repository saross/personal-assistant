"""
Tests for session-start-accountability.py — markdown parsing,
date arithmetic, and SYSTEM.md parameter reading.

Tests pure functions only; does not execute the hook end-to-end.
"""

import sys
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
            "| Roster access | Facilities | 2024-02-07 | 2024-02-07 | Follow up |\n"
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
            "| Roster access | Facilities | 2024-02-07 | - | Follow up |\n"
            "| Coating quote | Supplier | 2024-02-10 | - | Chase |\n"
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

    def test_strikethrough_rows_skipped_live_waiting_for_pattern(
        self, tmp_path, monkeypatch
    ):
        """Audit C-M1 (2026-05-02): the live ``waiting-for.md`` (line
        7 at audit time) contains a completed row whose Item, Waiting
        On, and Since cells are struck through but whose Next Action
        cell carries a visible resolution note (``**Received
        2026-03-19.** Processing today.``). The completed row must
        not be counted as still-waiting; this is the exact bug shape
        flagged by the audit.
        """
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On | Since | Last Poked | Next Action |\n"
            "|------|------------|-------|------------|-------------|\n"
            "| ~~Trainee profile info~~ | ~~Pat Example~~ "
            "| ~~2026-03-17~~ | — | "
            "**Received 2026-03-19.** Processing today. |\n"
            "| Trip dates | Travel agent | 2026-04-28 "
            "| — | Late June |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        # Two table rows, but the first is a completed/struck-through
        # item — only the second should count.
        assert accountability.count_waiting_items() == 1

    def test_strikethrough_rows_skipped_whole_row(
        self, tmp_path, monkeypatch
    ):
        """The whole-row variant — every populated cell struck — is
        the unambiguous case and must also be skipped.
        """
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On | Since | Last Poked | Next Action |\n"
            "|------|------------|-------|------------|-------------|\n"
            "| ~~Old item~~ | ~~Person~~ | ~~2026-01-01~~ "
            "| — | ~~done~~ |\n"
            "| Live item | Someone | 2026-04-28 | — | Chase |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        assert accountability.count_waiting_items() == 1

    def test_struck_leading_fragment_marks_the_row_done(
        self, tmp_path, monkeypatch
    ):
        """The live convention closes the strikethrough mid-cell and appends
        a project tag: ``~~Car service~~ (`personal`)``. A first cell that
        BEGINS struck is a completed row (audit H8, 2026-09-08). A cell that
        is struck only in the middle is still live.
        """
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On |\n"
            "|------|------------|\n"
            "| ~~Car service~~ (`personal`) | Scott |\n"
            "| Renamed ~~old~~ item | Someone |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        assert accountability.count_waiting_items() == 1

    def test_a_strikethrough_that_closes_in_the_last_cell_marks_the_row_done(
        self, tmp_path, monkeypatch
    ):
        """Kills ``^~~.`` -> ``^~~.+?~~`` (audit H26, 2026-09-08).

        The other live shape: the row opens ``~~`` in its Item cell and does
        not close it until the last cell, so the whole row renders struck but
        the first cell on its own carries no closing delimiter. The old
        pattern required the strikethrough to close inside the first cell, so
        rows of this shape were counted as still-waiting and inflated the
        banner every session.

        All three shapes in one fixture, so a pattern that satisfies one by
        breaking another cannot pass: closed-in-the-first-cell (done),
        closed-in-the-last-cell (done), struck-only-mid-cell (live).
        """
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On | Since | Next Action |\n"
            "|------|------------|-------|-------------|\n"
            "| ~~Lens cleaning kit~~ (`workshop`) | Supplier | 2024-05-02 "
            "| Arrived. |\n"
            "| ~~Counterweight quote | Machinist | 2024-04-11 "
            "| Quoted and paid.~~ |\n"
            "| Replacement ~~drive belt~~ spindle | Workshop | 2024-05-19 "
            "| Chase Sam. |\n"
        )
        monkeypatch.setattr(accountability, "WAITING_FILE", waiting)
        assert accountability.count_waiting_items() == 1

    def test_a_bare_delimiter_cell_is_not_a_done_row(self, tmp_path, monkeypatch):
        """Kills ``^~~.`` -> ``^~~``.

        A first cell holding nothing but the delimiter strikes nothing
        through; reading it as done would silently drop a live row from the
        count.
        """
        waiting = tmp_path / "waiting.md"
        waiting.write_text(
            "| Item | Waiting On |\n"
            "|------|------------|\n"
            "| ~~ | Machinist |\n"
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
        assert slots[0]["name"] == "Mirror recoating"
        assert slots[0]["slot_number"] == 1
        assert slots[0]["started"] == "2024-02-06"
        assert slots[0]["deadline"] == "2024-02-28"
        assert slots[1]["name"] == "Dome automation"
        assert slots[1]["deadline"] is None
        assert slots[2]["name"] == "Observing run prep"
        assert slots[2]["deadline"] == "2024-02-25"

    def test_skips_empty_slots(self, tmp_path, monkeypatch):
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "# Current Focus\n\n"
            "## Slot 1: Mirror recoating\n\n"
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
        assert slots[0]["name"] == "Mirror recoating"

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(accountability, "FOCUS_FILE", tmp_path / "nope.md")
        assert accountability.parse_focus_slots() == []

    def test_no_slots(self, tmp_path, monkeypatch):
        focus = tmp_path / "FOCUS.md"
        focus.write_text("# Current Focus\n\nNothing here.\n")
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        assert accountability.parse_focus_slots() == []

    def test_started_field_pins_day_count(self, tmp_path, monkeypatch):
        """Audit C-C1 (2026-05-02): both ``Started:`` and
        ``Task starts:`` field names must drive the day-in-focus
        counter. The rotating-task convention introduced 2026-04-18
        uses ``Task starts:`` for the *current* task in a slot, while
        the original ``Started:`` marks slot opening — and only
        ``Started:`` was previously matched.
        """
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "# Current Focus\n\n"
            "## Slot 1: Plain-Started Slot\n\n"
            "- **Started:** 2024-02-06\n"
            "- **Deadline:** 2024-02-28\n\n"
            "---\n\n"
            "## Slot 2: Rotating Task Slot\n\n"
            "- **Task starts:** 2026-04-27\n"
            "- **Deadline:** 2026-04-29\n\n"
            "---\n\n"
            "## Slot 3: Mixed-case Variant\n\n"
            "- **task STARTS:** 2026-04-25\n"
            "- **Deadline:** None\n\n"
            "---\n"
        )
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)

        slots = accountability.parse_focus_slots()
        assert len(slots) == 3
        # Slot 1: plain "Started:" — historical happy path.
        assert slots[0]["started"] == "2024-02-06"
        # Slot 2: "Task starts:" — was previously parsed as None,
        # silently breaking days_in_focus for any rotating slot.
        assert slots[1]["started"] == "2026-04-27"
        # Slot 3: case-insensitive match on "task STARTS".
        assert slots[2]["started"] == "2026-04-25"


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


# ============================================================================
# Main — files-missing branch (C-M5)
# ============================================================================


class TestMainFilesMissing:
    """Tests for the files-missing branch in main().

    Audit C-M5 (2026-05-02): when every input file the banner depends
    on is absent (typically a fresh clone where the data/ submodule
    has not yet been pulled), the banner used to print "No items in
    focus" and "Inbox: 0 items | Waiting for: 0 items" — visually
    indistinguishable from a clean slate. The fix surfaces the
    failure visibly via stderr and a clear stdout banner.
    """

    def test_warns_when_all_task_files_missing(
        self, tmp_path, monkeypatch, capsys
    ):
        # Point every file path at non-existent locations.
        monkeypatch.setattr(
            accountability, "FOCUS_FILE", tmp_path / "nope-FOCUS.md"
        )
        monkeypatch.setattr(
            accountability, "INBOX_FILE", tmp_path / "nope-inbox.md"
        )
        monkeypatch.setattr(
            accountability, "WAITING_FILE", tmp_path / "nope-waiting.md"
        )
        monkeypatch.setattr(
            accountability, "SYSTEM_FILE", tmp_path / "nope-SYSTEM.md"
        )
        # Patch stdin (the hook reads-and-discards the JSON payload).
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

        accountability.main()

        captured = capsys.readouterr()
        # Stderr carries a parseable WARN line operators can grep.
        assert "[accountability] WARN" in captured.err
        assert "task files missing" in captured.err
        # Stdout carries a clear, user-readable explanation rather
        # than the misleading "No items in focus" banner.
        assert "Task files not found" in captured.out
        assert "No items in focus" not in captured.out

    def test_normal_banner_when_files_present(
        self, tmp_path, monkeypatch, capsys
    ):
        # Even one of the three present should bypass the
        # all-missing fast path.
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "# Current Focus\n\n"
            "## Slot 1: Test Slot\n\n"
            "- **Started:** 2026-04-28\n"
            "- **Deadline:** None\n\n"
            "---\n"
        )
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        monkeypatch.setattr(
            accountability, "INBOX_FILE", tmp_path / "nope-inbox.md"
        )
        monkeypatch.setattr(
            accountability, "WAITING_FILE", tmp_path / "nope-waiting.md"
        )
        monkeypatch.setattr(
            accountability, "SYSTEM_FILE", tmp_path / "nope-SYSTEM.md"
        )
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

        accountability.main()

        captured = capsys.readouterr()
        assert "task files missing" not in captured.err
        # Normal banner emitted. Audit round two M3: `"# Task Status" in out`
        # is satisfied by "## Task Status", "### Task Status", or the string
        # embedded in a sentence, so the heading is pinned as a whole line.
        lines = captured.out.splitlines()
        assert lines[0] == "# Task Status"
        assert any(
            line.startswith("  Slot 1: Test Slot (day ") for line in lines
        ), lines



class TestAuditRoundTwo:
    """Live FOCUS.md formats the parser missed (audit H9, H10, 2026-09-08)."""

    def test_rotated_in_drives_the_day_counter(self, tmp_path, monkeypatch):
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "## Slot 1: Mirror recoating\n\n- **Rotated in:** 2024-02-05, per the trigger\n"
            "- **Deadline:** None\n\n---\n"
        )
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        slots = accountability.parse_focus_slots()
        assert slots and slots[0]["started"] == "2024-02-05"

    def test_prose_deadline_is_reported_unparseable_not_absent(self, tmp_path, monkeypatch):
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "## Slot 1: Mirror recoating\n\n- **Started:** 2024-02-05\n"
            "- **Deadline:** **~14 Mar, observing run**; booked **mid-Apr**.\n\n---\n"
        )
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        slots = accountability.parse_focus_slots()
        assert slots[0]["deadline"].startswith("~14 Mar")
        status = accountability.format_deadline_status(slots[0]["deadline"])
        assert "UNPARSEABLE" in status and "~14 Mar" in status


# ============================================================================
# Audit round two, Lens B (2026-09-08): H6 — the banner itself
# ============================================================================


def _iso(days_from_today: int) -> str:
    """Return an ISO date *days_from_today* away from today."""
    return (datetime.now().date() + timedelta(days=days_from_today)).isoformat()


def _stage_task_files(
    tmp_path,
    monkeypatch,
    *,
    focus: str | None = None,
    inbox: str | None = None,
    waiting: str | None = None,
    system: str | None = None,
) -> None:
    """Point every task-file path at *tmp_path*, writing only what is given.

    A file left as ``None`` is pointed at a path that does not exist, which
    is the "degrade gracefully if some files are missing" branch. At least
    one must be written or ``build_banner`` raises ``TaskFilesMissing``.
    """
    for attr, name, text in (
        ("FOCUS_FILE", "FOCUS.md", focus),
        ("INBOX_FILE", "inbox.md", inbox),
        ("WAITING_FILE", "waiting-for.md", waiting),
        ("SYSTEM_FILE", "SYSTEM.md", system),
    ):
        path = tmp_path / name
        if text is None:
            monkeypatch.setattr(accountability, attr, tmp_path / f"absent-{name}")
            continue
        path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(accountability, attr, path)


# These fixtures reproduce the SHAPE of the live task files and nothing
# else. Audit round two L4: an earlier version was a de-identified copy of
# the real waiting-for file — same situation, same week — which is still
# the private file in a public repository. Everything below is invented and
# deliberately unrelated: a fictional observatory's equipment log, dated in
# a different year.
#
# The shapes the tests actually pin: a header row containing "Waiting On",
# a separator row, bold item cells with a backticked project tag, and a
# completed row that closes its strikethrough MID-CELL before an un-struck
# tag (the live convention, audit H8).
#
# The last row is struck cell by cell, which is the OTHER encoding the
# counter documents — but note it is caught by the same first-cell rule, so
# the whole-row branch below it in count_waiting_items is defensive and
# unreachable in practice. No fixture here pins it, and none can while any
# struck row's first cell also opens with ``~~``.
_WAITING_LIVE = """# Waiting For

| Item | Waiting On | Since | Last Poked | Next Action If No Response |
|------|------------|-------|------------|---------------------------|
| **Spectrograph slot** (`observatory`) | Roster desk | 2024-03-11 | — | Ask again. |
| **Filter wheel part** (`observatory`/optics) | Supplier | 2024-02-19 | 2024-02-26 | Reorder. |
| **Dome shutter report** (`observatory`) | Contractor | 2024-03-04 | 2024-03-04 | Escalate. |
| ~~Telescope time application~~ (`observatory`) | ~~Panel~~ | 2024-01-15 | — | Granted. |
| ~~Star catalogue licence~~ | ~~Publisher~~ | ~~2023-11-02~~ | — | Renewed. |
"""

_INBOX_LIVE = """# Inbox

- [ ] Recalibrate the guide camera
- [x] Log last night's seeing conditions
- [ ] Order replacement desiccant
"""


class TestBannerRendering:
    """H6: build_banner() had no assertions on its content.

    Replacing its whole body with a constant list passed all 1,208 tests
    at the branch point, as did swapping the two counts, dropping the last
    empty slot, and deleting the slot-block delimiter. The counting
    functions were well pinned; the banner that renders them into every
    session's context was not pinned at all.
    """

    def test_counts_are_rendered_in_the_right_order(self, tmp_path, monkeypatch):
        """Kills swapping the two counts on the ``Inbox: … | Waiting for: …`` line.

        The two numbers differ (2 open inbox items, 3 open waiting-for
        rows), and the struck rows carry the live trailing project tag, so
        a strikethrough regression shows up here as well.
        """
        _stage_task_files(
            tmp_path, monkeypatch, inbox=_INBOX_LIVE, waiting=_WAITING_LIVE,
        )
        lines = accountability.build_banner()
        assert "Inbox: 2 items | Waiting for: 3 items" in lines

    def test_every_unfilled_slot_up_to_the_system_limit_is_listed(
        self, tmp_path, monkeypatch
    ):
        """Kills ``range(1, focus_limit + 1)`` → ``range(1, focus_limit)``.

        With the mutation the highest-numbered empty slot is never shown —
        the banner reports a full desk while a slot is free.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Mirror recoating — aluminising run\n\n"
            "- **Project:** observatory/optics (slug `optics`)\n\n"
            "---\n\n"
            "## Slot 3: Grant application\n\n"
            "- **Project:** research/grant\n\n"
            "---\n"
        )
        system = (
            "# System Configuration\n\n"
            "| Parameter | Current | Default | Notes |\n"
            "|-----------|---------|---------|-------|\n"
            "| focus_limit | 4 | 3 | Max items in FOCUS.md |\n"
        )
        _stage_task_files(tmp_path, monkeypatch, focus=focus, system=system)
        lines = accountability.build_banner()
        assert "  Slot 2: [Empty]" in lines
        assert "  Slot 4: [Empty]" in lines
        assert not any(line.startswith("  Slot 5:") for line in lines)

    def test_three_slots_are_shown_when_system_md_is_absent(
        self, tmp_path, monkeypatch
    ):
        """Kills ``DEFAULT_FOCUS_LIMIT = 3`` → any other value.

        ``test_default_when_missing`` compares get_focus_limit() with the
        constant itself, which is a tautology; the documented value of 3
        was pinned nowhere.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Mirror recoating — aluminising run\n\n"
            "- **Project:** observatory/optics\n\n"
            "---\n"
        )
        _stage_task_files(tmp_path, monkeypatch, focus=focus)
        lines = accountability.build_banner()
        assert "  Slot 2: [Empty]" in lines
        assert "  Slot 3: [Empty]" in lines
        assert not any(line.startswith("  Slot 4:") for line in lines)

    def test_slot_fields_stop_at_the_block_delimiter(self, tmp_path, monkeypatch):
        """Kills ``end_match = re.search(r"^(---|## )", …)`` → ``end_match = None``.

        With the mutation every slot's block runs to end of file, so a slot
        with no dates of its own silently inherits the next slot's
        ``Rotated in`` and ``Deadline`` — the banner then reports a day
        counter and a deadline that belong to a different task.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Alpha — no dates of its own\n\n"
            "- **Project:** research/alpha\n"
            "- **Next action:** start it\n\n"
            "---\n\n"
            "## Slot 2: Beta — dated\n\n"
            "- **Project:** business/beta\n"
            f"- **Rotated in:** {_iso(-2)}, per the dated trigger recorded below\n"
            f"- **Deadline:** {_iso(3)}\n\n"
            "---\n"
        )
        _stage_task_files(tmp_path, monkeypatch, focus=focus)
        lines = accountability.build_banner()
        slot_1 = next(line for line in lines if line.startswith("  Slot 1:"))
        slot_2 = next(line for line in lines if line.startswith("  Slot 2:"))

        assert "(day" not in slot_1, f"Slot 1 inherited a start date: {slot_1!r}"
        assert "[" not in slot_1, f"Slot 1 inherited a deadline: {slot_1!r}"
        # Slot 2 keeps its own, and the numbers are the file's, not a constant.
        assert "(day 3)" in slot_2, slot_2
        assert "[deadline in 3 days]" in slot_2, slot_2

    def test_the_seven_day_deadline_boundary_is_inclusive(
        self, tmp_path, monkeypatch
    ):
        """Kills ``elif delta <= 7:`` → ``elif delta < 7:``.

        At exactly seven days the mutation drops to the bare-date branch,
        so the last week before a deadline reads as a distant one.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Seven days out\n\n"
            f"- **Deadline:** {_iso(7)}\n\n"
            "---\n"
        )
        _stage_task_files(tmp_path, monkeypatch, focus=focus)
        lines = accountability.build_banner()
        slot_1 = next(line for line in lines if line.startswith("  Slot 1:"))
        assert "[deadline in 7 days]" in slot_1, slot_1

    def test_main_emits_the_real_counts_not_scaffolding(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills replacing the body of build_banner() with a constant list.

        ``test_normal_banner_when_files_present`` asserts only that
        ``# Task Status`` and the slot name appear, both of which a
        hardcoded banner satisfies. This asserts the numbers and the slot
        rendering come from the staged files.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Mirror recoating — aluminising run\n\n"
            "- **Project:** observatory/optics (slug `optics`)\n"
            f"- **Rotated in:** {_iso(-21)}, per the dated trigger\n"
            "- **Deadline:** None\n\n"
            "---\n"
        )
        _stage_task_files(
            tmp_path,
            monkeypatch,
            focus=focus,
            inbox=_INBOX_LIVE,
            waiting=_WAITING_LIVE,
        )
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"source": "startup"}'))

        accountability.main()

        out = capsys.readouterr().out
        assert "  Slot 1: Mirror recoating — aluminising run (day 22)" in out
        assert "Inbox: 2 items | Waiting for: 3 items" in out
        assert "  Slot 2: [Empty]" in out
        assert "  Slot 3: [Empty]" in out


class TestBannerScaffolding:
    """Audit round two M3: the banner's fixed lines and both deadline edges.

    The banner is a fixed shape the reader learns to scan. Its heading, its
    ``Focus:`` label, and its closing instruction were all deletable with
    the suite green, and only the lower edge of the "deadline in N days"
    window was pinned.
    """

    def test_the_heading_is_an_exact_first_line(self, tmp_path, monkeypatch):
        """Kills ``"# Task Status"`` -> ``"## Task Status"`` or a reworded
        heading.

        A substring assertion accepts any heading level and any surrounding
        prose; the banner is injected as additionalContext, where the
        heading level decides how the model reads the block.
        """
        _stage_task_files(tmp_path, monkeypatch, inbox=_INBOX_LIVE)
        lines = accountability.build_banner()
        assert lines[0] == "# Task Status"
        assert lines[1] == ""

    def test_the_focus_label_precedes_the_slots(self, tmp_path, monkeypatch):
        """Kills deleting ``lines.append("Focus:")``.

        Without the label the indented slot lines have no heading, so a
        reader (human or model) cannot tell the slot block from the counts.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Alpha\n\n"
            "- **Project:** research/alpha\n\n"
            "---\n"
        )
        _stage_task_files(tmp_path, monkeypatch, focus=focus)
        lines = accountability.build_banner()
        assert "Focus:" in lines
        assert lines.index("Focus:") < lines.index("  Slot 1: Alpha ")

    def test_the_empty_desk_message_replaces_the_slot_block(
        self, tmp_path, monkeypatch
    ):
        """Kills the ``if not slots:`` arm, which is the only prompt to act.

        With no slots the banner must say so and name the commands, not
        emit a bare ``Focus:`` label with nothing under it.
        """
        _stage_task_files(tmp_path, monkeypatch, inbox=_INBOX_LIVE)
        lines = accountability.build_banner()
        assert "Focus: No items in focus. Run /standup or /focus add." in lines
        assert not any(line.startswith("  Slot ") for line in lines)

    def test_the_closing_instruction_is_the_last_line(self, tmp_path, monkeypatch):
        """Kills deleting the ``Run /standup …`` footer.

        It is the only pointer from the banner to the command that acts on
        it; the banner is otherwise a read-only status dump.
        """
        _stage_task_files(tmp_path, monkeypatch, inbox=_INBOX_LIVE)
        lines = accountability.build_banner()
        assert lines[-1] == "Run /standup for full accountability check."
        assert lines[-2] == ""

    def test_the_counts_line_sits_between_the_slots_and_the_footer(
        self, tmp_path, monkeypatch
    ):
        """Kills reordering the banner's three blocks.

        Order is the whole reason a fixed-shape banner is scannable.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Alpha\n\n"
            "- **Project:** research/alpha\n\n"
            "---\n"
        )
        _stage_task_files(
            tmp_path,
            monkeypatch,
            focus=focus,
            inbox=_INBOX_LIVE,
            waiting=_WAITING_LIVE,
        )
        lines = accountability.build_banner()
        counts = "Inbox: 2 items | Waiting for: 3 items"
        assert counts in lines
        assert lines.index("Focus:") < lines.index(counts)
        assert lines.index(counts) < lines.index(lines[-1])

    def test_a_deadline_eight_days_out_is_a_bare_date(self, tmp_path, monkeypatch):
        """Kills ``elif delta <= 7:`` -> ``elif delta <= 8:``.

        The lower edge (exactly seven days) is pinned elsewhere; this is the
        other side. Widening the countdown window makes a deadline outside
        the week read as urgent, which is the failure the banner's
        escalation language exists to avoid.
        """
        due = _iso(8)
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Eight days out\n\n"
            f"- **Deadline:** {due}\n\n"
            "---\n"
        )
        _stage_task_files(tmp_path, monkeypatch, focus=focus)
        slot_1 = next(
            line for line in accountability.build_banner()
            if line.startswith("  Slot 1:")
        )
        assert f"[deadline {due}]" in slot_1, slot_1
        assert "deadline in" not in slot_1

    def test_the_overdue_and_today_wordings_are_distinct(self, tmp_path, monkeypatch):
        """Kills ``if delta < 0:`` -> ``<= 0`` and ``elif delta == 0:`` -> a
        shared branch.

        "OVERDUE by 0 days" and "deadline TODAY" are not the same statement,
        and the day a deadline falls due is exactly when the difference
        matters.
        """
        focus = (
            "# Current Focus\n\n"
            "## Slot 1: Due today\n\n"
            f"- **Deadline:** {_iso(0)}\n\n"
            "---\n\n"
            "## Slot 2: A day late\n\n"
            f"- **Deadline:** {_iso(-1)}\n\n"
            "---\n"
        )
        _stage_task_files(tmp_path, monkeypatch, focus=focus)
        lines = accountability.build_banner()
        slot_1 = next(line for line in lines if line.startswith("  Slot 1:"))
        slot_2 = next(line for line in lines if line.startswith("  Slot 2:"))
        assert "[deadline TODAY]" in slot_1, slot_1
        assert "[OVERDUE by 1 day]" in slot_2, slot_2
