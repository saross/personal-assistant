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

    def test_is_disproved_only_when_verification_returned_false(self):
        """Audit H25: "checked and found wrong" is its own state.

        ``pending``/absent must NOT read as disproved — that would empty the
        promoted-recent fallback pool of the records it exists to carry.
        """
        assert digest.is_disproved({"verified": "false"})
        assert digest.is_disproved({"verified": "FALSE"})
        assert digest.is_disproved({"verified": False})
        for v in ("true", True, "pending", None, ""):
            assert not digest.is_disproved({"verified": v})
        assert not digest.is_disproved({})  # field absent

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
    def test_only_anchored_pending_active_in_window(self):
        """The pool is anchored records still AWAITING verification.

        Rewritten for audit H25 (2026-09-08): the fixtures used to be
        ``verified="false"`` records, which pinned the disproved-records-are-
        eligible behaviour as deliberate. A record whose anchors were checked
        and did not hold is a known-wrong pointer and is now excluded; the
        pool is the anchored-but-pending records it was always described as.
        """
        mems = [
            _mem(id="anchored", verified="pending", anchors=["x.py:1"],
                 created_at=_iso(1)),
            _mem(id="no-anchors", verified="pending", anchors=[], created_at=_iso(1)),
            _mem(id="verified", verified="true", anchors=["x.py:1"], created_at=_iso(1)),
            _mem(id="disproved", verified="false", anchors=["x.py:1"],
                 created_at=_iso(1)),
            _mem(id="forgotten", verified="pending", anchors=["x.py:1"],
                 is_active=False, created_at=_iso(1)),
        ]
        out = digest.rank_fallback(mems, now=NOW, exclude_ids=set(), window_days=7)
        assert [m["id"] for m in out] == ["anchored"]

    def test_a_disproved_record_is_never_in_the_pool(self):
        """Kills dropping ``and not is_disproved(m)`` from ``rank_fallback``.

        Both spellings the corpus uses — the string ``"false"`` and a real
        ``False`` — must be excluded, and a record that has simply never been
        checked must still get in, so the mutation cannot be satisfied by
        excluding everything.
        """
        as_string = _mem(id="s", verified="false", anchors=["x.py:1"],
                         created_at=_iso(1))
        as_bool = _mem(id="b", verified=False, anchors=["x.py:1"], created_at=_iso(1))
        never_checked = _mem(id="n", anchors=["x.py:1"], created_at=_iso(1))
        del never_checked["verified"]
        out = digest.rank_fallback(
            [as_string, as_bool, never_checked],
            now=NOW, exclude_ids=set(), window_days=7,
        )
        assert [m["id"] for m in out] == ["n"]

    def test_respects_exclude_ids(self):
        m = _mem(id="anchored", verified="pending", anchors=["x.py:1"],
                 created_at=_iso(1))
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
        # No verified-true, but anchored recent memories awaiting a check
        # exist. ``verified="pending"`` since audit H25 — a disproved record
        # is no longer eligible for the fallback at all.
        mems = [
            _mem(id=f"f{i}", verified="pending", anchors=["x.py:1"],
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

    def test_digest_log_line_carries_focus_and_scoped_flags(self):
        res = digest.build_digest(
            [], now=NOW, project_tags=set(), byte_budget=1500,
            focus_keywords={"inscriptions"}, focus_label="inscriptions",
            project_id="-home-shawn-Code-inscriptions",
        )
        line = digest.digest_log_line(res, now=NOW)
        assert "focus=True" in line and "scoped=True" in line


# ============================================================================
# Vector 2c — focus-aware ranking + hard project scope
# ============================================================================


class TestMatchesProject:
    def test_none_project_id_is_no_scope(self):
        # The personal-assistant hub case: everything is in scope.
        assert digest.matches_project(_mem(project="-home-x"), None)

    def test_legacy_no_project_field_is_in_scope(self):
        # Pre-project-tagging records must not be penalised.
        assert digest.matches_project({"verified": "true"}, "-home-shawn-Code-x")

    def test_exact_match_in_scope(self):
        assert digest.matches_project(
            _mem(project="-home-shawn-Code-inscriptions"),
            "-home-shawn-Code-inscriptions",
        )

    def test_other_project_out_of_scope(self):
        assert not digest.matches_project(
            _mem(project="-home-shawn-Code-map-reader-llm"),
            "-home-shawn-Code-inscriptions",
        )


class TestFocusScore:
    def test_empty_keywords_is_zero(self):
        assert digest.focus_score(_mem(project="-home-shawn-Code-inscriptions"), set()) == 0

    def test_matches_project_substring(self):
        assert digest.focus_score(
            _mem(project="-home-shawn-Code-inscriptions", research_tags=[]),
            {"inscriptions"},
        ) == 1

    def test_matches_tag_substring(self):
        # The differently-named repo case: keyword hits a tag, not the project.
        assert digest.focus_score(
            _mem(project="-home-shawn-Code-Groundsite-EFN-Planning", research_tags=["efn-bizdev"]),
            {"efn"},
        ) == 1

    def test_counts_distinct_keywords(self):
        mem = _mem(project="-home-shawn-Code-inscriptions", research_tags=["efn"])
        assert digest.focus_score(mem, {"inscriptions", "efn"}) == 2

    def test_case_insensitive(self):
        assert digest.focus_score(
            _mem(project="-HOME-INSCRIPTIONS", research_tags=[]),
            {"inscriptions"},
        ) == 1

    def test_short_keywords_ignored(self):
        # <3 chars are dropped to avoid pathological substring hits.
        assert digest.focus_score(_mem(project="-home-ab-x", research_tags=[]), {"ab"}) == 0


class TestRankVerifiedScopeAndFocus:
    def test_focus_relevant_outranks_more_recent_offfocus(self):
        on_focus = _mem(id="f", project="-home-shawn-Code-inscriptions", created_at=_iso(3))
        off_focus = _mem(id="o", project="-home-shawn-Code-map-reader-llm", created_at=_iso(0.1))
        ranked = digest.rank_verified(
            [off_focus, on_focus], now=NOW, project_tags=set(),
            focus_keywords={"inscriptions"},
        )
        assert [m["id"] for m in ranked] == ["f", "o"]

    def test_project_id_hard_scopes_pool(self):
        ins = _mem(id="i", project="-home-shawn-Code-inscriptions")
        mr = _mem(id="m", project="-home-shawn-Code-map-reader-llm")
        ranked = digest.rank_verified(
            [ins, mr], now=NOW, project_tags=set(),
            project_id="-home-shawn-Code-inscriptions",
        )
        assert [m["id"] for m in ranked] == ["i"]

    def test_no_focus_no_scope_is_recency_order(self):
        # Defaults reproduce the pre-2c behaviour: pure recency here.
        a = _mem(id="a", created_at=_iso(2))
        b = _mem(id="b", created_at=_iso(1))
        ranked = digest.rank_verified([a, b], now=NOW, project_tags=set())
        assert [m["id"] for m in ranked] == ["b", "a"]


class TestRankFallbackScope:
    def test_fallback_respects_project_scope(self):
        # Anchored, awaiting verification → fallback pool; off-project
        # excluded. ``pending`` rather than ``false`` since audit H25.
        ins = _mem(id="i", verified="pending",
                   anchors=[{"type": "commit", "ref": "x"}],
                   project="-home-shawn-Code-inscriptions")
        mr = _mem(id="m", verified="pending",
                  anchors=[{"type": "commit", "ref": "y"}],
                  project="-home-shawn-Code-map-reader-llm")
        pool = digest.rank_fallback(
            [ins, mr], now=NOW, exclude_ids=set(),
            project_id="-home-shawn-Code-inscriptions",
        )
        assert [m["id"] for m in pool] == ["i"]


class TestBuildDigestVector2c:
    def test_flag_off_defaults_are_byte_identical(self):
        mems = [
            _mem(id="a", project="-home-shawn-Code-inscriptions", created_at=_iso(1)),
            _mem(id="b", project="-home-shawn-Code-map-reader-llm", created_at=_iso(2)),
        ]
        base = digest.build_digest(mems, now=NOW, project_tags=set())
        explicit = digest.build_digest(
            mems, now=NOW, project_tags=set(),
            project_id=None, focus_keywords=set(), focus_label="",
        )
        assert base.text == explicit.text
        assert base.focus_active is False and base.scoped is False

    def test_focus_label_renders_one_line(self):
        res = digest.build_digest(
            [_mem(project="-home-shawn-Code-inscriptions")],
            now=NOW, project_tags=set(),
            focus_keywords={"inscriptions"}, focus_label="inscriptions, efn",
        )
        assert "ranked for current focus: inscriptions, efn" in res.text
        assert res.focus_active is True

    def test_scope_shrinks_verified_available(self):
        mems = [
            _mem(id="a", project="-home-shawn-Code-inscriptions"),
            _mem(id="b", project="-home-shawn-Code-map-reader-llm"),
        ]
        unscoped = digest.build_digest(mems, now=NOW, project_tags=set())
        scoped = digest.build_digest(
            mems, now=NOW, project_tags=set(),
            project_id="-home-shawn-Code-inscriptions",
        )
        assert unscoped.verified_available == 2
        assert scoped.verified_available == 1
        assert scoped.scoped is True


# ============================================================================
# Vector 2b — cap_markdown_to_budget (the shared scratchpad capper)
# ============================================================================


# A realistic mini-scratchpad: a `# ` preamble plus several `## ` sections.
_SCRATCHPAD = (
    "# Scratchpad\n\n"
    "Claude's running learning log.\n\n"
    "## Constraints\n\n"
    "- Always use UK spelling.\n"
    "- Re-read sources before citing specifics.\n\n"
    "## Preferences\n\n"
    "- Critical-friend tone on statistics.\n\n"
    "## What Works\n\n"
    "- Product-manage, do not pair-program.\n\n"
    "## What Doesn't\n\n"
    "- Do not lecture about focus during PA-infra sessions.\n\n"
    "## Patterns\n\n"
    "- Compute aggregate implications of per-unit costs.\n"
)


class TestCapMarkdownToBudget:
    """Unit tests for the section-aware byte capper (design §5a)."""

    def test_under_budget_returns_input_unchanged(self):
        """Fast path: under budget → byte-identical passthrough, no trim.

        This is the property that makes flag-OFF / under-budget output
        indistinguishable from today's behaviour.
        """
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, 10_000)
        assert text == _SCRATCHPAD
        assert trimmed is False

    def test_exact_budget_boundary_not_trimmed(self):
        n = len(_SCRATCHPAD.encode("utf-8"))
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, n)
        assert text == _SCRATCHPAD
        assert trimmed is False

    def test_over_budget_drops_whole_sections_from_tail(self):
        """A tight budget keeps the preamble + earliest sections, drops the
        rest WHOLE, and marks the trim."""
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, 200)
        assert trimmed is True
        # Preamble always survives.
        assert "# Scratchpad" in text
        # Result is within budget.
        assert len(text.encode("utf-8")) <= 200
        # Trim marker present.
        assert digest.SCRATCHPAD_TRIM_MARKER in text

    def test_never_splits_a_section(self):
        """Every `## ` heading that survives must keep its full body — no
        half-sections."""
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, 260)
        assert trimmed is True
        # If 'Constraints' heading survived, both its bullets must too.
        if "## Constraints" in text:
            assert "UK spelling" in text
            assert "Re-read sources" in text

    def test_preamble_always_kept_even_if_over_budget(self):
        """Fail-soft: a budget below even the preamble still returns the
        preamble intact (we have no whole unit to drop below it)."""
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, 10)
        assert "# Scratchpad" in text

    def test_sub_floor_budget_may_exceed_but_keeps_preamble_and_marker(self):
        """Documented scaffolding-floor contract: below the
        preamble+marker floor every section is dropped and the result MAY
        exceed the budget (the sections are the only squeezable variable).
        We assert the contract, not an impossible cap."""
        preamble, _ = digest._split_markdown_sections(_SCRATCHPAD)
        marker = digest.SCRATCHPAD_TRIM_MARKER
        floor = len(preamble.encode("utf-8")) + len(marker.encode("utf-8")) + 2
        # A budget below the floor: result keeps preamble + marker, all
        # sections gone, was_trimmed True — and is allowed to exceed budget.
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, floor - 50)
        assert trimmed is True
        assert "# Scratchpad" in text
        assert marker in text
        assert "## Constraints" not in text  # every section dropped
        assert len(text.encode("utf-8")) > floor - 50  # exceeds, per contract

    def test_at_floor_budget_is_within_budget(self):
        """At/above the floor the cap holds exactly (the boundary of the
        contract): preamble + marker fit, all sections dropped."""
        preamble, _ = digest._split_markdown_sections(_SCRATCHPAD)
        marker = digest.SCRATCHPAD_TRIM_MARKER
        floor = len(preamble.encode("utf-8")) + len(marker.encode("utf-8")) + 2
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, floor)
        assert trimmed is True
        assert len(text.encode("utf-8")) <= floor

    def test_no_sections_passthrough(self):
        """Text with no `## ` headings is unsplittable → returned intact,
        not trimmed, even when over budget."""
        plain = "# Title\n\n" + ("x " * 500)
        text, trimmed = digest.cap_markdown_to_budget(plain, 50)
        assert text == plain
        assert trimmed is False

    def test_multibyte_budget_is_byte_not_char(self):
        """The cap counts UTF-8 bytes, not characters — a section of
        multibyte glyphs costs its byte weight."""
        mb = (
            "# Scratchpad\n\n"
            "## A\n\n" + ("é" * 400) + "\n\n"  # ~800 bytes
            "## B\n\n- short\n"
        )
        text, trimmed = digest.cap_markdown_to_budget(mb, 120)
        assert trimmed is True
        assert len(text.encode("utf-8")) <= 120

    def test_kept_sections_stay_in_document_order(self):
        """Surviving sections appear in their original order."""
        text, _ = digest.cap_markdown_to_budget(_SCRATCHPAD, 400)
        # Of whatever survives, Constraints (if present) precedes Preferences.
        if "## Constraints" in text and "## Preferences" in text:
            assert text.index("## Constraints") < text.index("## Preferences")

    def test_trim_marker_within_budget(self):
        """When trimmed, the rendered whole INCLUDING the marker is within
        budget — the marker is not allowed to push it over."""
        budget = 300
        text, trimmed = digest.cap_markdown_to_budget(_SCRATCHPAD, budget)
        assert trimmed is True
        assert len(text.encode("utf-8")) <= budget


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# Audit round two M2: the module defaults themselves
# ---------------------------------------------------------------------------


