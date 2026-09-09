"""
Tests for the efficacy-experiment scripts under ``scripts/style-analyser/``:
``efficacy_build_prompts.py``, ``efficacy_build_reference.py``,
``efficacy_analyse.py`` and ``efficacy_score.py``.

The audit findings covered here:

* ST17 — citation stripping deleted "(Bulgaria in 2019)", which is a place and
  a date, while leaving the integrated form "Smith (2012)" in the injected
  guide; ST16 — the whitespace tidy-up collapsed nested-list indentation and
  the interior of fenced code blocks;
* STT-M4 — the experiment directory was created BEFORE the guide was read, so
  a missing guide left an empty directory as the only trace of the failure;
* ST10 — reference windows were accumulated on citation-inclusive text and
  stripped afterwards, so a "400-word" excerpt came out short, and the
  --min-words floor was applied before the strip; L5 — an empty excerpt list
  reached ``min()``;
* ST27 — the per-feature profile averaged over topics that were excluded from
  the pairing, so its C0 and C2 columns were computed over different topics.

``efficacy_score.py`` imports numpy through the Phase 5 evaluator, which is
not installed here, so its tests are marked ``integration`` and skip. Every
fixture is invented.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import (  # noqa: E402
    FakeNlp, FakeSent, FakeToken, load_style_module, refuse_sockets,
)

prompts = load_style_module("efficacy_build_prompts")
reference = load_style_module("efficacy_build_reference")
analyse = load_style_module("efficacy_analyse")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; these scripts are CPU-only."""
    refuse_sockets(monkeypatch)


# ---------------------------------------------------------------------------
# ST17 / ST16 — citation stripping and whitespace
# ---------------------------------------------------------------------------

def test_a_parenthetical_citation_is_removed():
    """The intended case, including a multi-work citation and a signal phrase."""
    assert prompts.strip_citations(
        "We used it (Niven 2011a; Whitmore and Dennis 2019).") == "We used it."
    assert prompts.strip_citations(
        "See (cf. Fish and Kowalewski 1990) for context.") == \
        "See for context."


def test_an_integrated_citation_is_removed():
    """"Smith (2012) argues" kept its year because the name is outside.

    The mutation this kills: deleting ``_INTEGRATED_CITE_RE``, which leaves a
    citation token in the guide the C2 condition injects.
    """
    assert prompts.strip_citations("Smith (2012) argues the opposite.") == \
        "Smith argues the opposite."


def test_a_year_bearing_parenthetical_that_is_not_a_citation_survives():
    """"(Bulgaria in 2019)" is a place and a date, and was being deleted.

    The mutation this kills: restoring the old
    ``\\([^()]*[A-Z][a-z]{2,}[^()]*(?:18|19|20)\\d{2}[^()]*\\)`` pattern.
    """
    assert prompts.strip_citations("Work in the field (Bulgaria in 2019) went "
                                   "on.") == \
        "Work in the field (Bulgaria in 2019) went on."


def test_year_free_parentheticals_are_untouched():
    """"(FAIR)" and "(12 articles)" are content, not citations."""
    text = "The data are open (FAIR) and reusable (12 articles)."

    assert prompts.strip_citations(text) == text


def test_nested_list_indentation_survives_the_tidy_up():
    """The guide is injected as Markdown; indentation is structure.

    The mutation this kills: restoring the bare ``  +`` collapse, which
    flattens a nested list into a flat one inside the C2 context.
    """
    text = "- item\n    - nested item with  doubled  spaces"

    assert prompts.strip_citations(text) == \
        "- item\n    - nested item with doubled spaces"


def test_a_fenced_block_is_left_exactly_as_written():
    """Alignment inside a code fence is deliberate."""
    text = "```python\nvalue   = 1\n```\nprose  with  spaces"

    assert prompts.strip_citations(text) == \
        "```python\nvalue   = 1\n```\nprose with spaces"


# ---------------------------------------------------------------------------
# The guide block and the manifest
# ---------------------------------------------------------------------------

GUIDE = """# Invented style guide

## How to read this guide

Read the sections in order.

### 1.1 A claim

**Status:** attested

The corpus does something measurable.

## Appendix A

Evidence tables that must NOT reach the prompt.

## Appendix F

An exemplar sentence, invented for this test.
"""


