"""
Tests for ``scripts/style-analyser/style_support.py``.

The tranche's twenty-odd output files were all written with a plain
``Path.write_text``: an interrupted run left a truncated JSON file that the
next stage parsed without complaint, none of them recorded what had produced
them, and no writer had a dry run. This module is the shared fix, so the
properties it promises — atomicity, "dry run writes nothing", a provenance
block with no wall-clock field in it — are asserted here once, rather than
re-asserted in every consumer.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import load_style_module, refuse_sockets  # noqa: E402

style_support = load_style_module("style_support")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; these scripts are CPU-only."""
    refuse_sockets(monkeypatch)


# ---------------------------------------------------------------------------
# atomic_write_text
# ---------------------------------------------------------------------------

def test_atomic_write_creates_the_file_and_leaves_no_debris(tmp_path):
    """The happy path: content lands, and the temporary file is gone.

    The mutation this kills: returning without the ``os.replace`` (the
    temporary file would survive and the destination would never appear).
    """
    target = tmp_path / "nested" / "out.json"

    wrote = style_support.atomic_write_text(target, "payload\n")

    assert wrote is True
    assert target.read_text(encoding="utf-8") == "payload\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["out.json"]


def test_dry_run_writes_nothing_at_all(tmp_path):
    """``--dry-run`` must not create the file *or* its parent directory.

    The mutation this kills: dropping the ``if dry_run: return False`` guard,
    which would let a dry run overwrite a production output.
    """
    target = tmp_path / "nested" / "out.json"

    wrote = style_support.atomic_write_text(target, "payload\n", dry_run=True)

    assert wrote is False
    assert not target.exists()
    assert not target.parent.exists()


