"""
Tests for the shared project-id encoder (audit IC3 / C-X3 fix).

Pins two contracts:

* The encoding (resolve absolute path then ``replace("/", "-")``) is
  byte-identical to the previous inline implementation in
  ``hooks/session-start-retrieval.py:178``.
* The retrieval hook's ``derive_project`` is now a thin wrapper over
  the shared encoder — both writers and readers MUST agree byte-for-byte
  on the encoded form.
"""

from __future__ import annotations

import importlib.util
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


# Each pair is ``(cwd, expected_encoded_form)``. The expected forms are
# computed against the exact pre-batch-4 inline implementation:
# ``str(Path(cwd).resolve()).replace("/", "-")``.
PARITY_CASES = [
    ("/home/shawn/personal-assistant", "-home-shawn-personal-assistant"),
    ("/home/shawn/Code/llm-history-paper", "-home-shawn-Code-llm-history-paper"),
    ("/", "-"),
    ("/tmp/foo/bar", "-tmp-foo-bar"),
    ("/home/shawn/Code/map-reader-llm", "-home-shawn-Code-map-reader-llm"),
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
    expected = str(nested.resolve()).replace("/", "-")
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
