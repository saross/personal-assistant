"""
Tests for the two style-analyser human-audit printers,
``scripts/style-analyser/validate_announce_colon.py`` and
``scripts/style-analyser/validate_passive_detection.py``.

Findings covered, all from the 2026-09-08 repository audit:

* **ST14 / STT2** — both scripts read ``/tmp/style-corpus-extract/<key>.txt``,
  a layout superseded by ``data/style-corpus/extracted/<key>/body.md``. The
  colon printer died with an unhandled ``FileNotFoundError``; the passive
  printer reported every paper missing, printed zero examples, and still
  exited 0, so its precision estimate could not be re-derived and the empty
  run looked like a clean one.
* **L1** — the colon printer's summary hard-coded "n=3" while dividing by a
  denominator no paper necessarily stood behind.
* **L2** — a missing ``phase1-results.json`` produced a reported rate of 0.0,
  printed as "0.000/1k" and indistinguishable from a measured zero.
* **L4** — the passive printer's docstring claimed it mirrored phase 1
  exactly; the trigger rule does, but the counting unit and the sentence set
  do not.

Every fixture here is invented. The real corpus is private and this is a
public repository, so no paper key, sentence, title, or number below comes
from it: the keys are of the form ``AAAA1111`` and the prose is written for
the test.

spaCy is not installed in this environment and its inputs are private, so the
passive printer is exercised through the scripted ``FakeNlp`` pipeline from
``tests/style_test_helpers.py``. No test here is marked ``integration``,
because the production code now defers ``import spacy`` into ``load_nlp`` —
every helper and driver is importable and testable without it.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import (  # noqa: E402
    FakeNlp,
    FakeSent,
    FakeToken,
    load_style_module,
    refuse_sockets,
)

announce = load_style_module("validate_announce_colon")
passive = load_style_module("validate_passive_detection")

#: The repository root, found from this file rather than from ``~`` (the suite
#: repoints HOME; see ``tests/conftest.py``).
REPO_ROOT = Path(__file__).resolve().parent.parent

#: One synthetic sentence carrying a genuine announcement colon: lower-case
#: word, colon, space, capital. Written for this test, not taken from anywhere.
COLON_PAPER = (
    "The survey produced one result: Ceramic scatters cluster near the ridge.\n"
)

#: Synthetic prose with no colon at all, so the regex finds nothing.
NO_COLON_PAPER = "we walked the transect and counted sherds all morning.\n"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; these scripts are CPU-only."""
    refuse_sockets(monkeypatch)


def _write_body(corpus_dir: Path, key: str, text: str) -> Path:
    """Create ``<corpus_dir>/<key>/body.md`` holding ``text``."""
    path = corpus_dir / key / "body.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_phase1_results(corpus_dir: Path, rates: dict[str, float]) -> Path:
    """Create the phase 1 results file the colon printer reads rates from."""
    path = corpus_dir / "analysis" / "phase1-results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "per_paper": [
            {"key": key, "announcement_colon_per_1k": rate}
            for key, rate in sorted(rates.items())
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _passive_sentence() -> FakeSent:
    """A scripted sentence whose parse carries nsubjpass and auxpass children.

    "The trench was recorded" — ``recorded`` is the VERB, ``trench`` its
    ``nsubjpass`` child, ``was`` its ``auxpass`` child. That is exactly the
    shape ``find_passive_triggers`` looks for.
    """
    sent = FakeSent([
        FakeToken("The", pos="DET", dep="det"),
        FakeToken("trench", pos="NOUN", dep="nsubjpass"),
        FakeToken("was", pos="AUX", dep="auxpass"),
        FakeToken("recorded", pos="VERB", dep="ROOT"),
    ])
    return sent.link(0, 3).link(1, 3).link(2, 3)


