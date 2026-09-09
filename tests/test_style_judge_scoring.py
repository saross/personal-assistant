"""
Tests for ``scripts/style-analyser/efficacy_score_judges.py``.

The audit found the headline number of the blind pairwise judge test to be
untrustworthy in three separate ways (findings ST1, ST2 and ST13):

* a tie, a refusal, or an empty ``choice`` scored as a win for the *baseline*,
  because the tally was ``picked_guide = choice == guide_side``;
* the judgements file was read with a bare ``json.loads`` per line, so a
  fenced answer or a prose refusal aborted the run, an empty file divided by
  zero, and a duplicated pair id was counted twice;
* the two counterbalanced orders of one pair — the same two passages, shown
  to two judges in opposite positions — were tallied as two independent
  trials, with no test of any kind attached.

Every fixture here is invented. The real judge run, its passages, and its
topics are private corpus material and are never copied into this repository.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import load_style_module, refuse_sockets  # noqa: E402

scorer = load_style_module("efficacy_score_judges")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; this script is CPU-only."""
    refuse_sockets(monkeypatch)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _pair(pair_id: str, topic: str, order: int,
          contrast: str = "CXvC0") -> dict:
    """One ordered mapping entry, in the shape the build script writes."""
    return {
        "pair_id": pair_id,
        "topic_id": topic,
        "contrast": contrast,
        "guide_condition": "CX",
        "order": order,
        "guide_side": "A" if order == 0 else "B",
        "unordered_pair_id": f"{contrast}|{topic}",
    }


def _write_case(tmp_path: Path, pairs: list[dict],
                judgement_lines: list[str]) -> tuple[Path, Path, Path]:
    """Lay out a judge directory, a key directory, and an output directory."""
    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "judge-key"
    out_dir = tmp_path / "out"
    judge_dir.mkdir()
    key_dir.mkdir()
    out_dir.mkdir()
    (key_dir / "judge-mapping.json").write_text(
        json.dumps({"n_pairs": len(pairs), "pairs": pairs}, indent=2),
        encoding="utf-8")
    (judge_dir / "judgments.jsonl").write_text(
        "\n".join(judgement_lines) + ("\n" if judgement_lines else ""),
        encoding="utf-8")
    return judge_dir, key_dir, out_dir


def _run(judge_dir: Path, key_dir: Path, out_dir: Path,
         *extra: str) -> int:
    """Invoke the scorer's ``main`` with explicit directories."""
    return scorer.main([
        "--judge-dir", str(judge_dir), "--key-dir", str(key_dir),
        "--out-dir", str(out_dir), *extra,
    ])


def _summary(out_dir: Path) -> dict:
    """Read back the JSON summary the run wrote."""
    return json.loads((out_dir / "judge-analysis.json").read_text(
        encoding="utf-8"))


# ---------------------------------------------------------------------------
# ST1 — an unusable answer is never a win for either side
# ---------------------------------------------------------------------------