def _point_at_tmp(monkeypatch, tmp_path: Path, guide_text: str | None) -> Path:
    """Repoint every module path constant at a throwaway directory."""
    experiment = tmp_path / "experiment"
    guide = tmp_path / "guide.md"
    if guide_text is not None:
        guide.write_text(guide_text, encoding="utf-8")
    monkeypatch.setattr(prompts, "GUIDE_PATH", guide)
    monkeypatch.setattr(prompts, "EXPERIMENT_DIR", experiment)
    monkeypatch.setattr(prompts, "C2_CONTEXT_PATH",
                        experiment / "prompt-c2-context.md")
    monkeypatch.setattr(prompts, "MANIFEST_PATH", experiment / "prompts.json")
    return experiment


def test_the_c2_block_holds_the_guide_but_not_the_evidence_appendices(
        monkeypatch, tmp_path):
    """Appendix A is deliberately excluded from the injected context."""
    _point_at_tmp(monkeypatch, tmp_path, GUIDE)

    block = prompts.extract_guide_block()

    assert "Read the sections in order." in block
    assert "An exemplar sentence" in block
    assert "Evidence tables" not in block


def test_a_missing_section_marker_is_a_named_error(monkeypatch, tmp_path):
    """A renamed heading must fail loudly, not silently truncate the block."""
    _point_at_tmp(monkeypatch, tmp_path, "# A guide with no markers\n")

    with pytest.raises(ValueError, match="guide section marker not found"):
        prompts.extract_guide_block()


def test_only_the_c2_condition_carries_the_guide():
    """C0 and C1 must never see the guide text: that is the whole design."""
    manifest = prompts.build_manifest("GUIDE-CONTEXT-SENTINEL")

    by_condition = {r["condition"]: r["prompt"] for r in manifest["records"]}
    assert "GUIDE-CONTEXT-SENTINEL" in by_condition["C2"]
    assert "GUIDE-CONTEXT-SENTINEL" not in by_condition["C0"]
    assert "GUIDE-CONTEXT-SENTINEL" not in by_condition["C1"]


def test_a_missing_guide_leaves_no_experiment_directory(monkeypatch, tmp_path):
    """The failed run must leave no trace pretending it half-succeeded.

    The mutation this kills: restoring ``EXPERIMENT_DIR.mkdir(...)`` above the
    guide read (finding STT-M4).
    """
    experiment = _point_at_tmp(monkeypatch, tmp_path, None)

    assert prompts.main([]) == 2
    assert not experiment.exists()


def test_dry_run_writes_no_prompt_files(monkeypatch, tmp_path):
    """``--dry-run`` assembles everything and writes nothing."""
    experiment = _point_at_tmp(monkeypatch, tmp_path, GUIDE)

    assert prompts.main(["--dry-run"]) == 0
    assert not experiment.exists()


def test_a_written_manifest_records_the_guide_it_came_from(monkeypatch,
                                                           tmp_path):
    """Provenance ties the prompts to the exact guide bytes behind them."""
    experiment = _point_at_tmp(monkeypatch, tmp_path, GUIDE)

    assert prompts.main([]) == 0

    manifest = json.loads((experiment / "prompts.json").read_text(
        encoding="utf-8"))
    assert manifest["provenance"]["script"] == "efficacy_build_prompts.py"
    assert manifest["provenance"]["inputs"][0]["sha256"]


# ---------------------------------------------------------------------------
# ST10 — the length-matched reference
# ---------------------------------------------------------------------------

def _windows_nlp(sentence_lengths: list[int]) -> FakeNlp:
    """A scripted pipeline whose sentences have the given word counts."""
    return FakeNlp([FakeSent([FakeToken("word") for _ in range(n)])
                    for n in sentence_lengths])


def test_a_short_trailing_window_is_dropped():
    """The floor exists so a stub excerpt cannot enter the reference.

    The mutation this kills: dropping the ``n >= min_words`` condition on the
    trailing window.
    """
    nlp = _windows_nlp([100, 100, 100, 20])

    windows = reference.sentence_windows("ignored", nlp, target_words=200,
                                         min_words=150)

    assert len(windows) == 1


def test_a_long_enough_trailing_window_is_kept():
    """The complement of the previous test, so the floor is not a wall."""
    nlp = _windows_nlp([100, 100, 60])

    windows = reference.sentence_windows("ignored", nlp, target_words=200,
                                         min_words=50)

    assert len(windows) == 2


def test_the_reference_module_imports_without_numpy():
    """Its pure helpers must stay testable where numpy is absent.

    The mutation this kills: restoring ``import phase5_evaluator as p5`` at
    module scope, which makes this whole file uncollectable.
    """
    assert reference.sentence_windows is not None
    assert "phase5_evaluator" not in sys.modules


# ---------------------------------------------------------------------------
# ST27 — the per-feature profile
# ---------------------------------------------------------------------------