class TestModuleDefaults:
    """The constants were unpinned: every test passed them explicitly.

    ``byte_budget=1500`` and ``window_days=7`` appear as literals in every
    cap and ranking test above, so ``DEFAULT_BYTE_BUDGET`` and
    ``DEFAULT_WINDOW_DAYS`` could take any value with the suite green — and
    the live hook calls ``build_digest`` without either argument.
    """

    @staticmethod
    def _fat_pool(n: int = 200) -> list[dict]:
        """Verified in-window records far larger than any sane budget."""
        return [
            _mem(
                id=f"m{i}",
                summary="X" * 300,
                research_tags=[f"tag{i}", "alpha"],
                created_at=_iso(i % 7),
            )
            for i in range(n)
        ]

    def test_the_default_byte_budget_binds_at_1500(self):
        """Kills ``DEFAULT_BYTE_BUDGET = 1500`` -> a larger value.

        Called the way the hook calls it — no ``byte_budget`` argument —
        against 200 fat entries, so the cap must both be 1,500 and actually
        bind. SessionStart stdout goes straight into the model's context, so
        the constant is the bound.
        """
        res = digest.build_digest(
            self._fat_pool(), now=NOW, project_tags={"alpha"}
        )
        assert digest.DEFAULT_BYTE_BUDGET == 1500
        assert res.byte_budget == 1500
        assert res.rendered_bytes <= 1500
        assert len(res.text.encode("utf-8")) <= 1500
        # The cap bound: far fewer entries shown than were available.
        assert 0 < len(res.entries) < res.verified_available

    def test_the_default_window_is_seven_days(self):
        """Kills ``DEFAULT_WINDOW_DAYS = 7`` -> any other value.

        Records at six, seven, and eight days old, ranked with no
        ``window_days`` argument: the first two are in, the third is out.
        A wider default silently drags stale records into every session.
        """
        six = _mem(id="six", created_at=_iso(6))
        seven = _mem(id="seven", created_at=_iso(7))
        eight = _mem(id="eight", created_at=_iso(8))
        pool = digest.rank_verified(
            [six, seven, eight], now=NOW, project_tags=set()
        )
        assert [m["id"] for m in pool] == ["six", "seven"]
        assert digest.DEFAULT_WINDOW_DAYS == 7

    def test_the_window_edge_is_inclusive(self):
        """Kills ``created.timestamp() >= now.timestamp() - …`` -> ``>``.

        A record created exactly ``window_days`` ago is inside the window.
        The strict form drops it, which is invisible in any test whose
        fixtures sit at whole days on either side of the edge.
        """
        exact = _mem(id="exact", created_at=_iso(7))
        just_outside = _mem(id="outside", created_at=_iso(7.000_02))
        pool = digest.rank_verified(
            [exact, just_outside], now=NOW, project_tags=set(), window_days=7
        )
        assert [m["id"] for m in pool] == ["exact"]

    def test_the_default_window_reaches_the_rendered_text_and_result(self):
        """Kills passing a different window through to _assemble or the result.

        The digest tells the reader which window it covers; if the prose and
        the selection disagree, every entry is presented under a false
        claim.
        """
        res = digest.build_digest(
            [_mem(id="m1", created_at=_iso(1))], now=NOW, project_tags=set()
        )
        assert res.window_days == 7
        assert "in the last 7 days" in res.text
        assert "Verified-true entries from the last 7 days" in res.text


