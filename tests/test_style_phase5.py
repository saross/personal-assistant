"""
Tests for ``scripts/style-analyser/phase5_evaluator.py``.

Four findings from the 2026-09 repository audit are pinned here.

* **ST11 — the held-out arm could not fail.** ``build_validation_report``
  picks the leave-one-out (LOO) median corpus paper as its "held-out real"
  sanity sample, then scored it against a fit built from *every* corpus paper,
  that paper included. A row that helps define the centroid and covariance it
  is measured against is guaranteed to sit inside the envelope, so the arm of
  the check that was supposed to prove the metric recognises genuine corpus
  prose was decorative. The fix drops that paper's row, recomputes the LOO
  envelope from the reduced matrix, and scores the text against the n-1 fit —
  naming the held-out key in the report so a reader can see which paper it was.

* **ST12 — the footer could contradict the table.** A fixture rendered as
  "NOT farther ✗" only flipped ``sanity_ok`` to False when it *also* fell
  below the LOO median, so the report could print a PASS footer over a table
  row saying the metric had failed to separate foreign text from the corpus.
  The rendered verdict and the overall flag now both come from
  ``style_support.sanity_verdict``, which is where the rule is tested (see
  ``tests/test_style_support.py``); this module only asserts that Phase 5
  delegates to it rather than re-implementing it.

* **L5 — ``min()``/``max()`` on a possibly-empty sequence.**
  ``advisory_report`` took the range of an advisory metric's corpus values
  without checking there were any, so a phase1 results file predating a metric
  raised ``ValueError`` and aborted an otherwise valid evaluation over what is
  only an advisory block. It now reports the absence explicitly.

* **Cross-cutting — writes, dry runs, provenance.** Outputs went out through a
  plain ``Path.write_text`` (an interrupted run left a truncated report for the
  next stage to parse), there was no way to see what a run would write without
  writing it, and nothing recorded which code and which input bytes produced a
  result. Every write now goes through ``style_support``'s atomic helpers, a
  ``--dry-run`` flag writes zero bytes, and JSON output carries a
  ``provenance`` block.

**Why most of this file does not run here.** ``phase5_evaluator`` imports
numpy, scipy and scikit-learn at module scope and none of the three is
installed in this repository's virtual environment (deliberately — this is an
assistant repo, not a numerical one). Every test that needs the module object
is therefore marked ``integration`` and opens with an ``importorskip``, so it
is deselected by ``pytest.ini``'s ``-m "not integration"`` and would run only
in an environment carrying the scientific stack. The tests that *do* run here
read the script's source and assert against its abstract syntax tree (AST),
which needs nothing but the standard library; they are the regression guard
that survives in this environment.

All fixture data below is invented. Nothing is copied from the real corpus,
from ``data/``, or from any private source: this is a public repository.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import SCRIPTS_DIR, refuse_sockets  # noqa: E402

#: The script under audit. Parsed rather than imported: see the module
#: docstring on why importing it is impossible in this environment.
PHASE5_PATH = SCRIPTS_DIR / "phase5_evaluator.py"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; these scripts are CPU-only."""
    refuse_sockets(monkeypatch)


# ---------------------------------------------------------------------------
# Source-level helpers (standard library only — these run in this environment)
# ---------------------------------------------------------------------------

def _module_ast() -> ast.Module:
    """Parse ``phase5_evaluator.py`` without importing it."""
    return ast.parse(PHASE5_PATH.read_text(encoding="utf-8"),
                     filename=str(PHASE5_PATH))