def _scores(tmp_path: Path) -> Path:
    """Three topics x three conditions, with one topic missing C1."""
    rows = []
    for topic, stratum in (("T1", "on-domain"), ("T2", "off-domain"),
                           ("T3", "off-domain")):
        for condition in ("C0", "C1", "C2"):
            if topic == "T3" and condition == "C1":
                continue                      # incomplete topic
            for rep in (1, 2):
                rows.append({
                    "file": f"{topic}__{condition}__rep{rep}.md",
                    "topic_id": topic, "stratum": stratum,
                    "condition": condition, "rep": rep,
                    "distance": {"C0": 5.0, "C1": 4.0, "C2": 3.0}[condition],
                    "envelope_band": "within",
                    "gate_n_pass": 6,
                    "feature_deltas": [
                        {"feature": "shared_feature",
                         "z": 1.0 if topic != "T3" else 9.0},
                    ],
                })
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "scores.json").write_text(json.dumps({
        "experiment": "invented", "n_passages": len(rows),
        "loo_summary": {"n": 4, "mean": 2.0, "stdev": 1.0, "max": 4.0,
                        "median": 2.0},
        "results": rows,
    }), encoding="utf-8")
    return experiment


def test_the_feature_profile_uses_only_paired_topics(tmp_path):
    """A topic excluded from the pairing must not enter the profile.

    T3 has no C1 cell, so it is excluded from every paired comparison; its
    |z| of 9.0 used to be averaged into the C0 and C2 columns anyway. The
    mutation this kills: iterating ``rows`` instead of ``paired_rows``.
    """
    experiment = _scores(tmp_path)

    assert analyse.main(["--experiment-dir", str(experiment)]) == 0

    analysis = json.loads((experiment / "analysis.json").read_text(
        encoding="utf-8"))
    assert analysis["incomplete_topics"] == ["T3"]
    # Two complete topics, three conditions, two replicates each.
    assert analysis["n_rows_in_feature_profile"] == 12
    profile = {e["feature"]: e for e in analysis["feature_profile"]}
    assert profile["shared_feature"]["mean_abs_z_C0"] == 1.0


def test_the_exact_sign_flip_test_matches_its_documented_minimum():
    """Four positive differences give the documented p = 1/16."""
    assert analyse.exact_signflip_p([1.0, 2.0, 3.0, 4.0])[0] == 0.0625


def test_zero_differences_drop_out_of_the_flip_set():
    """A tie contributes to neither tail, per the sign-flip convention."""
    assert analyse.exact_signflip_p([0.0, 0.0]) == (1.0, 1.0)


def test_the_effect_size_is_none_when_the_corpus_sd_is_zero():
    """No division by a zero spread; the field says so instead."""
    block = analyse.paired_block({("T1", "C0"): 2.0, ("T1", "C2"): 1.0},
                                 ["T1"], "C0", "C2", 0.0)

    assert block["effect_size_loo_sd"] is None


def test_a_paired_block_never_reaches_outside_its_topics():
    """Pairing is strictly within a topic — the unit of the design."""
    cells = {("T1", "C0"): 5.0, ("T1", "C2"): 3.0,
             ("T2", "C0"): 9.0, ("T2", "C2"): 1.0}

    block = analyse.paired_block(cells, ["T1"], "C0", "C2", 1.0)

    assert block["n_topics"] == 1
    assert block["per_topic"][0]["diff"] == 2.0


def test_analyse_dry_run_writes_nothing(tmp_path):
    """``--dry-run`` prints the analysis and writes no file."""
    experiment = _scores(tmp_path)

    assert analyse.main(["--experiment-dir", str(experiment),
                         "--dry-run"]) == 0
    assert not (experiment / "analysis.json").exists()
    assert not (experiment / "analysis.md").exists()


def test_a_missing_scores_file_exits_two(tmp_path):
    """Nothing to analyse is a diagnostic, not a traceback."""
    assert analyse.main(["--experiment-dir", str(tmp_path)]) == 2


# ---------------------------------------------------------------------------
# efficacy_score.py — needs numpy through the Phase 5 evaluator
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_the_passage_filename_pattern_accepts_and_rejects():
    """`A1__C2__rep1` parses; a malformed name is skipped, not scored."""
    pytest.importorskip("numpy")
    score = load_style_module("efficacy_score")

    assert score.FNAME_RE.match("A1__C2__rep1")
    assert score.FNAME_RE.match("draft-A1-C2") is None


@pytest.mark.integration
def test_scoring_no_passage_at_all_exits_two(tmp_path):
    """An empty passages directory must not write a scores.json of zeroes."""
    pytest.importorskip("numpy")
    score = load_style_module("efficacy_score")
    (tmp_path / "passages").mkdir()

    assert score.main(["--experiment-dir", str(tmp_path)]) == 2