def test_a_failed_write_leaves_the_previous_version_intact(tmp_path, monkeypatch):
    """An interrupted write must not truncate the file the next stage reads.

    ``os.replace`` is made to fail, standing in for a crash between opening
    the destination and finishing it. The mutation this kills: replacing the
    body with ``path.write_text(text)``, under which the original content is
    destroyed the moment the write starts.
    """
    target = tmp_path / "out.json"
    target.write_text('{"complete": true}\n', encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(style_support.os, "replace", boom)

    with pytest.raises(OSError):
        style_support.atomic_write_text(target, "TRUNCA")

    assert target.read_text(encoding="utf-8") == '{"complete": true}\n'
    # And no temporary file is left behind for a later run to trip over.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.json"]


def test_atomic_write_json_round_trips_with_a_trailing_newline(tmp_path):
    """JSON writers go through the same path and stay well-formed text."""
    target = tmp_path / "out.json"

    style_support.atomic_write_json(target, {"b": 1, "a": [2, 3]})

    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == {"b": 1, "a": [2, 3]}


def test_atomic_write_json_honours_dry_run(tmp_path):
    """The JSON wrapper must not lose the dry-run flag on the way through."""
    target = tmp_path / "out.json"

    assert style_support.atomic_write_json(target, {"a": 1}, dry_run=True) is False
    assert not target.exists()


# ---------------------------------------------------------------------------
# Hashing and git provenance
# ---------------------------------------------------------------------------

def test_file_sha256_matches_hashlib_and_tolerates_a_missing_file(tmp_path):
    """Provenance must record the real digest, and survive an absent input."""
    present = tmp_path / "input.txt"
    present.write_bytes(b"corpus stand-in\n")

    assert (style_support.file_sha256(present)
            == hashlib.sha256(b"corpus stand-in\n").hexdigest())
    assert style_support.file_sha256(tmp_path / "gone.txt") is None


def test_git_commit_is_none_outside_a_repository(tmp_path):
    """A run from a non-repository records no commit rather than crashing."""
    assert style_support.git_commit(tmp_path) is None


def test_git_commit_reports_head_of_a_throwaway_repository(tmp_path):
    """The positive case, in a repository created for this test alone.

    The mutation this kills: always returning ``None`` (provenance would
    silently stop recording the commit while every other assertion passed).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_CONFIG_SYSTEM": "/dev/null"}
    run = lambda *args: subprocess.run(  # noqa: E731 — terse local helper
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        check=True, env=env,
    )
    run("init", "-q")
    run("config", "user.email", "tests@example.invalid")
    run("config", "user.name", "Style Tests")
    (repo / "file.txt").write_text("one\n", encoding="utf-8")
    run("add", "file.txt")
    run("commit", "-qm", "seed")
    expected = run("rev-parse", "HEAD").stdout.strip()

    assert style_support.git_commit(repo) == expected


# ---------------------------------------------------------------------------
# provenance_block
# ---------------------------------------------------------------------------

def test_provenance_records_script_inputs_seed_and_model(tmp_path):
    """Every field a reader needs to re-derive the output is present."""
    an_input = tmp_path / "phase1.json"
    an_input.write_text("{}\n", encoding="utf-8")

    block = style_support.provenance_block(
        "demo_script.py", [an_input], seed=7, spacy_model="en_core_web_sm",
        extra={"reference": "excerpts"},
    )

    assert block["script"] == "demo_script.py"
    assert block["seed"] == 7
    assert block["spacy_model"] == "en_core_web_sm"
    assert block["reference"] == "excerpts"
    assert block["inputs"] == [
        {"path": str(an_input), "sha256": hashlib.sha256(b"{}\n").hexdigest()}
    ]


def test_provenance_carries_no_wall_clock_field(tmp_path, monkeypatch):
    """Two identical runs must produce identical provenance, byte for byte.

    A timestamp would make every output differ between runs and destroy the
    cheapest determinism check the tranche has. The mutation this kills:
    adding a ``generated_at_utc`` field.
    """
    monkeypatch.setattr(style_support, "git_commit", lambda *a, **k: "cafe1234")
    an_input = tmp_path / "phase1.json"
    an_input.write_text("{}\n", encoding="utf-8")

    first = style_support.provenance_block("demo.py", [an_input])
    second = style_support.provenance_block("demo.py", [an_input])

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert not [k for k in first if "time" in k or "date" in k or "_at" in k]


# ---------------------------------------------------------------------------
# sanity_verdict (Phase 5's decision rule, finding ST12)
# ---------------------------------------------------------------------------

def test_an_off_register_fixture_at_the_loo_ceiling_fails_the_verdict():
    """A fixture the metric failed to separate must turn the verdict False.

    This is finding ST12: the report rendered "NOT farther ✗" in the table
    while the footer still said PASS, because only a fixture below the LOO
    *median* flipped the flag. The mutation this kills: restoring
    ``ok = distance > loo_median`` for the fixture arm.
    """
    verdict, ok = style_support.sanity_verdict(
        distance=4.0, loo_max=4.0, loo_median=2.0, is_corpus=False,
    )

    assert ok is False
    assert "NOT farther" in verdict


def test_an_off_register_fixture_beyond_the_ceiling_passes():
    """The intended case still passes, so the check is not merely strict."""
    verdict, ok = style_support.sanity_verdict(
        distance=9.0, loo_max=4.0, loo_median=2.0, is_corpus=False,
    )

    assert ok is True
    assert verdict.startswith("farther")


def test_a_fixture_inside_the_median_is_reported_more_loudly():
    """The old, stricter condition survives as a note on the same failure."""
    verdict, ok = style_support.sanity_verdict(
        distance=1.0, loo_max=4.0, loo_median=2.0, is_corpus=False,
    )

    assert ok is False
    assert "median" in verdict


def test_a_held_out_corpus_paper_is_judged_in_the_other_direction():
    """The corpus arm passes inside the envelope and fails outside it."""
    assert style_support.sanity_verdict(3.9, 4.0, 2.0, is_corpus=True) == (
        "within", True)
    assert style_support.sanity_verdict(4.1, 4.0, 2.0, is_corpus=True)[1] is False
