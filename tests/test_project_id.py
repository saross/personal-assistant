"""
Tests for the shared project-id encoder (audit IC3 / C-X3 fix).

Pins two contracts:

* The encoding (resolve to an absolute path, then replace every
  non-alphanumeric character with ``-``) matches what Claude Code itself
  writes under ``~/.claude/projects/`` — the live double-dash evidence in
  ``scripts/project_id.py:encode_project_id`` (audit R4).
* The retrieval hook's ``derive_project`` is now a thin wrapper over
  the shared encoder — both writers and readers MUST agree byte-for-byte
  on the encoded form.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
HOOKS_DIR = PROJECT_ROOT / "hooks"


@pytest.fixture(scope="module")
def encode():
    """Load the shared encoder."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from project_id import encode_project_id  # noqa: WPS433
    return encode_project_id


@pytest.fixture(scope="module")
def retrieval_hook_module():
    """Load hooks/session-start-retrieval.py as a module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "session_start_retrieval", HOOKS_DIR / "session-start-retrieval.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Parity with the historical inline encoding
# ---------------------------------------------------------------------------


# Each pair is ``(cwd, expected_encoded_form)``. The first five are the
# historical parity cases (alphanumeric components only, so the pre-audit-R4
# ``/``-only rule and the corrected rule agree on them). The last two are the
# R4 cases the old rule got wrong.
PARITY_CASES = [
    ("/home/shawn/personal-assistant", "-home-shawn-personal-assistant"),
    ("/home/shawn/Code/llm-history-paper", "-home-shawn-Code-llm-history-paper"),
    ("/", "-"),
    ("/tmp/foo/bar", "-tmp-foo-bar"),
    ("/home/shawn/Code/map-reader-llm", "-home-shawn-Code-map-reader-llm"),
    # Audit R4 — the live name observed under ~/.claude/projects/ on
    # amd-tower (2026-09-08). The dot in ``.claude`` becomes its own dash,
    # so the separator and the dot together read as a DOUBLE dash. The
    # pre-fix encoder emitted ``…-.claude-worktrees-…`` and every worktree
    # session therefore matched zero same-project memories.
    (
        "/home/shawn/personal-assistant/.claude/worktrees/workstream-g-efficacy",
        "-home-shawn-personal-assistant--claude-worktrees-workstream-g-efficacy",
    ),
    # A dotted component anywhere, not just ``.claude``.
    ("/home/shawn/Code/site.example/docs", "-home-shawn-Code-site-example-docs"),
]


@pytest.mark.parametrize("cwd,expected", PARITY_CASES)
def test_encode_matches_pre_batch_inline(encode, cwd, expected):
    """The shared encoder reproduces the exact inline implementation.

    Pins the audit IC3 fix: any drift between the live writer (the
    extraction hook) and the live reader (this hook) silently breaks
    project-aware filtering.
    """
    assert encode(cwd) == expected


def test_encode_empty_cwd_returns_none(encode):
    """An empty cwd yields ``None`` — callers treat this as 'no current
    project known' and skip filtering."""
    assert encode("") is None


def test_encode_resolves_relative(encode, tmp_path):
    """Relative paths are resolved before encoding.

    The historical inline call was ``Path(cwd).resolve()`` first, so
    the encoded form does not contain ``..`` or trailing slashes.
    """
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    relative = str(nested / ".." / "b")
    expected = re.sub(r"[^A-Za-z0-9]", "-", str(nested.resolve()))
    assert encode(relative) == expected


# ---------------------------------------------------------------------------
# Wrapper contract — derive_project routes through the shared encoder.
# ---------------------------------------------------------------------------


def test_derive_project_uses_shared_encoder(encode, retrieval_hook_module):
    """``derive_project`` must produce the same value as
    ``encode_project_id`` for arbitrary cwds.

    A future refactor that reverts to inline encoding would diverge
    from the shared helper and this test would catch it.
    """
    for cwd, _ in PARITY_CASES:
        assert retrieval_hook_module.derive_project(cwd) == encode(cwd)


def test_derive_project_empty_cwd(retrieval_hook_module):
    """Empty cwd → ``None`` — same contract as the shared encoder."""
    assert retrieval_hook_module.derive_project("") is None


# ---------------------------------------------------------------------------
# Audit R4 — every non-alphanumeric character encodes to a dash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cwd,expected", [
    ("/a/b.c", "-a-b-c"),
    ("/a/b_c", "-a-b-c"),
    ("/a/b c", "-a-b-c"),
    ("/a/b+c", "-a-b-c"),
    ("/a/b@c", "-a-b-c"),
])
def test_encode_rewrites_every_non_alphanumeric(encode, cwd, expected):
    """Kills: narrowing the character class back to ``/`` (or to ``[/.]``).

    Only ``/`` and ``.`` are attested in the live projects directory; the
    rest are the deliberate conservative inference documented on
    ``encode_project_id``. Pinning them here means a future narrowing is a
    decision someone makes on purpose, not a silent regression.
    """
    assert encode(cwd) == expected


def test_encode_is_stable_for_alphanumeric_paths(encode):
    """A path with no special characters is unchanged but for the separators."""
    assert encode("/home/shawn/Code/inscriptions") == "-home-shawn-Code-inscriptions"