def _active_sentence() -> FakeSent:
    """A scripted sentence with no passive trigger anywhere in its parse."""
    sent = FakeSent([
        FakeToken("We", pos="PRON", dep="nsubj"),
        FakeToken("recorded", pos="VERB", dep="ROOT"),
        FakeToken("the", pos="DET", dep="det"),
        FakeToken("trench", pos="NOUN", dep="dobj"),
    ])
    return sent.link(0, 1).link(2, 3).link(3, 1)


# ---------------------------------------------------------------------------
# Shared: both scripts (ST14 / STT2, and the "this is a printer" statement)
# ---------------------------------------------------------------------------

def _code_string_literals(module) -> list[str]:
    """Return every string literal in ``module`` that is not a docstring.

    Docstrings are excluded deliberately: they explain which layout was
    superseded and why, and that historical note must stay sayable while the
    path itself must not survive anywhere the code can act on it.
    """
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node, clean=False) is not None:
                docstring_nodes.add(id(node.body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ]


def test_neither_validator_still_points_at_the_superseded_tmp_layout():
    """No executable string in either script names the superseded ``/tmp`` layout.

    The mutation this kills: restoring ``CORPUS_DIR =
    Path("/tmp/style-corpus-extract")``, a directory that no longer exists, so
    that every run reads nothing (ST14 / STT2).
    """
    for module in (announce, passive):
        offenders = [
            literal for literal in _code_string_literals(module)
            if "/tmp/style-corpus-extract" in literal
        ]
        assert offenders == [], f"{Path(module.__file__).name}: {offenders}"


@pytest.mark.parametrize("module", [announce, passive],
                         ids=["announce_colon", "passive_detection"])
def test_the_default_corpus_directory_is_the_clean_extraction(module):
    """The default corpus root is the repo's clean extraction, found from ``__file__``.

    The mutation this kills: resolving the default from ``Path.home()`` or
    leaving it a bare relative path, either of which silently reads the wrong
    tree (or nothing) depending on where the operator ran the script from.
    """
    expected = REPO_ROOT / "data" / "style-corpus" / "extracted"

    assert module.DEFAULT_CORPUS_DIR == expected
    assert module.DEFAULT_CORPUS_DIR.is_absolute()


@pytest.mark.parametrize("module", [announce, passive],
                         ids=["announce_colon", "passive_detection"])
def test_both_module_docstrings_declare_they_are_human_audit_printers(module):
    """Each module must say plainly that it decides nothing.

    The mutation this kills: dropping the statement, leaving a reader to
    assume these scripts check something and that exit 0 means "the regex is
    fine". They print a worksheet for a person to classify.
    """
    doc = module.__doc__ or ""

    assert "HUMAN-AUDIT PRINTER" in doc
    assert "asserts nothing" in doc


# ---------------------------------------------------------------------------
# validate_announce_colon.py
# ---------------------------------------------------------------------------

def test_a_missing_body_file_is_reported_and_the_run_continues(tmp_path, capsys):
    """A paper with no body.md is a stderr diagnostic, not a traceback.

    The mutation this kills: reverting ``read_body`` to an unguarded
    ``path.read_text(...)``, which raised ``FileNotFoundError`` and abandoned
    the papers that were present (ST14).
    """
    _write_body(tmp_path, "AAAA1111", COLON_PAPER)

    code = announce.main(
        ["--corpus-dir", str(tmp_path), "--keys", "AAAA1111", "BBBB2222"]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "SKIPPED" in captured.err
    assert "BBBB2222" in captured.err
    assert "TRUE ANNOUNCEMENT COLON" in captured.out


def test_an_unreadable_corpus_exits_non_zero(tmp_path, capsys):
    """No paper readable at all must not look like a clean audit.

    The mutation this kills: an unconditional ``return 0``, under which a run
    against a mistyped ``--corpus-dir`` printed an empty report and reported
    success.
    """
    code = announce.main(["--corpus-dir", str(tmp_path), "--keys", "AAAA1111"])

    captured = capsys.readouterr()
    assert code == 1
    assert "EMPTY SAMPLE" in captured.err


def test_a_paper_with_no_regex_match_exits_non_zero(tmp_path, capsys):
    """A readable paper with nothing to sample is still an empty sample.

    The mutation this kills: counting *papers read* rather than *examples
    printed*, which would report success on a report containing no example.
    """
    _write_body(tmp_path, "AAAA1111", NO_COLON_PAPER)

    code = announce.main(["--corpus-dir", str(tmp_path), "--keys", "AAAA1111"])

    captured = capsys.readouterr()
    assert code == 1
    assert "total matches=0" in captured.out
    assert "EMPTY SAMPLE" in captured.err


def test_the_corrected_rate_is_precision_times_the_reported_rate(tmp_path, capsys):
    """The reported rate is read from ``<corpus>/analysis/phase1-results.json``.

    One synthetic paper, one genuine announcement colon, precision 1.0 and a
    reported 4.0/1k, so the corrected rate must be 4.000/1k. The mutation this
    kills: dropping the ``precision *`` multiplication, or reading the results
    file from a path unrelated to ``--corpus-dir``.
    """
    _write_body(tmp_path, "AAAA1111", COLON_PAPER)
    _write_phase1_results(tmp_path, {"AAAA1111": 4.0})

    code = announce.main(["--corpus-dir", str(tmp_path), "--keys", "AAAA1111"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Sample precision: 1/1 = 1.00" in captured.out
    assert "AAAA1111: reported 4.000/1k  ->  corrected 4.000/1k" in captured.out


def test_the_summary_mean_counts_the_papers_that_contributed(tmp_path, capsys):
    """``n`` in the summary is derived, not the hard-coded 3 (finding L1).

    Two papers contribute and a third is missing, so the mean is over n=2.
    The mutation this kills: restoring the literal ``n=3``, which divided by a
    denominator that no longer matched the papers behind the number.
    """
    _write_body(tmp_path, "AAAA1111", COLON_PAPER)
    _write_body(tmp_path, "BBBB2222", COLON_PAPER)
    _write_phase1_results(tmp_path, {"AAAA1111": 4.0, "BBBB2222": 2.0})

    code = announce.main(
        ["--corpus-dir", str(tmp_path),
         "--keys", "AAAA1111", "BBBB2222", "CCCC3333"]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "Unweighted mean (n=2)" in captured.out
    assert "n=3" not in captured.out
    # Unweighted mean of 4.000 and 2.000, both at precision 1.0.
    assert "corrected: 3.000/1k" in captured.out


def test_a_missing_results_file_prints_not_available_not_zero(tmp_path, capsys):
    """No ``phase1-results.json`` must read as "not available" (finding L2).

    The mutation this kills: ``reported.get(key, 0.0)``, which rendered an
    absent measurement as "corrected 0.000/1k" — a number an operator could
    not tell apart from a paper measured at zero.
    """
    _write_body(tmp_path, "AAAA1111", COLON_PAPER)

    code = announce.main(["--corpus-dir", str(tmp_path), "--keys", "AAAA1111"])

    captured = capsys.readouterr()
    assert code == 0
    assert "reported not available  ->  corrected not available" in captured.out
    assert "0.000/1k" not in captured.out
    assert "Unweighted mean: not available" in captured.out


def test_the_corpus_dir_override_is_actually_read(tmp_path, capsys):
    """``--corpus-dir`` points the printer at any extraction.

    The mutation this kills: parsing the flag but going on to read
    ``DEFAULT_CORPUS_DIR``, which would silently audit the wrong corpus (or
    none) and still exit 0 on this fixture.
    """
    _write_body(tmp_path, "AAAA1111", COLON_PAPER)

    code = announce.main(["--corpus-dir", str(tmp_path), "--keys", "AAAA1111"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Ceramic scatters cluster near the ridge" in captured.out


# ---------------------------------------------------------------------------
# validate_passive_detection.py
# ---------------------------------------------------------------------------

def test_spacy_is_imported_inside_the_loader_not_at_module_scope():
    """The spaCy import is deferred, so the helpers stay importable without it.

    The mutation this kills: moving ``import spacy`` back to module scope,
    which makes every test in this file un-runnable wherever spaCy is absent —
    including this environment, where it is deliberately not installed.
    """
    tree = ast.parse(Path(passive.__file__).read_text(encoding="utf-8"))
    module_level_imports = {
        alias.name
        for node in tree.body if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "spacy" not in module_level_imports
    assert "import spacy" in inspect.getsource(passive.load_nlp)


def test_the_docstring_states_how_the_sample_differs_from_phase_one():
    """The "mirrors phase 1 exactly" claim is corrected (finding L4).

    Phase 1's ``passive_ratio`` counts passive verbs; this script counts
    sentences holding at least one trigger. Phase 1's other sentence metrics
    use ``split_sentences``, a paragraph-aware 5–200-word splitter, while the
    sentences sampled here are the raw ``doc.sents``. The mutation this kills:
    restoring the docstring that told a reader the two were interchangeable.
    """
    doc = passive.__doc__ or ""

    assert "split_sentences" in doc
    assert "doc.sents" in doc
    assert "5–200-word" in doc
    assert "cannot be substituted" in doc


def test_flagged_sentences_are_printed_as_a_worksheet(tmp_path, capsys):
    """A flagged sentence reaches the operator with its triggers and a blank verdict.

    The mutation this kills: dropping the ``nsubjpass``/``auxpass`` branch in
    ``find_passive_triggers``, after which nothing is ever flagged and the
    worksheet is empty.
    """
    _write_body(tmp_path, "AAAA1111", "The trench was recorded in the field.\n")
    nlp = FakeNlp([_passive_sentence()])

    code = passive.run(nlp, tmp_path, ["AAAA1111"])

    captured = capsys.readouterr()
    assert code == 0
    assert "The trench was recorded" in captured.out
    assert "nsubjpass: trench, head: recorded" in captured.out
    assert "auxpass: was, head: recorded" in captured.out
    assert "VERDICT" in captured.out


def test_a_missing_body_file_does_not_stop_the_passive_run(tmp_path, capsys):
    """One absent paper is reported and skipped; the readable ones still print.

    The mutation this kills: reverting to an unguarded read, which turned a
    single missing extraction into a traceback part-way through the worksheet
    (STT2).
    """
    _write_body(tmp_path, "AAAA1111", "The trench was recorded in the field.\n")
    nlp = FakeNlp([_passive_sentence()])

    code = passive.run(nlp, tmp_path, ["AAAA1111", "BBBB2222"])

    captured = capsys.readouterr()
    assert code == 0
    assert "SKIPPED" in captured.err
    assert "BBBB2222" in captured.err
    assert "1 SAMPLED FLAGGED SENTENCES" in captured.out


def test_an_empty_passive_sample_exits_non_zero(tmp_path, capsys):
    """A worksheet with no example on it must not exit 0 (finding STT2).

    The paper is readable and the parse is clean of passives, so there is
    nothing for a human to classify. The mutation this kills: the old
    unconditional ``return 0``, under which pointing the script at a corpus
    layout that no longer existed reported success on an empty report.
    """
    _write_body(tmp_path, "AAAA1111", "We recorded the trench in the field.\n")
    nlp = FakeNlp([_active_sentence()])

    code = passive.run(nlp, tmp_path, ["AAAA1111"])

    captured = capsys.readouterr()
    assert code == 1
    assert "EMPTY SAMPLE" in captured.err


def test_the_passive_printer_parses_its_corpus_and_key_overrides():
    """``--corpus-dir`` and ``--keys`` reach the driver.

    The mutation this kills: dropping either flag, which would pin the printer
    to one corpus layout and one fixed paper list — the state that made the
    superseded ``/tmp`` path unfixable from the command line.
    """
    args = passive.parse_args(
        ["--corpus-dir", "/nowhere/extracted", "--keys", "AAAA1111", "BBBB2222"]
    )

    assert args.corpus_dir == Path("/nowhere/extracted")
    assert args.keys == ["AAAA1111", "BBBB2222"]