# ---------------------------------------------------------------------------
# Headings — what the digest CLAIMS about the entries under them (audit H25)
# ---------------------------------------------------------------------------


_VERIFIED_HEADING = "**Verified-true entries from the last"
# The common prefix of both fallback headings; the clause after it names why
# the fallback fired and is asserted on explicitly where it matters.
_UNVERIFIED_HEADING = "**Unverified, shown because"
_NOTHING_VERIFIED = "**Unverified, shown because nothing verified is available"
_COVERAGE_THIN = "**Unverified, shown because verified coverage is thin"


def _section(text: str, heading_prefix: str) -> list[str]:
    """Return the bullet lines that follow *heading_prefix* in *text*.

    A section runs from its heading to the next blank line, which is how
    :func:`digest._assemble` separates the blocks. Returns ``[]`` when the
    heading is absent, so an assertion on a missing section reads as an
    empty section rather than raising.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(heading_prefix):
            body = []
            for candidate in lines[i + 1:]:
                if not candidate.strip():
                    break
                body.append(candidate)
            return body
    return []


class TestHeadingsMatchTheirEntries:
    """H25: the fallback rendered under a "Verified-true entries" heading.

    ``rank_fallback`` admitted anchored ``verified: "false"`` records and
    ``_assemble`` printed every chosen entry under one heading claiming
    verification, directly above the anti-confabulation line promising that
    unverified content is not surfaced. Two independent guarantees now stop
    that: disproved records are out of the pool, and anything that is not
    verified-true renders under its own honest heading.
    """

    def test_a_disproved_record_never_renders_under_the_verified_heading(self):
        """Kills both halves of the H25 fix at once.

        Restoring ``rank_fallback``'s old predicate puts the disproved record
        in the digest; collapsing ``_assemble`` back to a single heading puts
        it under the verified-true one. The assertions below fail on either.
        """
        disproved = _mem(
            id="d", verified="false", anchors=["x.py:1"],
            summary="THE REFUTED CLAIM", created_at=_iso(1),
        )
        pending = _mem(
            id="p", verified="pending", anchors=["x.py:1"],
            summary="THE UNCHECKED CLAIM", created_at=_iso(1),
        )
        res = digest.build_digest(
            [disproved, pending], now=NOW, project_tags=set(), byte_budget=1500
        )

        assert "THE REFUTED CLAIM" not in res.text, (
            "a record whose anchors were disproved reached the session"
        )
        verified_block = "\n".join(_section(res.text, _VERIFIED_HEADING))
        assert "THE UNCHECKED CLAIM" not in verified_block, (
            "an unverified entry was rendered under the verified-true heading"
        )
        unverified_block = "\n".join(_section(res.text, _UNVERIFIED_HEADING))
        assert "THE UNCHECKED CLAIM" in unverified_block
        assert res.used_fallback is True

    def test_assemble_splits_by_verification_not_by_call_site(self):
        """Kills ``lines += [render_entry(m) for m in entries]`` under one
        heading, without relying on ``rank_fallback`` to have filtered first.

        ``_assemble`` is handed the mixed list directly, so the split has to
        be derived from the records. The verified-true count in the heading
        must count only verified-true entries as well — "5 shown of 0
        available" was the old shape whenever the fallback fired.
        """
        good = _mem(id="g", summary="A CHECKED FACT", created_at=_iso(1))
        pending = _mem(
            id="p", verified="pending", anchors=["x.py:1"],
            summary="AN UNCHECKED NOTE", created_at=_iso(1),
        )
        text = digest._assemble(
            {"new": 2, "updated": 0, "forgotten": 0, "categories": {}},
            [good, pending],
            window_days=7,
            verified_available=1,
            since_label=None,
        )
        assert "1 shown of 1 available" in text
        verified_block = "\n".join(_section(text, _VERIFIED_HEADING))
        assert "A CHECKED FACT" in verified_block
        assert "AN UNCHECKED NOTE" not in verified_block
        assert "AN UNCHECKED NOTE" in "\n".join(
            _section(text, _UNVERIFIED_HEADING)
        )

    def test_the_anti_confabulation_line_describes_this_digest(self):
        """Kills leaving the no-fallback wording in place when unverified
        entries are shown.

        "unverified content from prior sessions is not surfaced here" is a
        false claim on a digest that surfaces exactly that, and it is the
        sentence a reader would trust when deciding whether to re-check an
        entry.
        """
        pending = _mem(
            id="p", verified="pending", anchors=["x.py:1"],
            summary="an unchecked note", created_at=_iso(1),
        )
        with_fallback = digest.build_digest(
            [pending], now=NOW, project_tags=set(), byte_budget=1500
        ).text
        assert "is not surfaced here" not in with_fallback
        assert "not verified true — unchecked or inconclusive" in (
            with_fallback.replace("\n", " ")
        )

        # And the untouched wording on a digest that really does hold only
        # verified entries — the pre-H25 output, byte for byte.
        verified_only = digest.build_digest(
            [_mem(id="v", summary="a checked fact", created_at=_iso(1))],
            now=NOW, project_tags=set(), byte_budget=1500,
        ).text
        assert "unverified content from prior sessions is not surfaced" in (
            verified_only.replace("\n", " ")
        )
        assert _UNVERIFIED_HEADING not in verified_only

    def test_a_pending_record_is_not_called_unchecked(self):
        """Kills "never checked against a source" (re-audit M2, 2026-09-08).

        ``verified: "pending"`` means anchor verification RAN and could not
        settle the record — 53 such records were live at the re-audit. Both
        states the fallback admits are in this fixture, and the sentence has
        to be true of both, so it can only claim the negative they share.
        """
        pending = _mem(
            id="p", verified="pending", anchors=["x.py:1"],
            summary="an inconclusive note", created_at=_iso(1),
        )
        never_run = _mem(id="n", anchors=["x.py:1"],
                         summary="an unchecked note", created_at=_iso(1))
        del never_run["verified"]
        text = digest.build_digest(
            [pending, never_run], now=NOW, project_tags=set(), byte_budget=1500
        ).text
        assert {"an inconclusive note", "an unchecked note"} <= set(
            line.split("] ", 1)[-1].split(" | ")[0]
            for line in _section(text, _UNVERIFIED_HEADING)
        )
        flat = text.replace("\n", " ")
        assert "not verified true — unchecked or inconclusive" in flat
        assert "never checked" not in flat, (
            "a record that was checked and came back inconclusive was "
            "described as never checked"
        )

    def test_the_fallback_heading_names_why_the_fallback_fired(self):
        """Kills hard-coding either clause (re-audit M1, 2026-09-08).

        The fallback fires whenever verified content under-fills
        ``fallback_min_fill`` of the budget, not only when there is none, so
        a fixed "nothing verified is available" is false the moment one
        verified entry is present. Both branches are asserted, so neither
        clause can be hard-coded.
        """
        pending = [
            _mem(id=f"p{i}", verified="pending", anchors=["x.py:1"],
                 summary=f"an unchecked note {i}", created_at=_iso(1))
            for i in range(3)
        ]

        # Nothing verified at all.
        none_verified = digest.build_digest(
            pending, now=NOW, project_tags=set(), byte_budget=1500
        ).text
        assert _NOTHING_VERIFIED in none_verified
        assert _COVERAGE_THIN not in none_verified

        # Two short verified entries — present, but nowhere near filling the
        # budget, so the fallback still fires.
        verified = [
            _mem(id="v1", summary="a checked fact", created_at=_iso(1)),
            _mem(id="v2", summary="another checked fact", created_at=_iso(2)),
        ]
        thin = digest.build_digest(
            verified + pending, now=NOW, project_tags=set(), byte_budget=1500
        )
        assert thin.used_fallback is True, "the fixture did not exercise the top-up"
        assert len(_section(thin.text, _VERIFIED_HEADING)) == 2
        assert _COVERAGE_THIN in thin.text
        assert _NOTHING_VERIFIED not in thin.text
