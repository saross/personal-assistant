"""
Tests for scripts/anchor_verify.py — the v2 mechanical anchor
verification module (Memory System v2, Phase 2).

Tests pure functions and dispatcher logic. Subprocess-bound paths
(verify_file, verify_commit) are exercised against mocked
subprocess.run; an integration test against a real git fixture is
deferred until Phase 0b.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# Import the module (under scripts/, hyphenated filename for some
# siblings — but anchor_verify is underscored so importlib isn't strictly
# needed; use it anyway to stay consistent with other test modules).
_av_path = Path(__file__).parent.parent / "scripts" / "anchor_verify.py"
_spec = importlib.util.spec_from_file_location("anchor_verify", _av_path)
av = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(av)


# ============================================================================
# _looks_like_hash — gate before launching git
# ============================================================================


class TestLooksLikeHash:
    """Cheap hash-shape predicate used by verify_commit."""

    @pytest.mark.parametrize("h", [
        "abc1234",                  # 7-char (typical short hash)
        "a1b2c3d4",                 # 8-char
        "1234567890abcdef" * 2 + "12345678",  # 40-char (full SHA-1)
        "ABCDEF12",                 # uppercase OK
        "DeadBeef",                 # mixed case
    ])
    def test_valid_hash_shapes(self, h):
        assert av._looks_like_hash(h) is True

    @pytest.mark.parametrize("h", [
        "",                         # empty
        "abc",                      # too short
        "g" * 8,                    # non-hex character
        "abc xyz",                  # whitespace
        "a" * 41,                   # too long
        "../../../etc/passwd",      # path-shaped, not hash-shaped
    ])
    def test_invalid_hash_shapes(self, h):
        assert av._looks_like_hash(h) is False


# ============================================================================
# bind_confidence — the rubric that Phase 2 uses to override Haiku
# ============================================================================


class TestBindConfidence:
    """The mapping from verified-status to confidence label."""

    def test_verified_true_non_guidance_is_high(self):
        assert av.bind_confidence(
            "true", is_guidance_category=False,
        ) == "high"

    def test_verified_true_guidance_complete_is_high(self):
        assert av.bind_confidence(
            "true",
            has_why=True,
            has_how_to_apply=True,
            is_guidance_category=True,
        ) == "high"

    def test_verified_true_guidance_missing_why_is_medium(self):
        assert av.bind_confidence(
            "true",
            has_why=False,
            has_how_to_apply=True,
            is_guidance_category=True,
        ) == "medium"

    def test_verified_true_guidance_missing_how_is_medium(self):
        assert av.bind_confidence(
            "true",
            has_why=True,
            has_how_to_apply=False,
            is_guidance_category=True,
        ) == "medium"

    def test_verified_pending_is_medium(self):
        assert av.bind_confidence("pending") == "medium"

    def test_verified_tier3_is_medium(self):
        # tier3 reserved for Phase 0b transcript-grep fallback;
        # rubric handles it for forward compatibility.
        assert av.bind_confidence("tier3") == "medium"

    def test_verified_false_is_low(self):
        assert av.bind_confidence("false") == "low"

    def test_verified_none_is_low(self):
        # No anchors checked at all — pre-v2 memories land here.
        assert av.bind_confidence(None) == "low"

    def test_guidance_category_doesnt_help_when_verified_false(self):
        # Even with rationale, a failed-verification memory stays low.
        assert av.bind_confidence(
            "false",
            has_why=True,
            has_how_to_apply=True,
            is_guidance_category=True,
        ) == "low"


# ============================================================================
# verify_memory — aggregation across multiple anchors
# ============================================================================


class TestVerifyMemoryAggregation:
    """How verify_memory combines per-anchor verifier results."""

    def test_no_anchors_returns_none(self):
        record = {"id": "test", "content": "no anchors here"}
        assert av.verify_memory(record, []) is None

    def test_empty_anchors_returns_none(self):
        record = {"id": "test", "anchors": []}
        assert av.verify_memory(record, []) is None

    def test_all_true_returns_true(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "file", "ref": "a.py"},
                {"type": "file", "ref": "b.py"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda ref, _r: "true"}):
            assert av.verify_memory(record, []) == "true"

    def test_any_false_returns_false(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "file", "ref": "real.py"},
                {"type": "file", "ref": "invented.py"},
            ],
        }
        results = iter(["true", "false"])
        with patch.dict(av._VERIFIERS, {"file": lambda r, _: next(results)}):
            assert av.verify_memory(record, []) == "false"

    def test_pending_with_no_false_returns_pending(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "file", "ref": "a.py"},
                {"type": "zotero", "ref": "MPZHXY3P"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda r, _: "true"}):
            # zotero stub already returns "pending"
            assert av.verify_memory(record, []) == "pending"

    def test_unknown_anchor_type_is_ignored(self):
        record = {
            "id": "test",
            "anchors": [
                {"type": "telepathy", "ref": "alpha-centauri"},
                {"type": "file", "ref": "a.py"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda ref, _r: "true"}):
            assert av.verify_memory(record, []) == "true"

    def test_malformed_anchor_skipped(self):
        record = {
            "id": "test",
            "anchors": [
                "not a dict",
                {"type": "file"},          # missing ref
                {"ref": "a.py"},            # missing type
                {"type": "file", "ref": "a.py"},
            ],
        }
        with patch.dict(av._VERIFIERS, {"file": lambda ref, _r: "true"}):
            assert av.verify_memory(record, []) == "true"

    def test_verifier_exception_treated_as_pending(self):
        record = {
            "id": "test",
            "anchors": [{"type": "file", "ref": "a.py"}],
        }
        def boom(*_):
            raise RuntimeError("boom")
        with patch.dict(av._VERIFIERS, {"file": boom}):
            assert av.verify_memory(record, []) == "pending"


# ============================================================================
# verify_commit — hash-shape gate
# ============================================================================


class TestVerifyCommitHashGate:
    """verify_commit short-circuits before subprocess on non-hash strings."""

    def test_short_circuit_on_non_hash(self):
        # No subprocess call should happen for an obviously non-hash value.
        with patch("subprocess.run") as mock_run:
            result = av.verify_commit("not-a-hash-at-all !!!", [Path("/tmp")])
            assert result == "false"
            mock_run.assert_not_called()

    def test_empty_input(self):
        assert av.verify_commit("", []) == "false"


# ============================================================================
# verify_zotero — stub
# ============================================================================


class TestVerifyZoteroStub:
    """The Zotero verifier is stubbed until Phase 5 — pending always."""

    def test_returns_pending(self):
        assert av.verify_zotero("MPZHXY3P") == "pending"

    def test_returns_pending_even_for_empty(self):
        # The stub doesn't try to validate the key shape.
        assert av.verify_zotero("") == "pending"
