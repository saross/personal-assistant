"""
Tests for scripts/triage_anchors.py — the item-12 read-only triage classifier.

Covers the pure logic (``classify_anchor`` with an injected resolver, and
``dispose``). The heavy I/O paths (broad repo scan, corpus walk, git
subprocesses in ``main``) are not exercised here — they reuse already-tested
``anchor_verify`` resolvers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_path = Path(__file__).parent.parent / "scripts" / "triage_anchors.py"
_spec = importlib.util.spec_from_file_location("triage_anchors", _path)
ta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ta)


class TestClassifyAnchor:
    def test_malformed_short_circuits_before_resolve(self):
        # A malformed anchor is tagged without ever calling the resolver.
        called = []

        def resolve(_a):
            called.append(1)
            return "true"

        tag = ta.classify_anchor({"type": "commit", "ref": "rome-script"}, resolve)
        assert tag == "malformed"
        assert called == []  # resolver not invoked for malformed anchors

    @pytest.mark.parametrize("result,expected", [
        ("true", "broad-true"),
        ("false", "broad-false"),
        ("pending", "pending"),
    ])
    def test_wellformed_uses_resolver_result(self, result, expected):
        anchor = {"type": "commit", "ref": "7078d39"}
        assert ta.classify_anchor(anchor, lambda _a: result) == expected


class TestDispose:
    def test_broad_false_is_unresolvable(self):
        assert ta.dispose(["broad-true", "broad-false"]) == "unresolvable"

    def test_malformed_only_is_clean_after_strip(self):
        assert ta.dispose(["malformed"]) == "clean-after-strip"

    def test_malformed_plus_good_is_clean_after_strip(self):
        # Strip the malformed one and the record re-verifies on the good anchor.
        assert ta.dispose(["malformed", "broad-true"]) == "clean-after-strip"

    def test_all_broad_true_is_cross_repo(self):
        # No malformed, no broad-false: false only under the narrow verifier.
        assert ta.dispose(["broad-true", "pending"]) == "cross-repo"

    def test_malformed_plus_broad_false_is_unresolvable(self):
        # Stripping the malformed one still leaves a well-formed anchor that
        # resolves nowhere → genuinely suspect, not clean.
        assert ta.dispose(["malformed", "broad-false"]) == "unresolvable"
