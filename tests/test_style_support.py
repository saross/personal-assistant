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


def _throwaway_repo(tmp_path: Path) -> tuple[Path, callable]:
    """Create a git repository with one committed file; return it and a runner."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_CONFIG_SYSTEM": "/dev/null"}

    def run(*args):
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, check=True,
                              env=env)

    run("init", "-q")
    run("config", "user.email", "tests@example.invalid")
    run("config", "user.name", "Style Tests")
    (repo / "script.py").write_text("print('one')\n", encoding="utf-8")
    run("add", "script.py")
    run("commit", "-qm", "seed")
    return repo, run


def test_git_state_reports_a_tracked_file_in_a_clean_tree(tmp_path):
    """The ordinary case: the commit that contains this very file."""
    repo, run = _throwaway_repo(tmp_path)

    state = style_support.git_state(repo / "script.py")

    assert state["commit"] == run("rev-parse", "HEAD").stdout.strip()
    assert state["dirty"] is False
    assert state["reason"] is None


def test_git_state_flags_an_uncommitted_change(tmp_path):
    """A commit alone does not identify a result produced from a dirty tree.

    The mutation this kills: hard-coding ``dirty`` to False, which lets
    provenance claim reproducibility it cannot deliver.
    """
    repo, _run = _throwaway_repo(tmp_path)
    (repo / "script.py").write_text("print('edited')\n", encoding="utf-8")

    assert style_support.git_state(repo / "script.py")["dirty"] is True


def test_git_state_refuses_an_untracked_copy_inside_another_repository(tmp_path):
    """A copy under someone else's checkout must not borrow its HEAD.

    ``git rev-parse HEAD`` searches upwards, so a copy of these scripts at
    ``<repo>/sub/sub2/`` used to report that repository's commit — naming a
    commit which does not contain the code that ran. The mutation this kills:
    dropping the ``ls-files --error-unmatch`` check.
    """
    repo, _run = _throwaway_repo(tmp_path)
    nested = repo / "sub" / "sub2"
    nested.mkdir(parents=True)
    copied = nested / "style_support.py"
    copied.write_text("print('a copy nobody committed')\n", encoding="utf-8")

    state = style_support.git_state(copied)

    assert state["commit"] is None
    assert state["dirty"] is None
    assert "not tracked" in state["reason"]


def test_git_state_outside_a_repository_says_so(tmp_path):
    """No repository is a reason, not a crash."""
    state = style_support.git_state(tmp_path)

    assert state["commit"] is None
    assert state["reason"] == "not inside a git repository"


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
    monkeypatch.setattr(style_support, "git_state", lambda *a, **k: {
        "commit": "cafe1234", "dirty": False, "root": "/nowhere",
        "reason": None,
    })
    an_input = tmp_path / "phase1.json"
    an_input.write_text("{}\n", encoding="utf-8")

    first = style_support.provenance_block("demo.py", [an_input])
    second = style_support.provenance_block("demo.py", [an_input])

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert not [k for k in first if "time" in k or "date" in k or "_at" in k]


def test_provenance_records_whether_the_tree_was_dirty(tmp_path, monkeypatch):
    """A reader must be able to tell a clean-commit result from a dirty one.

    The mutation this kills: dropping the ``git_dirty`` field, which leaves a
    result produced from a modified tree indistinguishable from one built at
    the recorded commit.
    """
    monkeypatch.setattr(style_support, "git_state", lambda *a, **k: {
        "commit": "cafe1234", "dirty": True, "root": "/nowhere",
        "reason": None,
    })

    block = style_support.provenance_block("demo.py")

    assert block["git_dirty"] is True


def test_provenance_extra_cannot_overwrite_the_run_fields(tmp_path):
    """`extra` is caller metadata; it must not rewrite what the block asserts.

    The mutation this kills: restoring the bare ``record.update(dict(extra))``,
    under which a caller could silently replace ``inputs`` or ``git_commit``.
    """
    with pytest.raises(ValueError, match="git_commit"):
        style_support.provenance_block(
            "demo.py", extra={"git_commit": "0000000", "note": "fine"})

    with pytest.raises(ValueError, match="inputs"):
        style_support.provenance_block("demo.py", extra={"inputs": []})

    # A non-clashing extra still lands.
    assert style_support.provenance_block(
        "demo.py", extra={"note": "fine"})["note"] == "fine"


# ---------------------------------------------------------------------------
# impute_missing_features (Phase 5's input vector, re-audit item 1)
# ---------------------------------------------------------------------------

def test_an_unmeasurable_feature_is_imputed_with_the_corpus_mean():
    """`float(None)` used to raise TypeError deep inside numpy.

    Phase 1 reports None for a metric it could not measure — mattr_100 below
    its 100-word window — and mattr_100 is an ACTIVE Mahalanobis feature, so
    every input under 100 words crashed before the short-input warning could
    explain itself. The mutation this kills: dropping the ``is_measured``
    branch and calling ``float(value)`` on everything.
    """
    values = [21.0, None, 0.42]
    labels = ["Mean sentence length", "MATTR-100", "Hapax ratio"]
    means = [23.0, 0.73, 0.40]

    vector, imputed = style_support.impute_missing_features(values, labels, means)

    # The imputed value is the corpus mean, which standardises to z = 0 and so
    # contributes nothing to the distance.
    assert vector == [21.0, 0.73, 0.42]
    assert imputed == ["MATTR-100"]


def test_a_fully_measured_input_imputes_nothing():
    """The ordinary case must report an empty list, not a silent default."""
    vector, imputed = style_support.impute_missing_features(
        [1.0, 2.0], ["a", "b"], [9.0, 9.0])

    assert vector == [1.0, 2.0]
    assert imputed == []


def test_a_boolean_is_not_a_measurement():
    """`isinstance(True, int)` is True, so a bool would pass as 1.0.

    The mutation this kills: using a bare ``isinstance(v, (int, float))``
    check, which turns a stray boolean into a fabricated measurement.
    """
    vector, imputed = style_support.impute_missing_features(
        [True], ["Flagged"], [4.5])

    assert vector == [4.5]
    assert imputed == ["Flagged"]


def test_mis_aligned_fallbacks_are_refused():
    """A fallback landing on the wrong feature would impute a wrong mean."""
    with pytest.raises(ValueError, match="parallel"):
        style_support.impute_missing_features([1.0, None], ["a", "b"], [0.0])


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


# ---------------------------------------------------------------------------
# metric_schema (re-audit item 4)
# ---------------------------------------------------------------------------

def test_a_stamped_payload_passes_and_an_unstamped_one_does_not(tmp_path):
    """The whole point: a file measured the old way must be refusable.

    The mutation this kills: returning None unconditionally, which restores
    exactly the silent mismatch the stamp exists to prevent.
    """
    fresh = {"metric_schema": style_support.metric_schema_stamp()}
    assert style_support.metric_schema_error(fresh, "fresh.json") is None

    message = style_support.metric_schema_error({}, "stale.json")
    assert message is not None
    assert "stale.json" in message
    assert "absent" in message
    assert "Re-run phase1_pipeline.py" in message


def test_an_older_version_is_refused_with_both_numbers():
    """The operator needs to know what they have and what is required."""
    message = style_support.metric_schema_error(
        {"metric_schema": {"version": 1}}, "old.json")

    assert "version is 1" in message
    assert f"version {style_support.METRIC_SCHEMA_VERSION}" in message


def test_the_temporary_file_is_created_beside_its_destination(tmp_path,
                                                              monkeypatch):
    """``os.replace`` is only atomic within one filesystem.

    Writing the temporary file to the system temp directory and renaming it
    across a mount boundary is not a rename at all — it is a copy, and a copy
    can be interrupted half way, which is the failure this helper exists to
    prevent. The mutation this kills: dropping ``dir=str(path.parent)`` from
    the ``mkstemp`` call.
    """
    recorded: dict[str, object] = {}
    real_mkstemp = style_support.tempfile.mkstemp

    def spy(*args, **kwargs):
        recorded.update(kwargs)
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(style_support.tempfile, "mkstemp", spy)
    target = tmp_path / "nested" / "out.json"

    style_support.atomic_write_text(target, "payload\n")

    assert recorded["dir"] == str(target.parent)


def test_a_stamp_without_a_version_is_refused(tmp_path):
    """A `metric_schema` block that carries no version is not a version.

    ``stamp.get("version")`` returning None for a version-less dict is what
    makes this refusal work, and nothing asserted it: changing the call to
    ``stamp.get("version", METRIC_SCHEMA_VERSION)`` — a plausible "sensible
    default" edit — makes an unversioned block pass as current. The mutation
    this kills is exactly that default.
    """
    message = style_support.metric_schema_error(
        {"metric_schema": {"definitions": "unstated"}}, "vague.json")

    assert message is not None
    assert "version is absent" in message


def test_an_untracked_file_does_not_make_the_tree_dirty(tmp_path):
    """`dirty` is about the recorded code, not about what is lying around.

    A scratch file, an editor backup, or a test's own output would otherwise
    stamp every result "dirty" and the flag would stop meaning anything.
    Dropping ``--untracked-files=no`` from the status call does exactly that,
    and nothing noticed. The mutation this kills is that dropped flag.
    """
    repo, _run = _throwaway_repo(tmp_path)
    (repo / "scratch-note.txt").write_text("not committed, not code\n",
                                           encoding="utf-8")

    state = style_support.git_state(repo / "script.py")

    assert state["dirty"] is False
    assert state["commit"] is not None
