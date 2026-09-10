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
    """One call, a literal list, and the payloads FED to the consumer.

    ``load_checked_payloads`` refuses before returning any payload — tested
    directly, without numpy, in ``tests/test_style_support.py``. What this
    asserts is that ``main`` cannot route around it: the list it hands over
    is a non-empty literal naming all three inputs (a filtering comprehension
    is how ``if p is not None`` became ``if p is None`` and handed the loader
    an empty list), the result is unpacked, and those unpacked names are what
    ``load_corpus_space`` receives — so no file is read again after the
    check.

    The mutations this kills: emptying or filtering the list; `if problem:` →
    `if False:`; and passing ``args.phase1``-style PATHS to
    ``load_corpus_space`` again, which is the check-then-reload this replaces.
    """
    import ast

    _module, main_fn = _score_main_ast()
    loader_calls = [node for node in ast.walk(main_fn)
                    if isinstance(node, ast.Call)
                    and _call_name(node) == "load_checked_payloads"]

    assert len(loader_calls) == 1
    argument = loader_calls[0].args[0]
    assert isinstance(argument, ast.List), (
        "the inputs must be a literal list, not a comprehension that can "
        "filter every one of them away"
    )
    assert len(argument.elts) == 3, "all three phase inputs must be checked"
    passed = {element.attr for element in argument.elts
              if isinstance(element, ast.Attribute)
              and isinstance(element.value, ast.Name)
              and element.value.id == "args"}
    assert passed == {"phase1", "phase3", "reference_phase1"}

    # The loader's return is unpacked, and the unpacked names are what the
    # corpus builder is given.
    # ...and the refusal is acted on. `if problem:` -> `if False:` leaves the
    # loader's verdict computed and ignored, which is a check in name only.
    guards = [node for node in ast.walk(main_fn)
              if isinstance(node, ast.If)
              and isinstance(node.test, ast.Name)
              and node.test.id == "problem"
              and any(isinstance(inner, ast.Return)
                      and getattr(inner.value, "value", 0) != 0
                      for inner in ast.walk(node))]
    assert guards, (
        "the loader's `problem` must be tested and returned on, not computed "
        "and discarded"
    )

    unpacked = [node for node in ast.walk(main_fn)
                if isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Tuple)
                and isinstance(node.value, ast.Name)
                and node.value.id == "payloads"]
    assert unpacked, "the loader's payloads must be unpacked, not discarded"
    names = [element.id for element in unpacked[0].targets[0].elts]
    assert names == ["phase1", "phase3", "reference_phase1"]

    space_calls = [node for node in ast.walk(main_fn)
                   if isinstance(node, ast.Call)
                   and _call_name(node) == "load_corpus_space"]
    assert len(space_calls) == 1
    given = [element.id for element in space_calls[0].args
             if isinstance(element, ast.Name)]
    assert set(names) <= set(given), (
        "load_corpus_space must receive the checked payloads, not the paths"
    )
    assert not [element for element in ast.walk(space_calls[0])
                if isinstance(element, ast.Attribute)
                and isinstance(element.value, ast.Name)
                and element.value.id == "args"
                and element.attr in {"phase1", "phase3", "reference_phase1"}], (
        "a phase PATH reaching load_corpus_space means the file is read again"
    )

    consumers = [(_call_name(node), node.lineno) for node in ast.walk(main_fn)
                 if isinstance(node, ast.Call)
                 and _call_name(node) in ("load_corpus_space", "evaluate_text",
                                          "evaluation_to_dict")]
    assert consumers, "no phase-consuming call found in main()"
    first_name, first_line = min(consumers, key=lambda pair: pair[1])
    assert loader_calls[0].lineno < first_line, (
        f"the phase files are loaded after {first_name}() has already run"
    )


def test_the_scorer_reads_no_phase_file_after_the_check():
    """The only reader of these files is the checked loader.

    ``load_corpus_space`` used to re-read all three with ``p5.load_json``,
    so the stamp check ran over one set of bytes and the scoring over
    another. The mutation this kills: restoring any ``load_json`` call in
    this module.
    """
    from style_test_helpers import SCRIPTS_DIR

    source = (SCRIPTS_DIR / "efficacy_score.py").read_text(encoding="utf-8")

    assert "load_json" not in source


# ---------------------------------------------------------------------------
# Round 4g-5 item L-b2 — one base moves the WHOLE experiment
# ---------------------------------------------------------------------------

#: Every script that names an experiment path, and the constant it uses.
_ROOT_CONSTANTS = (
    ("efficacy_build_judge_tasks.py", "JUDGE_DIR"),
    ("efficacy_build_judge_tasks.py", "PRIVATE_DIR"),
    ("efficacy_build_judge_tasks.py", "KEY_DIR"),
    ("efficacy_build_prompts.py", "EXPERIMENT_DIR"),
    ("efficacy_build_reference.py", "EXPERIMENT_DIR"),
    ("efficacy_analyse.py", "DEFAULT_EXPERIMENT_DIR"),
    ("efficacy_score.py", "DEFAULT_EXPERIMENT_DIR"),
    ("efficacy_score_judges.py", "JUDGE_DIR_DEFAULT"),
    ("efficacy_score_judges.py", "KEY_DIR_DEFAULT"),
)

#: The style_support helpers that derive a path from the shared base.
_LAYOUT_HELPERS = {"experiment_root", "judge_dir", "private_dir",
                   "judge_key_dir", "passages_dir"}


def _module_constant_value(filename: str, name: str):
    """Return the AST of the value assigned to a module-level constant."""
    import ast

    from style_test_helpers import SCRIPTS_DIR

    source = (SCRIPTS_DIR / filename).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
                getattr(target, "id", None) == name for target in node.targets):
            return node.value
    raise AssertionError(f"{filename} no longer defines {name}")


def test_every_experiment_path_is_derived_not_spelled_out():
    """Derivation, asserted structurally rather than by comparing values.

    Comparing the constant with the helper's RESULT passes just as happily
    when the constant is a literal that spells the same path — which is how
    reverting three of these to their hard-coded strings survived (round
    4g-6, M2). What has to hold is that each constant is *computed* from the
    shared base, so repointing that base moves it. The mutation this kills:
    replacing any of these with a literal path.
    """
    import ast

    for filename, name in _ROOT_CONSTANTS:
        value = _module_constant_value(filename, name)
        calls = [node for node in ast.walk(value)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr in _LAYOUT_HELPERS
                 and getattr(node.func.value, "id", None) == "style_support"]
        assert calls, (
            f"{filename}:{name} does not derive from style_support's layout "
            "helpers, so repointing the experiment root would not move it"
        )


def test_the_passages_directory_moves_with_the_base(monkeypatch, tmp_path):
    """The path L-b2 found left behind: passages stayed in the old root."""
    style_support = load_style_module("style_support")
    monkeypatch.setattr(style_support, "EXPERIMENT_DEFAULT", tmp_path)

    assert style_support.passages_dir() == tmp_path / "passages"
    assert style_support.judge_dir() == tmp_path / "judge-tasks"
    assert style_support.judge_key_dir() == tmp_path / "private" / "judge-key"
