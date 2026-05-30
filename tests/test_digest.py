"""
Tests for scripts/digest.py — the Vector 2 Stage 1 digest selector.

Covers the pure selector only (no I/O, no live corpus): the
what-changed counter, verified-true ranking, the promoted-recent
fallback, the hard byte cap, and the schema edge cases the live corpus
actually exhibits (``verified`` as a STRING, ``is_active: false``
forgotten records, ``research_tags`` as string-or-list).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# digest.py lives in scripts/; conftest only adds hooks/ to the path.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import digest  # noqa: E402

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _mem(**kw) -> dict:
    """Build a memory record with sensible defaults."""
    base = {
        "id": kw.get("id", "m-default"),
        "category": "decision",
        "summary": "a short summary",
        "research_tags": ["alpha", "beta"],
        "created_at": _iso(1),
        "verified": "true",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_verified_true_accepts_string_and_bool(self):
        assert digest.is_verified_true({"verified": "true"})
        assert digest.is_verified_true({"verified": "TRUE"})
        assert digest.is_verified_true({"verified": True})

    def test_verified_true_rejects_other_values(self):
        for v in ("false", "pending", None, "", False):
            assert not digest.is_verified_true({"verified": v})
        assert not digest.is_verified_true({})  # field absent

    def test_is_active_only_false_when_explicit(self):
        assert digest.is_active({})  # legacy default
        assert digest.is_active({"is_active": True})
        assert not digest.is_active({"is_active": False})

    def test_tags_of_handles_string_list_and_missing(self):
        assert digest.tags_of({"research_tags": ["A", "b"]}) == {"a", "b"}
        assert digest.tags_of({"research_tags": "Solo"}) == {"solo"}
        assert digest.tags_of({}) == set()

    def test_overlap_zero_when_profile_empty(self):
        assert digest.overlap_score({"research_tags": ["a"]}, set()) == 0

    def test_parse_iso_handles_z_and_naive(self):
        assert digest.parse_iso("2026-05-30T00:00:00Z") is not None
        naive = digest.parse_iso("2026-05-30T00:00:00")
        assert naive is not None and naive.tzinfo is not None
        assert digest.parse_iso(None) is None
        assert digest.parse_iso("not-a-date") is None


# ---------------------------------------------------------------------------
# What-changed counter
# ---------------------------------------------------------------------------


class TestCountChanges:
    def test_counts_new_in_window_only(self):
        mems = [
            _mem(id="a", created_at=_iso(1)),
            _mem(id="b", created_at=_iso(3)),
            _mem(id="c", created_at=_iso(10)),  # outside 7-day window
        ]
        c = digest.count_changes(mems, now=NOW, window_days=7)
        assert c["new"] == 2

    def test_category_breakdown(self):
        mems = [
            _mem(id="a", category="decision", created_at=_iso(1)),
            _mem(id="b", category="decision", created_at=_iso(2)),
            _mem(id="c", category="progress", created_at=_iso(2)),
        ]
        c = digest.count_changes(mems, now=NOW, window_days=7)
        assert c["categories"] == {"decision": 2, "progress": 1}

    def test_forgotten_counted_via_revision(self):
        mems = [
            _mem(
                id="f",
                is_active=False,
                created_at=_iso(20),  # created long ago...
                revisions=[{"revised_at": _iso(2), "action": "forget"}],  # ...forgotten recently
            )
        ]
        c = digest.count_changes(mems, now=NOW, window_days=7)
        assert c["forgotten"] == 1
        assert c["updated"] == 0
        assert c["new"] == 0  # not active, not created in window

    def test_updated_counted_via_revision(self):
        mems = [
            _mem(
                id="u",
                created_at=_iso(20),
                revisions=[{"revised_at": _iso(2), "action": "correct"}],
            )
        ]
        c = digest.count_changes(mems, now=NOW, window_days=7)
        assert c["updated"] == 1
        assert c["forgotten"] == 0

    def test_revision_outside_window_ignored(self):
        mems = [
            _mem(
                id="u",
                created_at=_iso(40),
                revisions=[{"revised_at": _iso(30), "action": "correct"}],
            )
        ]
        c = digest.count_changes(mems, now=NOW, window_days=7)
        assert c["updated"] == 0

    def test_created_and_updated_in_window_not_double_counted(self):
        # A memory both created and revised inside the window is "new"
        # only — its in-window revision must not also inflate "updated".
        mems = [
            _mem(
                id="x",
                created_at=_iso(2),
                revisions=[{"revised_at": _iso(1), "action": "correct"}],
            )
        ]
        c = digest.count_changes(mems, now=NOW, window_days=7)
        assert c["new"] == 1
        assert c["updated"] == 0  # not double-counted

    def test_window_boundary_is_inclusive(self):
        # Exactly window_days old counts as in-window; a hair older does not.
        mems = [
            _mem(id="edge-in", created_at=_iso(7.0)),
            _mem(id="edge-out", created_at=_iso(7.01)),
        ]
        c = digest.count_changes(mems, now=NOW, window_days=7)
        assert c["new"] == 1


# ---------------------------------------------------------------------------
# Verified ranking
# ---------------------------------------------------------------------------


class TestRankVerified:
    def test_excludes_unverified_forgotten_and_stale(self):
        mems = [
            _mem(id="keep", verified="true", created_at=_iso(1)),
            _mem(id="unverified", verified="false", created_at=_iso(1)),
            _mem(id="forgotten", verified="true", is_active=False, created_at=_iso(1)),
            _mem(id="stale", verified="true", created_at=_iso(30)),
        ]
        out = digest.rank_verified(mems, now=NOW, project_tags=set(), window_days=7)
        assert [m["id"] for m in out] == ["keep"]

    def test_ranks_by_overlap_then_recency(self):
        mems = [
            _mem(id="low-overlap-recent", research_tags=["zzz"], created_at=_iso(0)),
            _mem(id="high-overlap-old", research_tags=["alpha", "beta"], created_at=_iso(5)),
            _mem(id="high-overlap-recent", research_tags=["alpha", "beta"], created_at=_iso(1)),
        ]
        out = digest.rank_verified(
            mems, now=NOW, project_tags={"alpha", "beta"}, window_days=7
        )
        # Overlap dominates; recency breaks ties within an overlap level.
        assert [m["id"] for m in out] == [
            "high-overlap-recent",
            "high-overlap-old",
            "low-overlap-recent",
        ]

    def test_empty_profile_falls_back_to_recency(self):
        mems = [
            _mem(id="old", created_at=_iso(5)),
            _mem(id="new", created_at=_iso(1)),
        ]
        out = digest.rank_verified(mems, now=NOW, project_tags=set(), window_days=7)
        assert [m["id"] for m in out] == ["new", "old"]


# ---------------------------------------------------------------------------
# Fallback pool
# ---------------------------------------------------------------------------


class TestRankFallback:
    def test_only_anchored_unverified_active_in_window(self):
        mems = [
            _mem(id="anchored", verified="false", anchors=["x.py:1"], created_at=_iso(1)),
            _mem(id="no-anchors", verified="false", anchors=[], created_at=_iso(1)),
            _mem(id="verified", verified="true", anchors=["x.py:1"], created_at=_iso(1)),
            _mem(id="forgotten", verified="false", anchors=["x.py:1"],
                 is_active=False, created_at=_iso(1)),
        ]
        out = digest.rank_fallback(mems, now=NOW, exclude_ids=set(), window_days=7)
        assert [m["id"] for m in out] == ["anchored"]

    def test_respects_exclude_ids(self):
        m = _mem(id="anchored", verified="false", anchors=["x.py:1"], created_at=_iso(1))
        out = digest.rank_fallback(
            [m], now=NOW, exclude_ids={id(m)}, window_days=7
        )
        assert out == []


# ---------------------------------------------------------------------------
# build_digest — the integration surface
# ---------------------------------------------------------------------------


class TestBuildDigest:
    def test_never_exceeds_byte_budget(self):
        # 200 fat verified entries; the cap must hold.
        mems = [
            _mem(
                id=f"m{i}",
                summary="X" * 300,
                research_tags=[f"tag{i}", "alpha"],
                created_at=_iso(i % 7),
            )
            for i in range(200)
        ]
        res = digest.build_digest(
            mems, now=NOW, project_tags={"alpha"}, byte_budget=1500
        )
        assert res.rendered_bytes <= 1500
        assert len(res.text.encode("utf-8")) <= 1500

    def test_cap_holds_with_multibyte_summaries(self):
        # Char count != byte count for non-ASCII; the cap must measure
        # bytes, not characters (regression guard for len(text) vs
        # len(text.encode())).
        mems = [
            _mem(id=f"m{i}", summary="é" * 200, research_tags=["alpha"],
                 created_at=_iso(i % 7))
            for i in range(50)
        ]
        res = digest.build_digest(
            mems, now=NOW, project_tags={"alpha"}, byte_budget=1500
        )
        assert len(res.text.encode("utf-8")) <= 1500

    def test_cap_holds_at_tight_budget(self):
        # A realistically tight budget (just above the scaffolding floor).
        mems = [
            _mem(id=f"m{i}", summary="word " * 20, created_at=_iso(i % 7))
            for i in range(30)
        ]
        res = digest.build_digest(mems, now=NOW, project_tags=set(), byte_budget=700)
        assert len(res.text.encode("utf-8")) <= 700

    def test_sub_floor_budget_returns_minimal_scaffolding(self):
        # Below the scaffolding floor the cap cannot be honoured (the
        # anti-confab reminder is load-bearing); the function must still
        # return valid, non-empty scaffolding rather than crash or return
        # nothing. Documents the floor contract in DigestResult.
        res = digest.build_digest([], now=NOW, project_tags=set(), byte_budget=50)
        assert res.entries == []
        assert "Session-start digest" in res.text
        assert res.rendered_bytes > 50  # honestly over the impossible budget

    def test_oversized_top_entry_does_not_starve_digest(self):
        # The audit's case: one huge highest-rank entry followed by small
        # lower-rank entries. The big one is skipped, not allowed to
        # abandon the smaller entries behind it (greedy continue, not
        # break). Result must be non-empty.
        big = _mem(id="big", research_tags=["alpha", "beta"], summary="B" * 4000,
                   created_at=_iso(0))
        smalls = [
            _mem(id=f"s{i}", research_tags=["alpha"], summary="small", created_at=_iso(1))
            for i in range(5)
        ]
        res = digest.build_digest(
            [big, *smalls], now=NOW, project_tags={"alpha", "beta"}, byte_budget=1500
        )
        chosen = {m["id"] for m in res.entries}
        assert "big" not in chosen
        assert len(res.entries) >= 1  # smalls surface despite the oversized top entry
        assert res.rendered_bytes <= 1500

    def test_trims_lowest_rank_first(self):
        # One high-overlap entry + many zero-overlap entries, tight budget.
        high = _mem(id="high", research_tags=["alpha", "beta"], summary="keep me",
                    created_at=_iso(1))
        lows = [
            _mem(id=f"low{i}", research_tags=["zzz"], summary="Z" * 120,
                 created_at=_iso(2))
            for i in range(20)
        ]
        res = digest.build_digest(
            [high, *lows], now=NOW, project_tags={"alpha", "beta"}, byte_budget=700
        )
        chosen_ids = {m["id"] for m in res.entries}
        assert "high" in chosen_ids  # highest rank survives the trim
        assert res.rendered_bytes <= 700  # cap genuinely held
        assert len(chosen_ids) < 21  # some low-rank entries were excluded

    def test_fallback_fires_when_verified_sparse(self):
        # No verified-true, but anchored recent memories exist.
        mems = [
            _mem(id=f"f{i}", verified="false", anchors=["x.py:1"],
                 summary="anchored recent", created_at=_iso(i % 5))
            for i in range(5)
        ]
        res = digest.build_digest(
            mems, now=NOW, project_tags=set(), byte_budget=1500
        )
        assert res.verified_available == 0
        assert res.used_fallback is True
        assert len(res.entries) >= 1

    def test_no_fallback_when_verified_fills_budget(self):
        mems = [
            _mem(id=f"v{i}", summary="Y" * 120, created_at=_iso(i % 7))
            for i in range(40)
        ]
        res = digest.build_digest(
            mems, now=NOW, project_tags=set(), byte_budget=1500
        )
        assert res.used_fallback is False
        assert len(res.entries) >= 1  # verified content genuinely filled the budget

    def test_empty_corpus_produces_valid_digest(self):
        res = digest.build_digest([], now=NOW, project_tags=set(), byte_budget=1500)
        assert res.rendered_bytes <= 1500
        assert res.entries == []
        assert res.counter == {"new": 0, "updated": 0, "forgotten": 0, "categories": {}}
        assert "Session-start digest" in res.text

    def test_no_verified_no_fallback_states_none(self):
        # Unverified, unanchored, recent — nothing eligible to surface.
        mems = [_mem(id="x", verified="false", anchors=[], created_at=_iso(1))]
        res = digest.build_digest(mems, now=NOW, project_tags=set(), byte_budget=1500)
        assert res.entries == []
        assert "(none yet" in res.text

    def test_forgotten_never_surfaced(self):
        mems = [
            _mem(id="forgotten", is_active=False, created_at=_iso(1)),
            _mem(id="live", created_at=_iso(1)),
        ]
        res = digest.build_digest(mems, now=NOW, project_tags=set(), byte_budget=1500)
        ids = {m["id"] for m in res.entries}
        assert "forgotten" not in ids
        assert "live" in ids

    def test_tolerates_malformed_corpus_shapes(self):
        # Real-corpus shapes that must not crash the selector: tags as a
        # bare string, missing created_at, and malformed revisions.
        mems = [
            _mem(id="str-tags", research_tags="solo", created_at=_iso(1)),
            _mem(id="no-date", created_at=None),
            _mem(id="bad-rev", created_at=_iso(40),
                 revisions=[{"action": "forget"}]),  # no revised_at
            _mem(id="rev-not-list", created_at=_iso(40), revisions="oops"),
        ]
        # Must build without raising; counter stays coherent.
        res = digest.build_digest(mems, now=NOW, project_tags={"solo"}, byte_budget=1500)
        assert isinstance(res.counter["new"], int)
        assert res.rendered_bytes <= 1500
        # The string-tagged, in-window verified memory is eligible.
        assert any(m["id"] == "str-tags" for m in res.entries)


# ---------------------------------------------------------------------------
# Rendering + logging
# ---------------------------------------------------------------------------


class TestRendering:
    def test_render_entry_shape(self):
        line = digest.render_entry(
            _mem(category="gotcha", summary="watch the cap", research_tags=["b", "a"],
                 created_at="2026-05-30T11:00:00+00:00")
        )
        assert line == "[gotcha] watch the cap | a, b [2026-05-30]"

    def test_render_entry_falls_back_to_content(self):
        line = digest.render_entry(
            {"category": "progress", "content": "no summary here",
             "research_tags": [], "created_at": "2026-05-30T00:00:00+00:00"}
        )
        assert "no summary here" in line

    def test_category_breakdown_capped_with_more_tail(self):
        cats = {f"cat{i}": (20 - i) for i in range(15)}  # 15 categories
        rendered = digest._format_categories(cats, max_items=6)
        assert rendered.count(",") == 6  # 6 items + the "+N more" tail
        assert "+9 more" in rendered

    def test_category_breakdown_no_tail_when_under_cap(self):
        rendered = digest._format_categories({"a": 3, "b": 1}, max_items=6)
        assert "more" not in rendered

    def test_digest_log_line_is_single_tabbed_line(self):
        res = digest.build_digest([], now=NOW, project_tags=set(), byte_budget=1500)
        line = digest.digest_log_line(res, now=NOW)
        assert "\n" not in line
        assert "bytes=" in line and "fallback=" in line


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