def _function_def(tree: ast.Module, name: str) -> ast.FunctionDef:
    """Return the top-level-or-nested ``def name`` node, or fail the test."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() has disappeared from {PHASE5_PATH.name}")


def _attribute_calls(node: ast.AST, attr: str) -> list[ast.Call]:
    """Every ``Call`` in ``node`` whose callee is an attribute named ``attr``."""
    return [
        child for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == attr
    ]


# ---------------------------------------------------------------------------
# Synthetic corpus fixtures (invented — no real corpus data anywhere here)
# ---------------------------------------------------------------------------

#: Invented paper keys. Deliberately nonsense so they cannot be confused with
#: real corpus keys if this file is ever read out of context.
FAKE_KEYS = [
    "quokka2019alpha", "wombat2020bravo", "numbat2021charlie",
    "bilby2022delta", "galah2023echo", "potoroo2024foxtrot",
]


def _fake_paper(index: int, key: str, *, with_em_dash: bool = True) -> dict:
    """One synthetic per-paper record carrying every feature Phase 5 reads.

    Values are a deterministic spread around invented centres, chosen only so
    that no feature column is constant (a zero standard deviation would make
    the standardiser's fallback, not the covariance, the thing under test).
    """
    step = index + 1
    record = {
        "key": key,
        "n_words": 4000 + 100 * step,
        "sentence_stats": {"mean": 20.0 + 0.7 * step, "stdev": 9.0 + 0.4 * step},
        "paragraph_stats": {"mean": 95.0 + 3.0 * step},
        "mattr_100": 0.70 + 0.006 * step,
        "hapax_ratio": 0.41 + 0.005 * step,
        "passive_ratio": 0.17 + 0.004 * step,
        "nominalisation_per_1000w": 22.0 + 0.9 * step,
        "announcement_colon_per_1k": 1.1 + 0.15 * step,
        "hedge_per_100w": 1.4 + 0.08 * step,
        "concession_rate": 0.22 + 0.01 * step,
        "mean_dep_depth": 3.4 + 0.11 * step,
        "regression": {
            "first_plural_per_1k": 5.0 + 0.3 * step,
            "semicolon_per_1k": 4.0 + 0.5 * step,
        },
    }
    if with_em_dash:
        record["regression"]["em_dash_per_1k"] = 0.2 * step
    return record


def _fake_phase1(n_papers: int = 6, *, with_em_dash: bool = True) -> dict:
    """A synthetic phase1 results structure: per-paper rows plus an aggregate."""
    papers = [
        _fake_paper(i, FAKE_KEYS[i], with_em_dash=with_em_dash)
        for i in range(n_papers)
    ]
    aggregate = {
        "sentence_stats": {"mean": 23.5},
        "announcement_colon_per_1k": 1.6,
        "hedge_per_100w": 1.7,
        "concession_rate": 0.26,
        "regression": {"em_dash_per_1k": 0.5, "semicolon_per_1k": 5.5},
    }
    return {"per_paper": papers, "aggregate": aggregate}


def _fake_phase3(bimodal: tuple[str, ...] = ()) -> dict:
    """A synthetic phase3 promotion structure flagging ``bimodal`` metrics."""
    metrics = [
        "sentence_mean", "paragraph_mean_words", "mattr_100", "hapax_ratio",
        "passive_ratio", "nominalisation_per_1000w",
        "announcement_colon_per_1k", "hedge_per_100w", "concession_rate",
        "first_plural_per_1k", "semicolon_per_1k", "mean_dep_depth",
        "em_dash_per_1k",
    ]
    return {
        "promotions": [
            {"metric": m, "bimodal": m in bimodal} for m in metrics
        ]
    }


class _StubEvaluation:
    """The slice of ``Evaluation`` the validation report actually reads.

    Building a real one would need spaCy and the private corpus; the report's
    job here is choosing *which fit* each sample is scored against, so the
    scoring itself is stubbed out.
    """

    def __init__(self, distance: float, n_words: int = 1234) -> None:
        self.distance = distance
        self.n_words = n_words
        self.gate_pass = True
        self.gate_n_pass = 8
        self.gate = [
            SimpleNamespace(key=f"check_{i}", passed=True, label=f"Check {i}")
            for i in range(8)
        ]


def _record_evaluate_text(monkeypatch, phase5, distance_for) -> list[dict]:
    """Replace ``evaluate_text`` with a recorder; return the call log.

    ``distance_for`` maps a sample label to the distance the stub should
    report, so a test can drive a sample to either side of the envelope.
    """
    calls: list[dict] = []

    def fake_evaluate_text(text, source_label, phase1, phase3, nlp,
                           corpus_em_dash=False, loo=None, X=None, fs=None):
        calls.append({"label": source_label, "X": X, "loo": loo})
        return _StubEvaluation(distance_for(source_label))

    monkeypatch.setattr(phase5, "evaluate_text", fake_evaluate_text)
    return calls


def _write_fake_bodies(root: Path, keys: list[str]) -> None:
    """Create a ``<key>/body.md`` for each key, with invented prose inside."""
    for key in keys:
        target = root / key / "body.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "Invented prose standing in for a corpus body. It says nothing "
            "about any real paper; the scoring is stubbed out in these tests.\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Source-level guards — these DO run in this environment
# ---------------------------------------------------------------------------

def test_the_module_imports_the_shared_support_helpers():
    """Phase 5 must pull in ``style_support`` as a flat sibling.

    The mutation this kills: deleting the ``import style_support`` line, which
    strands every atomic write, the dry run, and the shared sanity rule.
    """
    tree = _module_ast()
    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.Import) for alias in node.names
    }

    assert "style_support" in imported


def test_no_output_is_written_with_a_bare_write_text():
    """Every write must go through ``style_support``'s atomic helper.

    The mutation this kills: restoring ``args.report.write_text(out, ...)``,
    under which an interrupted run leaves a truncated report that the next
    stage parses as though it were complete.
    """
    bare = _attribute_calls(_module_ast(), "write_text")

    assert bare == [], (
        "phase5_evaluator.py still calls Path.write_text directly at line(s) "
        + ", ".join(str(call.lineno) for call in bare)
    )


def test_the_writer_creates_no_directory_of_its_own():
    """A dry run must leave the filesystem completely untouched.

    The mutation this kills: reinstating
    ``args.report.parent.mkdir(parents=True, exist_ok=True)`` before the
    write, which would create directories on a run that promised to write
    nothing (``atomic_write_text`` makes the parent itself, on real writes
    only).
    """
    tree = _module_ast()
    made = _attribute_calls(_function_def(tree, "main"), "mkdir")
    made += _attribute_calls(_function_def(tree, "write_output"), "mkdir")

    assert made == [], (
        "an output path's parent is being created outside atomic_write_text, "
        "at line(s) " + ", ".join(str(call.lineno) for call in made)
    )


def test_the_cli_registers_a_dry_run_flag():
    """``--dry-run`` must exist on the command line, not just in the helper.

    The mutation this kills: dropping the ``ap.add_argument("--dry-run", ...)``
    call, which would leave the plumbing in place but unreachable.
    """
    tree = _module_ast()
    flags = {
        call.args[0].value
        for call in _attribute_calls(tree, "add_argument")
        if call.args and isinstance(call.args[0], ast.Constant)
    }

    assert "--dry-run" in flags


def test_the_sanity_rule_is_delegated_rather_than_reimplemented():
    """The verdict rule must come from ``style_support.sanity_verdict``.

    The mutation this kills: replacing the ``style_support.sanity_verdict``
    call in ``build_validation_report`` with the old inline
    ``"farther ✓" if ev.distance > loo_max else "NOT farther ✗"`` conditional,
    which is exactly the ST12 defect (a table row and a footer that disagree).
    """
    report_fn = _function_def(_module_ast(), "build_validation_report")
    delegated = _attribute_calls(report_fn, "sanity_verdict")

    assert len(delegated) == 1, (
        "build_validation_report must call style_support.sanity_verdict "
        f"exactly once; found {len(delegated)}"
    )
    assert all(
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == "style_support"
        for call in delegated
    )


def test_the_verdict_strings_are_not_written_out_in_phase_five():
    """The rendered verdict text must live in one place only.

    The mutation this kills: re-inlining the literal ``"NOT farther ✗"`` (or
    its siblings) into ``build_validation_report`` beside the delegated call,
    so the table could once again drift away from the overall flag.
    """
    source = PHASE5_PATH.read_text(encoding="utf-8")
    report_start = source.index("def build_validation_report")
    report_body = source[report_start:]

    assert "NOT farther" not in report_body
    assert "ABOVE (unexpected)" not in report_body


def test_both_output_paths_carry_a_provenance_block():
    """Every artefact must record the code and inputs behind its numbers.

    There are two: the single-text result and — since re-audit item 12 — the
    ``--validate`` report, which is the artefact that says whether the
    instrument works at all and carried no provenance of any kind.

    The mutation this kills: deleting either ``provenance_block`` call in
    ``main``, which leaves an artefact that cannot be tied back to the
    phase1/phase3 bytes it was derived from.
    """
    main_fn = _function_def(_module_ast(), "main")
    blocks = _attribute_calls(main_fn, "provenance_block")

    assert len(blocks) == 2
    for block in blocks:
        keywords = {kw.arg for kw in block.keywords}
        # The spaCy model is part of the measurement, so it belongs in both.
        assert "spacy_model" in keywords


# ---------------------------------------------------------------------------
# ST11 — the held-out paper is scored against an n-1 fit
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_held_out_corpus_paper_is_scored_against_a_reduced_fit(tmp_path,
                                                               monkeypatch):
    """The held-out paper's own row must be absent from the fit it is scored on.

    The mutation this kills: passing ``X=X`` (the full corpus matrix) for the
    ``corpus:`` sample instead of the reduced matrix — the ST11 defect, under
    which the held-out arm of the sanity check cannot fail.
    """
    numpy = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3()
    extracted = tmp_path / "extracted"
    _write_fake_bodies(extracted, FAKE_KEYS)

    fs = phase5.resolve_feature_space(phase3)
    full_X, keys = phase5.build_corpus_matrix(phase1, fs.active_paths)
    calls = _record_evaluate_text(monkeypatch, phase5, lambda label: 0.5)

    phase5.build_validation_report(phase1, phase3, nlp=None,
                                   extracted_dir=extracted)

    corpus_calls = [c for c in calls if c["label"].startswith("corpus:")]
    assert len(corpus_calls) == 1, "expected exactly one held-out corpus sample"
    held_key = corpus_calls[0]["label"].split(":", 1)[1].split(" ", 1)[0]
    held_index = keys.index(held_key)

    assert corpus_calls[0]["X"].shape == (len(keys) - 1, fs.k)
    assert numpy.array_equal(corpus_calls[0]["X"],
                             numpy.delete(full_X, held_index, axis=0))
    # The comparison envelope must be recomputed from the reduced matrix too.
    assert len(corpus_calls[0]["loo"]) == len(keys) - 1


@pytest.mark.integration
def test_off_register_fixtures_keep_the_full_fit(tmp_path, monkeypatch):
    """Synthetic fixtures are not corpus rows, so they keep the full fit.

    The mutation this kills: building every sample's fit by dropping a row,
    which would quietly shrink the envelope the off-register fixtures are
    compared against and make them easier to "pass".
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3()
    extracted = tmp_path / "extracted"
    _write_fake_bodies(extracted, FAKE_KEYS)

    fs = phase5.resolve_feature_space(phase3)
    calls = _record_evaluate_text(monkeypatch, phase5, lambda label: 0.5)

    phase5.build_validation_report(phase1, phase3, nlp=None,
                                   extracted_dir=extracted)

    fixture_calls = [c for c in calls if c["label"].startswith("fixture:")]
    assert fixture_calls, "the off-register fixtures were not scored at all"
    for call in fixture_calls:
        assert call["X"].shape == (len(FAKE_KEYS), fs.k)


@pytest.mark.integration
def test_the_report_names_the_held_out_key_and_the_reduced_fit(tmp_path,
                                                               monkeypatch):
    """A reader must be able to see which paper was held out, and from what.

    The mutation this kills: dropping the ``**Held out for the n−1 fit:**``
    line from the report, leaving the table's "within" verdict unattributable
    to any particular paper or fit size.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3()
    extracted = tmp_path / "extracted"
    _write_fake_bodies(extracted, FAKE_KEYS)

    calls = _record_evaluate_text(monkeypatch, phase5, lambda label: 0.5)
    report, _ok = phase5.build_validation_report(phase1, phase3, nlp=None,
                                                 extracted_dir=extracted)

    held_key = next(c["label"] for c in calls
                    if c["label"].startswith("corpus:")).split(":", 1)[1]
    held_key = held_key.split(" ", 1)[0]

    assert "Held out for the n−1 fit" in report
    assert held_key in report
    # The table must say, per row, which fit produced the distance.
    assert "| Fit |" in report
    assert f"n−1 (n={len(FAKE_KEYS) - 1}" in report


@pytest.mark.integration
def test_a_missing_body_file_drops_the_held_out_arm_and_says_so(tmp_path,
                                                                monkeypatch):
    """No body text means no held-out arm — stated, not silently skipped.

    The mutation this kills: removing the ``body.exists()`` guard, which would
    make the reduced fit be built and then scored against text that was never
    read.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3()
    extracted = tmp_path / "extracted"          # deliberately left empty
    extracted.mkdir()

    # Far enough out that the fixtures separate on any plausible envelope.
    calls = _record_evaluate_text(monkeypatch, phase5, lambda label: 1e6)
    report, ok = phase5.build_validation_report(phase1, phase3, nlp=None,
                                                extracted_dir=extracted)

    assert not any(c["label"].startswith("corpus:") for c in calls)
    assert "No held-out arm" in report
    # The fixtures still separated, so the run itself is a pass.
    assert ok is True


# ---------------------------------------------------------------------------
# ST12 — the footer cannot contradict the table
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_a_fixture_that_is_not_farther_fails_the_overall_verdict(tmp_path,
                                                                 monkeypatch):
    """A "NOT farther ✗" row must drag the footer down with it.

    The mutation this kills: restoring ``if ev.distance <= loo_median:
    sanity_ok = False`` as the only way a fixture can fail — the ST12 defect,
    under which a fixture between the LOO median and the LOO max rendered as a
    failure but left the report's footer saying PASS.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3()
    extracted = tmp_path / "extracted"
    _write_fake_bodies(extracted, FAKE_KEYS)

    fs = phase5.resolve_feature_space(phase3)
    full_X, _keys = phase5.build_corpus_matrix(phase1, fs.active_paths)
    summary = phase5.distribution_summary(
        phase5.leave_one_out_distances(full_X)
    )
    assert summary["median"] < summary["max"], (
        "the synthetic corpus is degenerate; this test needs a LOO spread"
    )
    # Squarely inside the old blind spot: above the median (so the retired
    # rule would have let it pass) but not beyond the max (so it plainly
    # failed to separate).
    blind_spot = (summary["median"] + summary["max"]) / 2.0

    def distance_for(label: str) -> float:
        return 0.0 if label.startswith("corpus:") else blind_spot

    _record_evaluate_text(monkeypatch, phase5, distance_for)
    report, ok = phase5.build_validation_report(phase1, phase3, nlp=None,
                                                extracted_dir=extracted)

    assert ok is False
    assert "NOT farther" in report
    assert "**Sanity verdict:** ✗ FAIL" in report


@pytest.mark.integration
def test_a_held_out_paper_outside_its_own_envelope_fails(tmp_path, monkeypatch):
    """The held-out arm must be able to fail now that the fit excludes it.

    The mutation this kills: reporting the corpus sample's verdict without
    feeding ``sanity_ok`` (``sanity_ok = sanity_ok and sample_ok`` reduced to
    ``sanity_ok = sanity_ok``), which would restore an arm that never fails.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3()
    extracted = tmp_path / "extracted"
    _write_fake_bodies(extracted, FAKE_KEYS)

    def distance_for(label: str) -> float:
        # The corpus paper lands absurdly far out; the fixtures separate fine.
        return 1e6 if label.startswith("corpus:") else 1e5

    _record_evaluate_text(monkeypatch, phase5, distance_for)
    report, ok = phase5.build_validation_report(phase1, phase3, nlp=None,
                                                extracted_dir=extracted)

    assert ok is False
    assert "ABOVE (unexpected)" in report


# ---------------------------------------------------------------------------
# L5 — empty advisory metric
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_advisory_report_survives_a_metric_no_paper_carries():
    """An advisory metric absent from every paper must report, not raise.

    The mutation this kills: restoring the bare
    ``"corpus_min": round(min(corpus_vals), 4)``, which raises ``ValueError``
    on an empty sequence and aborts the whole evaluation over an advisory
    block.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    # No paper carries an em-dash rate, and phase3 flags that metric bimodal,
    # so it is advisory-only and its corpus value list comes out empty.
    phase1 = _fake_phase1(with_em_dash=False)
    phase3 = _fake_phase3(bimodal=("em_dash_per_1k",))
    fs = phase5.resolve_feature_space(phase3)
    record = _fake_paper(0, "input:synthetic", with_em_dash=False)

    advisory = phase5.advisory_report(phase1, fs, record)

    entry = next(a for a in advisory if a["metric"] == "em_dash_per_1k")
    assert entry["corpus_min"] is None
    assert entry["corpus_max"] is None
    assert entry["note"], "the empty case must say why the range is missing"
    assert entry["split"] == {"split": False}


@pytest.mark.integration
def test_advisory_report_still_reports_a_range_when_values_exist():
    """The guard must not swallow the ordinary case.

    The mutation this kills: inverting the ``if corpus_vals:`` condition, which
    would report every advisory metric as rangeless.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3(bimodal=("em_dash_per_1k",))
    fs = phase5.resolve_feature_space(phase3)
    record = _fake_paper(2, "input:synthetic")

    advisory = phase5.advisory_report(phase1, fs, record)

    entry = next(a for a in advisory if a["metric"] == "em_dash_per_1k")
    # _fake_paper spreads em-dash rates over 0.2 * (index + 1) for six papers.
    assert entry["corpus_min"] == pytest.approx(0.2)
    assert entry["corpus_max"] == pytest.approx(1.2)
    assert entry["note"] == ""


# ---------------------------------------------------------------------------
# Cross-cutting — atomic writes, dry runs, provenance
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_dry_run_writes_nothing_and_says_so_on_stdout(tmp_path, capsys):
    """``--dry-run`` must create neither the file nor its parent directory.

    The mutation this kills: dropping the ``if dry_run:`` early return in
    ``write_output``, under which a dry run would overwrite a production
    report.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    target = tmp_path / "nested" / "report.md"

    wrote = phase5.write_output(target, "# invented report\n", dry_run=True)

    assert wrote is False
    assert not target.exists()
    assert not target.parent.exists()
    assert "dry run" in capsys.readouterr().out.lower()


@pytest.mark.integration
def test_a_markdown_report_lands_atomically_with_no_debris(tmp_path):
    """A real write must leave the report and nothing else behind.

    The mutation this kills: swapping ``style_support.atomic_write_text`` for
    ``path.write_text``, which is non-atomic and leaves a truncated file when
    the run is interrupted.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    target = tmp_path / "nested" / "report.md"

    wrote = phase5.write_output(target, "# invented report\n")

    assert wrote is True
    assert target.read_text(encoding="utf-8") == "# invented report\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["report.md"]


@pytest.mark.integration
def test_a_json_report_is_written_through_the_json_helper(tmp_path):
    """A JSON report goes out via ``atomic_write_json``, provenance intact.

    The mutation this kills: replacing the ``payload is not None`` branch in
    ``write_output`` with a plain text write, which would drop the trailing
    newline ``atomic_write_json`` guarantees and bypass the atomic path for
    exactly the outputs that carry provenance.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    target = tmp_path / "result.json"
    payload = {
        "source": "<invented passage>",
        "provenance": {"script": "phase5_evaluator.py", "inputs": []},
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)

    wrote = phase5.write_output(target, rendered, payload=payload)

    text = target.read_text(encoding="utf-8")
    assert wrote is True
    assert text.endswith("\n")
    assert json.loads(text)["provenance"]["script"] == "phase5_evaluator.py"


# ---------------------------------------------------------------------------
# Re-audit item 1 — an unmeasurable feature must not crash the input vector
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_an_input_below_the_mattr_window_scores_instead_of_raising(tmp_path,
                                                                  monkeypatch):
    """Any input under 100 words used to raise TypeError inside numpy.

    ``mattr_100`` is an ACTIVE feature and phase 1 now returns ``None`` for it
    below its 100-word window, so ``float(dotted(record, path))`` raised
    before the short-input warning at the end of ``evaluate_text`` could
    explain what had happened. The guard imputes the corpus mean and names the
    feature. The mutation this kills: restoring the bare
    ``[float(dotted(record, path)) for path in fs.active_paths]``.

    The pure half of this — ``style_support.impute_missing_features`` — is
    tested without numpy in ``tests/test_style_support.py``; this asserts that
    Phase 5 actually routes its input vector through it.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3()

    # A record shaped exactly as phase 1 emits it for a very short input:
    # every feature measured except MATTR, which is None below its window.
    short_record = dict(_fake_paper(0, "AAAA1111"))
    short_record["mattr_100"] = None
    short_record["mattr_100_short_text"] = True
    short_record["n_words"] = 40
    monkeypatch.setattr(phase5.p1, "process_paper",
                        lambda *a, **k: short_record)

    evaluation = phase5.evaluate_text("forty invented words", "short-input",
                                      phase1, phase3, nlp=None)

    assert evaluation.short_input is True
    assert "MATTR-100" in evaluation.imputed_features
    assert isinstance(evaluation.distance, float)
    # And the report says so, rather than presenting a full-evidence distance.
    assert "imputed with the corpus mean" in phase5.render_markdown(evaluation)


# ---------------------------------------------------------------------------
# Re-audit items 11 and 12 — the held-out paper, and the validate artefact
# ---------------------------------------------------------------------------

def test_phase1_without_drops_only_the_named_paper():
    """The advisory ranges must be corpus evidence excluding the sample.

    Pure enough to run without numpy? No — the module imports it — but the
    helper itself is a dict operation, so it is asserted here rather than
    left to the integration-only path. The mutation this kills: returning
    ``phase1`` unchanged, which puts the held-out paper back into the bands
    it is compared against.
    """
    pytest.importorskip("numpy")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()

    reduced = phase5.phase1_without(phase1, FAKE_KEYS[2])

    assert [p["key"] for p in reduced["per_paper"]] == [
        k for k in FAKE_KEYS[:len(phase1["per_paper"])] if k != FAKE_KEYS[2]]
    # The aggregate is carried over deliberately, and the gate is reported as
    # not-independent because of it.
    assert reduced["aggregate"] is phase1["aggregate"]
    assert len(phase1["per_paper"]) == 6, "the input must not be mutated"


@pytest.mark.integration
def test_the_held_out_sample_gets_advisory_ranges_without_itself(tmp_path,
                                                                 monkeypatch):
    """Item 11: the advisory block self-included the held-out paper.

    The mutation this kills: passing the full ``phase1`` for the corpus
    sample, which restores a paper being compared against a cluster range it
    helped define.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    phase1 = _fake_phase1()
    phase3 = _fake_phase3(bimodal=("em_dash_per_1k",))
    extracted = tmp_path / "extracted"
    _write_fake_bodies(extracted, FAKE_KEYS)

    seen: list[dict] = []
    real = phase5.evaluate_text

    def capture(text, label, p1_arg, *args, **kwargs):
        seen.append({"label": label, "phase1": p1_arg})
        return real(text, label, p1_arg, *args, **kwargs)

    monkeypatch.setattr(phase5, "evaluate_text", capture)
    phase5.build_validation_report(phase1, phase3, nlp=None,
                                   extracted_dir=extracted)

    corpus_call = [c for c in seen if c["label"].startswith("corpus:")][0]
    held_key = corpus_call["label"].split(":", 1)[1].split(" ", 1)[0]
    assert held_key not in [p["key"] for p in corpus_call["phase1"]["per_paper"]]
    # The fixtures keep the full corpus: they are not corpus rows.
    fixture_call = [c for c in seen if not c["label"].startswith("corpus:")][0]
    assert len(fixture_call["phase1"]["per_paper"]) == len(phase1["per_paper"])


@pytest.mark.integration
def test_a_missing_held_out_paper_fails_the_validation(tmp_path):
    """Item 12: the arm that tests recognition cannot simply be skipped.

    With no body.md the run used to report PASS having checked only that
    off-register prose scores far away — half of what the report claims. The
    mutation this kills: dropping the ``sanity_ok = False`` in that branch.
    """
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")
    report, sanity_ok = phase5.build_validation_report(
        _fake_phase1(), _fake_phase3(), nlp=None,
        extracted_dir=tmp_path / "absent",
    )

    assert sanity_ok is False
    assert "No held-out arm — FAIL" in report


def test_the_provenance_section_names_the_code_and_the_inputs():
    """Item 12: the validate artefact carried no provenance at all.

    The mutation this kills: dropping the ``render_provenance_section`` call
    from the ``--validate`` branch (the section would simply vanish).
    """
    pytest.importorskip("numpy")
    from style_test_helpers import load_style_module

    phase5 = load_style_module("phase5_evaluator")

    section = phase5.render_provenance_section({
        "script": "phase5_evaluator.py", "git_commit": "cafe1234",
        "git_dirty": True, "spacy_model": "en_core_web_sm",
        "inputs": [{"path": "phase1.json", "sha256": "abc"}],
    })

    assert "## Provenance" in section
    assert "cafe1234" in section
    assert "DIRTY" in section
    assert "phase1.json" in section and "abc" in section


#: Calls in ``main`` that CONSUME a phase-1 or phase-3 payload. The checked
#: loader has to run before every one of them.
_PHASE_CONSUMING_CALLS = (
    "build_validation_report",
    "resolve_feature_space",
    "build_corpus_matrix",
    "evaluate_text",
    "build_gate",
    "load_json",
)


def _called_name(call: ast.Call) -> str | None:
    """Return the name a call resolves to, for `f()` and for `mod.f()` alike."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_main_loads_its_phase_files_through_the_checked_loader():
    """The guarantee is the loader, not the order of a hand-written check.

    ``style_support.load_checked_payloads`` refuses before returning any
    payload, so a ``main`` that obtains its phase files from it cannot reach
    an unchecked one — and that property is tested directly, without numpy,
    in ``tests/test_style_support.py``. All this file needs to assert is that
    ``main`` gets its payloads that way, and gets them before anything else
    touches a corpus.

    The mutation this kills: going back to a hand-rolled check-then-load
    sequence, every defeat of which (hoisting the check into a nested
    function called later, wrapping it in an environment condition, emptying
    its iterable) passed the position-and-membership assertions this replaces.
    """
    main_fn = _function_def(_module_ast(), "main")
    loader_calls = [node for node in ast.walk(main_fn)
                    if isinstance(node, ast.Call)
                    and _called_name(node) == "load_checked_payloads"]

    assert len(loader_calls) == 1, "main must load its phase files exactly once"

    consumers = [(_called_name(node), node.lineno) for node in ast.walk(main_fn)
                 if isinstance(node, ast.Call)
                 and _called_name(node) in _PHASE_CONSUMING_CALLS]
    if consumers:
        first_name, first_line = min(consumers, key=lambda pair: pair[1])
        assert loader_calls[0].lineno < first_line, (
            f"the phase files are loaded after {first_name}() has already run"
        )


