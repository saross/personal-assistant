"""
Tests for scripts/publish-dashboard.py — the second dashboard renderer.

The point of this script is that a derived view must not be able to drift from
its source or to look healthy when it is not. So the tests concentrate on the
two ways it could lie: rendering an empty dashboard when the source files are
unreadable, and rendering a clean one when FOCUS.md has defects the session
banner cannot show.

Rendering is tested from injected state, so no test depends on the real
FOCUS.md or on the day it runs.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
publish = importlib.import_module("publish-dashboard")
accountability = importlib.import_module("session-start-accountability")

NOW = datetime(2026, 8, 22, 4, 55, tzinfo=timezone.utc)


def state(**overrides):
    """Build a dashboard state dict with sensible defaults."""
    base = {
        "slots": [{"slot_number": 1, "name": "EFN — website content",
                   "started": None, "deadline": None}],
        "inbox": 33,
        "waiting": 46,
        "focus_limit": 3,
        "anomalies": [],
    }
    base.update(overrides)
    return base


class TestCanvasRendering:
    def test_slots_render_as_table_rows(self):
        out = publish.render_canvas(state(), now=NOW, revision="abc1234")
        assert "| 1 | EFN — website content |" in out
        assert "## Focus" in out

    def test_empty_slots_are_shown_explicitly(self):
        """A gap in the focus set must be visible, not merely absent."""
        out = publish.render_canvas(state(), now=NOW, revision="abc1234")
        assert "| 2 | _empty_ |" in out
        assert "| 3 | _empty_ |" in out

    def test_no_slots_at_all_gives_guidance(self):
        out = publish.render_canvas(state(slots=[]), now=NOW, revision="abc1234")
        assert "No items in focus" in out

    def test_counts_appear(self):
        out = publish.render_canvas(state(), now=NOW, revision="abc1234")
        assert "Inbox: **33** items" in out
        assert "Waiting for: **46** items" in out

    def test_pipe_in_a_title_cannot_break_the_table(self):
        s = state(slots=[{"slot_number": 1, "name": "a | b",
                          "started": None, "deadline": None}])
        out = publish.render_canvas(s, now=NOW, revision="abc1234")
        assert r"a \| b" in out

    def test_footer_carries_time_and_revision(self):
        """Staleness must be readable off the artefact itself."""
        out = publish.render_canvas(state(), now=NOW, revision="e268e29+dirty")
        assert "2026-08-22 04:55 UTC" in out
        assert "e268e29+dirty" in out

    def test_anomalies_render_as_a_callout(self):
        out = publish.render_canvas(
            state(anomalies=["Slot 1 appears 2 times"]), now=NOW, revision="x")
        assert "::: {.callout}" in out
        assert "Slot 1 appears 2 times" in out

    def test_no_callout_when_clean(self):
        out = publish.render_canvas(state(), now=NOW, revision="x")
        assert ".callout" not in out


class TestPlainRendering:
    def test_reuses_the_hook_banner(self, monkeypatch):
        """Plain output must be the session banner, not a reimplementation."""
        monkeypatch.setattr(accountability, "build_banner",
                            lambda: ["# Task Status", "", "Focus:"])
        out = publish.render_plain(state(), now=NOW, revision="abc1234")
        assert out.startswith("# Task Status")
        assert "generated 2026-08-22 04:55 UTC" in out

    def test_anomalies_are_appended(self, monkeypatch):
        monkeypatch.setattr(accountability, "build_banner", lambda: ["x"])
        out = publish.render_plain(
            state(anomalies=["bad slot"]), now=NOW, revision="x")
        assert "WARN: bad slot" in out


class TestSelfChecks:
    """The defects the session banner cannot surface."""

    def test_duplicate_slot_number_is_flagged(self, monkeypatch):
        dupes = [{"slot_number": 1, "name": "current", "started": None, "deadline": None},
                 {"slot_number": 1, "name": "closed", "started": None, "deadline": None}]
        monkeypatch.setattr(accountability, "parse_focus_slots", lambda: dupes)
        monkeypatch.setattr(accountability, "all_task_files_missing", lambda: False)
        monkeypatch.setattr(accountability, "count_inbox_items", lambda: 0)
        monkeypatch.setattr(accountability, "count_waiting_items", lambda: 0)
        monkeypatch.setattr(accountability, "get_focus_limit", lambda: 3)
        monkeypatch.setattr(publish, "unreadable_deadlines", lambda slots: [])
        result = publish.collect()
        assert any("Slot 1 appears 2 times" in a for a in result["anomalies"])
        assert any("(record)" in a for a in result["anomalies"])

    def test_prose_deadline_is_flagged(self, tmp_path, monkeypatch):
        """Stated-but-unreadable is the case that silently disables escalation."""
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "## Slot 1: EFN\n\n- **Deadline:** **~26 Aug commitment**\n\n"
            "## Slot 2: Move\n\n- **Deadline:** 2026-09-15\n"
        )
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        msgs = publish.unreadable_deadlines(
            [{"slot_number": 2, "name": "Move", "started": None,
              "deadline": "2026-09-15"}])
        assert len(msgs) == 1
        assert "Slot 1" in msgs[0]

    def test_absent_deadline_is_not_flagged(self, tmp_path, monkeypatch):
        """Plenty of work legitimately has no date; do not nag about it."""
        focus = tmp_path / "FOCUS.md"
        focus.write_text("## Slot 1: EFN\n\n- **Project:** efn\n")
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        assert publish.unreadable_deadlines([]) == []

    def test_record_sections_are_ignored(self, tmp_path, monkeypatch):
        """`(record)` sections are history and must not raise anomalies."""
        focus = tmp_path / "FOCUS.md"
        focus.write_text(
            "## (record) Slot 1: old\n\n- **Deadline:** **~1 Aug prose**\n")
        monkeypatch.setattr(accountability, "FOCUS_FILE", focus)
        assert publish.unreadable_deadlines([]) == []


class TestFalseAbsenceGuard:
    def test_missing_task_files_raises_rather_than_rendering_empty(self, monkeypatch):
        """An unreadable source must never render as an empty dashboard."""
        monkeypatch.setattr(accountability, "all_task_files_missing", lambda: True)
        with pytest.raises(accountability.TaskFilesMissing):
            publish.collect()


class TestEditPlan:
    """Slack splits a canvas into one section per markdown block, so a full
    refresh is delete-the-rest-then-append, not a single replace."""

    SECTIONS = ["s1", "s2", "s3"]

    def test_one_operation_per_call(self):
        """The API accepts only one operation per canvases.edit call."""
        plan = publish.build_edit_plan("F123", "# body", self.SECTIONS)
        assert all(len(p["changes"]) == 1 for p in plan)

    def test_every_section_deleted_then_body_appended(self):
        plan = publish.build_edit_plan("F123", "# body", self.SECTIONS)
        assert len(plan) == 4  # 3 deletes + 1 insert
        assert [p["changes"][0]["operation"] for p in plan[:3]] == ["delete"] * 3
        assert plan[-1]["changes"][0]["operation"] == "insert_at_end"
        assert plan[-1]["changes"][0]["document_content"]["markdown"] == "# body"

    def test_converges_regardless_of_previous_section_count(self):
        """Section count varies with content (a warning callout adds one)."""
        for n in (0, 1, 9):
            plan = publish.build_edit_plan("F", "b", [f"s{i}" for i in range(n)])
            assert len(plan) == n + 1
            assert plan[-1]["changes"][0]["operation"] == "insert_at_end"


class TestPublishRetry:
    def test_lock_is_retried_not_fatal(self, monkeypatch):
        """canvas_editing_locked means a human has it open — transient."""
        calls = {"n": 0}

        def fake_post(payload, token):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("canvases.edit failed: canvas_editing_locked")
            return {"ok": True}

        monkeypatch.setattr(publish, "_post", fake_post)
        applied = publish.publish([{"canvas_id": "F"}], "tok", sleep=lambda s: None)
        assert applied == 1
        assert calls["n"] == 2

    def test_other_errors_raise_immediately(self, monkeypatch):
        """A partial refresh should be visibly broken, not silently retried."""
        def fake_post(payload, token):
            raise RuntimeError("canvases.edit failed: not_authed")

        monkeypatch.setattr(publish, "_post", fake_post)
        with pytest.raises(RuntimeError, match="not_authed"):
            publish.publish([{"canvas_id": "F"}], "tok", sleep=lambda s: None)


class TestProvenance:
    def test_unavailable_git_degrades_to_unknown(self, monkeypatch):
        """Never invent a revision — an unknown anchor is better than a wrong one."""
        monkeypatch.setattr(publish, "DATA_DIR", Path("/nonexistent"))
        assert publish.data_revision() == "unknown"


class TestRenderedTypesAreDeletable:
    """`canvases.sections.lookup` cannot filter plain paragraphs, so anything
    the renderer emits that is not a listed body type would survive every
    refresh and accumulate. This is the guard on that contract."""

    def test_footer_is_a_blockquote_not_a_paragraph(self):
        out = publish.render_canvas(state(), now=NOW, revision="abc1234")
        footer = [ln for ln in out.splitlines() if "Generated" in ln]
        assert footer, "no provenance footer rendered"
        assert footer[0].startswith("> "), \
            "footer must be a blockquote; a paragraph cannot be deleted on refresh"

    def test_body_types_exclude_h1(self):
        """h1 is the canvas title and must survive a refresh."""
        assert "h1" not in publish.BODY_SECTION_TYPES

    def test_lookup_sends_a_filter(self, monkeypatch):
        """criteria requires at least one filter; an empty object is rejected."""
        captured = {}

        def fake_call(method, payload, token):
            captured.update(payload)
            return {"ok": True, "sections": [{"id": "a"}]}

        monkeypatch.setattr(publish, "_call", fake_call)
        assert publish.read_section_ids("F1", "tok") == ["a"]
        assert captured["criteria"]["section_types"] == publish.BODY_SECTION_TYPES