# ---------------------------------------------------------------------------
# The scorer's phase inputs (round 4g-3 item 4; round 4g-5 item M-a1)
# ---------------------------------------------------------------------------

def _score_main_ast():
    """Return the AST of ``efficacy_score.main`` without importing it.

    The module imports the Phase 5 evaluator, and so numpy, at module scope,
    and numpy is deliberately absent here.
    """
    import ast

    from style_test_helpers import SCRIPTS_DIR

    source = (SCRIPTS_DIR / "efficacy_score.py").read_text(encoding="utf-8")
    return ast.parse(source), next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "main")


def _call_name(call) -> str | None:
    """The name a call resolves to, for `f()` and `mod.f()` alike."""
    import ast

    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_the_scorer_loads_every_phase_input_through_the_checked_loader():
    """One call, before anything reads a corpus, covering all three inputs.

    ``load_checked_payloads`` refuses before returning any payload — tested
    directly, without numpy, in ``tests/test_style_support.py`` — so what
    matters here is that ``main`` obtains its phase files from it, passes
    every one of them, and does so before ``load_corpus_space`` builds the
    feature space, fits the model, and computes the envelope.

    The mutation this kills: reverting to the hand-rolled loop, whose
    ordering could only be asserted by reading the source and whose guard
    ``if candidate is None or candidate.exists(): continue`` — one word
    changed — skipped every file that existed with all 24 tests green.
    """
    import ast

    _module, main_fn = _score_main_ast()
    loader_calls = [node for node in ast.walk(main_fn)
                    if isinstance(node, ast.Call)
                    and _call_name(node) == "load_checked_payloads"]

    assert len(loader_calls) == 1

    # Every phase input this script reads must be in the list it hands over.
    passed = {element.attr for element in ast.walk(loader_calls[0])
              if isinstance(element, ast.Attribute)
              and isinstance(element.value, ast.Name)
              and element.value.id == "args"}
    assert {"phase1", "phase3", "reference_phase1"} <= passed

    consumers = [(_call_name(node), node.lineno) for node in ast.walk(main_fn)
                 if isinstance(node, ast.Call)
                 and _call_name(node) in ("load_corpus_space", "evaluate_text",
                                          "evaluation_to_dict")]
    assert consumers, "no phase-consuming call found in main()"
    first_name, first_line = min(consumers, key=lambda pair: pair[1])
    assert loader_calls[0].lineno < first_line, (
        f"the phase files are loaded after {first_name}() has already run"
    )


# ---------------------------------------------------------------------------
# Round 4g-5 item L-b2 — one base moves the WHOLE experiment
# ---------------------------------------------------------------------------

def test_every_script_derives_the_experiment_root_from_the_shared_base():
    """A "second experiment" must not be assembled half in each directory.

    Repointing the base used to move --judge-dir and --key-dir only:
    --passages-dir and four other scripts kept their own hard-coded copy of
    the root, so a second experiment would have written its passages,
    prompts, scores and analysis into the first one. The mutation this kills:
    restoring any of those hard-coded roots (each assertion below fails
    against a literal path, since the shared helper is what they are compared
    with).
    """
    style_support = load_style_module("style_support")
    root = style_support.experiment_root()

    assert load_style_module("efficacy_build_judge_tasks").EXP == root
    assert load_style_module("efficacy_build_prompts").EXPERIMENT_DIR == root
    assert load_style_module("efficacy_build_reference").EXPERIMENT_DIR == root
    assert load_style_module("efficacy_analyse").DEFAULT_EXPERIMENT_DIR == root
    # efficacy_score imports numpy through the Phase 5 evaluator, so its
    # constant is read from the source rather than by importing it.
    import ast

    from style_test_helpers import SCRIPTS_DIR

    source = (SCRIPTS_DIR / "efficacy_score.py").read_text(encoding="utf-8")
    assignment = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "DEFAULT_EXPERIMENT_DIR"
                for t in node.targets)
    )
    assert isinstance(assignment.value, ast.Call)
    assert assignment.value.func.attr == "experiment_root"


def test_the_passages_directory_moves_with_the_base(monkeypatch, tmp_path):
    """The path L-b2 found left behind: passages stayed in the old root."""
    style_support = load_style_module("style_support")
    monkeypatch.setattr(style_support, "EXPERIMENT_DEFAULT", tmp_path)

    assert style_support.passages_dir() == tmp_path / "passages"
    assert style_support.judge_dir() == tmp_path / "judge-tasks"
    assert style_support.judge_key_dir() == tmp_path / "private" / "judge-key"