def test_a_tie_is_not_counted_as_a_baseline_win(tmp_path):
    """A judge that declined to choose must not hand the point to "plain".

    The mutation this kills: restoring
    ``picked_guide = choice == guide_side``, under which the "tie" line below
    becomes a baseline win and the pair comes out split rather than a guide
    win.
    """
    pairs = [_pair("pair00", "Z1", 0), _pair("pair01", "Z1", 1)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A", "confidence": "high"}),
        json.dumps({"pair_id": "pair01", "choice": "tie",
                    "confidence": "low"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    summary = _summary(out_dir)
    assert summary["n_unusable"] == 1
    assert summary["pairs"] == {"guide": 1, "plain": 0, "tie": 0}
    assert summary["raw_letter_choices"] == {"A": 1}


def test_an_empty_choice_is_unusable(tmp_path):
    """The empty-string case from the audit, kept as its own regression.

    The mutation this kills: accepting any string as a choice (dropping the
    ``normalised not in VALID_CHOICES`` guard).
    """
    judgement = scorer.parse_judgement(
        json.dumps({"pair_id": "pair00", "choice": ""}), 1)

    assert judgement.usable is False
    assert "not one of" in judgement.reason


# ---------------------------------------------------------------------------
# ST2 — tolerant reading, and structural errors reported rather than raised
# ---------------------------------------------------------------------------

def test_a_fenced_answer_is_read_rather_than_crashing_the_run(tmp_path):
    """A judge that wrapped its JSON in a code fence must still be scored.

    The mutation this kills: reverting ``parse_judgement`` to a bare
    ``json.loads(line)``, which raises JSONDecodeError on this line.
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        '```json {"pair_id": "pair00", "choice": "A", "confidence": "high"} ```',
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0
    assert _summary(out_dir)["n_usable"] == 1


def test_a_prose_refusal_is_recorded_as_unusable(tmp_path):
    """Prose in the answers file is a diagnostic, not a crash and not a win.

    The mutation this kills: dropping the ``payload is None`` branch, which
    would raise instead of classifying the line.
    """
    pairs = [_pair("pair00", "Z1", 0), _pair("pair01", "Z1", 1)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
        "I am not able to judge between these two passages.",
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    summary = _summary(out_dir)
    assert summary["n_unusable"] == 1
    assert summary["unusable_reasons"] == {"not parseable as JSON": 1}


def test_an_empty_judgements_file_is_a_diagnostic_with_a_non_zero_exit(tmp_path):
    """Zero judgements used to divide by zero; it must now stop the run.

    The mutation this kills: removing the ``if not judgements`` guard, which
    restores the ZeroDivisionError (and, once that is caught, a 0/0 report
    that reads like a measurement).
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [])

    assert _run(judge_dir, key_dir, out_dir) == 1
    assert not (out_dir / "judge-analysis.json").exists()


def test_a_pair_judged_twice_is_an_error(tmp_path):
    """One judgement counted twice used to produce a "2/2" from one answer.

    The mutation this kills: dropping the duplicate branch of
    ``check_judgement_ids``.
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 1
    assert not (out_dir / "judge-analysis.json").exists()


def test_a_judgement_for_an_unknown_pair_is_an_error(tmp_path):
    """A stale or invented pair id must stop the run, not raise a KeyError.

    The mutation this kills: dropping the unknown-pair branch of
    ``check_judgement_ids``.
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair99", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 1


def test_a_key_listing_one_pair_id_twice_is_an_error(tmp_path):
    """An ambiguous key makes every judgement naming that id meaningless."""
    pairs = [_pair("pair00", "Z1", 0), _pair("pair00", "Z2", 1)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 1


def test_a_pair_with_no_judgement_is_reported_as_incomplete(tmp_path):
    """A missing answer used to vanish; it is now named in the report.

    The mutation this kills: dropping the ``incomplete`` computation, which
    lets a half-finished judge run look complete.
    """
    pairs = [_pair("pair00", "Z1", 0), _pair("pair01", "Z2", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    summary = _summary(out_dir)
    assert summary["incomplete_pairs"] == ["CXvC0|Z2"]
    assert "Incomplete" in (out_dir / "judge-analysis.md").read_text(
        encoding="utf-8")


# ---------------------------------------------------------------------------
# ST13 — the two orders of one pair are one observation
# ---------------------------------------------------------------------------

def test_both_orders_of_one_pair_count_as_a_single_observation(tmp_path):
    """Two judgements of the same content are one paired observation.

    The mutation this kills: tallying judgements instead of collapsed pairs
    (``guide`` would be 2 and the sign test would see two trials, halving the
    honest p-value).
    """
    pairs = [_pair("pair00", "Z1", 0), _pair("pair01", "Z1", 1)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        # order 0 has the guide as A; order 1 has it as B. Both judges chose
        # the guide.
        json.dumps({"pair_id": "pair00", "choice": "A"}),
        json.dumps({"pair_id": "pair01", "choice": "B"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    summary = _summary(out_dir)
    assert summary["n_judgements"] == 2
    assert summary["pairs"] == {"guide": 1, "plain": 0, "tie": 0}
    assert summary["sign_test"]["n_decided_pairs"] == 1


def test_a_pair_whose_orders_disagree_is_a_tie(tmp_path):
    """Disagreement across orders is position bias, not a preference."""
    pairs = [_pair("pair00", "Z1", 0), _pair("pair01", "Z1", 1)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),   # guide
        json.dumps({"pair_id": "pair01", "choice": "A"}),   # plain
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    summary = _summary(out_dir)
    assert summary["pairs"] == {"guide": 0, "plain": 0, "tie": 1}
    assert summary["sign_test"]["n_decided_pairs"] == 0
    assert summary["sign_test"]["p_one_sided"] == 1.0


def test_the_sign_test_matches_hand_computed_binomial_values():
    """Four guide-preferring pairs out of four: p = 1/16, two-sided 1/8.

    The mutation this kills: dropping the ``+ 1`` from the upper-tail range
    (which would report p = 0 for a clean sweep).
    """
    assert scorer.sign_test(4, 0) == (0.0625, 0.125)
    assert scorer.sign_test(2, 2) == (0.6875, 1.0)
    assert scorer.sign_test(0, 0) == (1.0, 1.0)


# ---------------------------------------------------------------------------
# STT-M6 — the prose follows the data
# ---------------------------------------------------------------------------

def test_the_topic_table_comes_from_the_mapping(tmp_path):
    """Topics are read from the key, not from a hard-coded four-topic list.

    The mutation this kills: restoring ``for t in ["A1", "A2", "B1", "B3"]``,
    which prints 0/0 rows for topics nobody ran and omits the ones that were.
    """
    pairs = [_pair("pair00", "Q7", 0), _pair("pair01", "Q8", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
        json.dumps({"pair_id": "pair01", "choice": "B"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    report = (out_dir / "judge-analysis.md").read_text(encoding="utf-8")
    assert "| Q7 |" in report and "| Q8 |" in report
    assert "A1" not in report
    assert _summary(out_dir)["topics"] == ["Q7", "Q8"]


def test_the_letter_lean_sentence_follows_the_counts():
    """The old report said "mild B-lean" whatever the judgements said.

    The mutation this kills: hard-coding the direction of the lean.
    """
    from collections import Counter

    assert "A-lean" in scorer.letter_lean_sentence(Counter({"A": 9, "B": 1}))
    assert "B-lean" in scorer.letter_lean_sentence(Counter({"A": 1, "B": 9}))
    assert "no letter lean" in scorer.letter_lean_sentence(
        Counter({"A": 4, "B": 4}))


# ---------------------------------------------------------------------------
# Cross-cutting: dry run, atomic writes, provenance
# ---------------------------------------------------------------------------

def test_dry_run_writes_no_bytes(tmp_path):
    """``--dry-run`` must produce a report on stdout and nothing on disk.

    The mutation this kills: passing ``dry_run=False`` to the writers.
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir, "--dry-run") == 0
    assert list(out_dir.iterdir()) == []


def test_the_summary_carries_provenance_and_re_runs_byte_identically(tmp_path):
    """Provenance ties a result to its inputs, and a re-run must not drift.

    The mutation this kills: dropping the ``provenance`` key from the summary
    (nothing else in the suite would notice), and any wall-clock field added
    to it (the second run's bytes would differ).
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0
    first = (out_dir / "judge-analysis.json").read_bytes()
    provenance = _summary(out_dir)["provenance"]
    assert provenance["script"] == "efficacy_score_judges.py"
    assert [Path(i["path"]).name for i in provenance["inputs"]] == [
        "judge-mapping.json", "judgments.jsonl"]
    assert all(i["sha256"] for i in provenance["inputs"])

    assert _run(judge_dir, key_dir, out_dir) == 0
    assert (out_dir / "judge-analysis.json").read_bytes() == first


def test_a_key_left_in_the_judge_directory_is_read_but_flagged(tmp_path, capsys):
    """Archived runs stay scoreable, loudly: the key was inside the blind dir.

    The mutation this kills: dropping the legacy fallback (an archived
    experiment could no longer be scored at all) or dropping its warning (the
    blinding leak would go unremarked).
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])
    legacy = judge_dir / "judge-mapping.json"
    legacy.write_text((key_dir / "judge-mapping.json").read_text(
        encoding="utf-8"), encoding="utf-8")
    (key_dir / "judge-mapping.json").unlink()

    assert _run(judge_dir, key_dir, out_dir) == 0
    assert "inside the directory the judge reads" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Re-audit item 2 — a key that cannot identify its pairs is not scoreable
# ---------------------------------------------------------------------------

def _anonymous_pair(pair_id: str, guide_side: str = "A") -> dict:
    """A legacy-shaped key entry with no identity fields at all."""
    return {"pair_id": pair_id, "guide_side": guide_side}


def test_a_key_without_pair_identities_is_refused(tmp_path, capsys):
    """Every entry collapsing to "?|?|?" reported p = 1.0 and exited 0.

    Eight judgements became "1 unordered pair", the tallies came out "0/0
    decided", and the run passed. The mutation this kills: restoring the
    ``str(entry.get(field, "?"))`` fallback in ``unordered_pair_key``.
    """
    pairs = [_anonymous_pair(f"pair{i:02d}") for i in range(8)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": f"pair{i:02d}", "choice": "A"})
        for i in range(8)
    ])

    assert _run(judge_dir, key_dir, out_dir) == 1
    assert not (out_dir / "judge-analysis.json").exists()
    assert "do not say which unordered pair" in capsys.readouterr().err


def test_a_key_entry_missing_one_identity_field_is_refused(tmp_path):
    """Two of the three fallback fields is not an identity either."""
    entry = _pair("pair00", "Z1", 0)
    del entry["unordered_pair_id"]
    del entry["guide_condition"]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, [entry], [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 1


def test_a_legacy_key_with_all_three_fields_still_scores(tmp_path):
    """The fallback must keep working where it can actually identify a pair."""
    entry = _pair("pair00", "Z1", 0)
    del entry["unordered_pair_id"]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, [entry], [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0
    assert _summary(out_dir)["n_pairs_judged"] == 1


def test_more_than_two_orders_per_pair_is_fatal(tmp_path, capsys):
    """A pair has two orders; a higher ratio means shared identities.

    The mutation this kills: dropping the MAX_ORDERS_PER_PAIR check, which
    lets a key whose entries share one identity report tallies computed over
    the wrong groups.
    """
    pairs = [_pair(f"pair{i:02d}", "Z1", i % 2) for i in range(6)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": "A"}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 1
    assert "orders per pair" in capsys.readouterr().err


def test_a_bare_code_fence_is_not_counted_as_a_judgement(tmp_path):
    """A judge's formatting must not inflate the unusable count.

    The mutation this kills: dropping the fence filter, which counts ``` as an
    unusable judgement and reports two answers where one was given.
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        "```json",
        json.dumps({"pair_id": "pair00", "choice": "A"}),
        "```",
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    summary = _summary(out_dir)
    assert summary["n_judgements"] == 1
    assert summary["n_unusable"] == 0


def test_a_lower_case_choice_still_counts(tmp_path):
    """Judges answer "a" as often as "A"; the normalisation must survive.

    The mutation this kills: dropping ``.upper()`` from the choice
    normalisation, which turns every lower-case answer into an unusable
    record and silently halves the evidence.
    """
    pairs = [_pair("pair00", "Z1", 0)]
    judge_dir, key_dir, out_dir = _write_case(tmp_path, pairs, [
        json.dumps({"pair_id": "pair00", "choice": " a "}),
    ])

    assert _run(judge_dir, key_dir, out_dir) == 0

    summary = _summary(out_dir)
    assert summary["n_usable"] == 1
    assert summary["pairs"] == {"guide": 1, "plain": 0, "tie": 0}


# ---------------------------------------------------------------------------
# Round 4g-3 item 1 — the builder's key location and the scorer's must agree
# ---------------------------------------------------------------------------

builder = load_style_module("efficacy_build_judge_tasks")


def test_the_scorer_looks_where_the_builder_writes():
    """One constant moved and the other did not, and nothing noticed.

    The builder put the key under ``private/``; the scorer kept defaulting to
    the old sibling directory, so a run at the defaults after --migrate-key
    reported "No judge-mapping.json found" and exited 2 with the key sitting
    exactly where it belonged. The mutation this kills: reverting
    ``KEY_DIR_DEFAULT`` to ``EXP / "judge-key"``.
    """
    assert scorer.KEY_DIR_DEFAULT == builder.KEY_DIR
    assert scorer.JUDGE_DIR_DEFAULT == builder.JUDGE_DIR
    assert scorer.KEY_DIR_DEFAULT.parent.name == "private"


def _experiment_at(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Point both modules' defaults at a throwaway experiment directory."""
    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "private" / "judge-key"
    monkeypatch.setattr(builder, "JUDGE_DIR", judge_dir)
    monkeypatch.setattr(builder, "KEY_DIR", key_dir)
    monkeypatch.setattr(scorer, "JUDGE_DIR_DEFAULT", judge_dir)
    monkeypatch.setattr(scorer, "KEY_DIR_DEFAULT", key_dir)
    return judge_dir, key_dir


def _passages_for(tmp_path: Path, topics: list[str]) -> Path:
    """One distinguishable passage per (topic, condition) cell."""
    passages = tmp_path / "passages"
    passages.mkdir()
    for topic in topics:
        for condition in ("C0", "CX"):
            (passages / f"{topic}__{condition}__rep1.md").write_text(
                f"Invented passage for {topic} under {condition}.\n",
                encoding="utf-8")
    return passages


def test_a_built_experiment_scores_at_the_defaults(tmp_path, monkeypatch):
    """Build, judge, score — with no path arguments anywhere.

    This is the round trip the mismatch broke. The mutation this kills: any
    future divergence between the two modules' key locations, which this
    exercises rather than merely asserting.
    """
    judge_dir, key_dir = _experiment_at(tmp_path, monkeypatch)
    judge_dir.mkdir()
    key_dir.mkdir(parents=True)
    topics = ["T1", "T2"]
    plan = builder.plan_pairs(4, contrasts=[("CXvC0", "CX")], topics=topics)
    builder.emit_tasks(plan, _passages_for(tmp_path, topics), judge_dir,
                       key_dir, "# Reference\n", seed=4)

    # The judges answer every pair, each choosing the guide's side.
    answers = [json.dumps({"pair_id": entry["pair_id"],
                           "choice": entry["guide_side"]}) for entry in plan]
    (judge_dir / "judgments.jsonl").write_text("\n".join(answers) + "\n",
                                               encoding="utf-8")

    assert scorer.main([]) == 0
    assert (tmp_path / "judge-analysis.json").exists()


def test_a_migrated_legacy_key_scores_at_the_defaults(tmp_path, monkeypatch):
    """--migrate-key moves the key; the scorer must then find it unaided.

    The mutation this kills: migrating into a directory the scorer does not
    read, which is the state this round found — migration "succeeded" and the
    next scoring run exited 2.
    """
    judge_dir, key_dir = _experiment_at(tmp_path, monkeypatch)
    judge_dir.mkdir()
    pairs = [_pair("pair00", "Z1", 0)]
    # The legacy layout: the key inside the directory the judges read.
    (judge_dir / "judge-mapping.json").write_text(
        json.dumps({"n_pairs": 1, "pairs": pairs}), encoding="utf-8")
    (judge_dir / "judgments.jsonl").write_text(
        json.dumps({"pair_id": "pair00", "choice": "A"}) + "\n",
        encoding="utf-8")

    assert builder.migrate_key(judge_dir, key_dir) == 0
    assert scorer.main([]) == 0
    assert (tmp_path / "judge-analysis.json").exists()
