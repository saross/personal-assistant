"""
Tests for ``scripts/style-analyser/efficacy_build_judge_tasks.py``.

The audit found the "blinded" judge layout leaking the answer three ways
(finding ST3), and destroying evidence on a re-run (finding STT-M5):

* the unblinding key — which side is the guide, and the condition-revealing
  source filenames — was written INTO the directory handed to the judge;
* pair ids were assigned in topic order and the A/B position alternated, so
  an even-numbered pair always had the guide as A;
* each unordered pair was emitted in both orders, which made two of the four
  files byte-identical copies of one passage;
* and every run began with ``shutil.rmtree`` of the judge directory, deleting
  any ``judgments.jsonl`` the judges had already produced.

Every fixture here is invented: no real passage, topic, or paper key appears.
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

builder = load_style_module("efficacy_build_judge_tasks")

#: Two synthetic contrasts and topics, unrelated to the real experiment.
CONTRASTS = [("CXvC0", "CX")]
TOPICS = ["T1", "T2", "T3", "T4"]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; this script is CPU-only."""
    refuse_sockets(monkeypatch)


def _passages(tmp_path: Path) -> Path:
    """Write one distinguishable passage per (topic, condition) cell."""
    passages = tmp_path / "passages"
    passages.mkdir()
    for topic in TOPICS:
        for condition in ("C0", "CX"):
            (passages / f"{topic}__{condition}__rep1.md").write_text(
                f"Synthetic passage for {topic} under {condition}.\n",
                encoding="utf-8")
    return passages


def _emit(tmp_path: Path, *, seed: int = 11, dry_run: bool = False) -> dict:
    """Plan and emit a full task set into throwaway directories."""
    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "judge-key"
    judge_dir.mkdir(exist_ok=True)
    key_dir.mkdir(exist_ok=True)
    plan = builder.plan_pairs(seed, contrasts=CONTRASTS, topics=TOPICS)
    key = builder.emit_tasks(plan, _passages(tmp_path), judge_dir, key_dir,
                             "# Reference\n\nInvented reference prose.\n",
                             seed=seed, dry_run=dry_run)
    return {"plan": plan, "key": key, "judge_dir": judge_dir,
            "key_dir": key_dir}


# ---------------------------------------------------------------------------
# ST3 — the key, the filenames, and the duplicate files
# ---------------------------------------------------------------------------

def test_the_key_is_written_outside_the_judge_directory(tmp_path):
    """The judge must never be pointed at a directory containing the answer.

    The mutation this kills: writing ``judge-mapping.json`` into
    ``judge_dir`` (the original defect).
    """
    built = _emit(tmp_path)

    assert (built["key_dir"] / "judge-mapping.json").exists()
    assert not (built["judge_dir"] / "judge-mapping.json").exists()
    assert built["key_dir"] not in built["judge_dir"].parents
    assert not str(built["key_dir"]).startswith(str(built["judge_dir"]))


def test_no_filename_in_the_judge_directory_names_a_condition(tmp_path):
    """Blinding is a property of the directory listing, so assert on it.

    The mutation this kills: copying the passages under their source names
    (or leaving the source names in a file the judge can read).
    """
    built = _emit(tmp_path)

    names = sorted(p.name for p in built["judge_dir"].iterdir())
    assert names == sorted(
        [f"pair{i:02d}_{side}.md" for i in range(4) for side in ("A", "B")]
        + ["reference.md"])
    listing = " ".join(names)
    for revealing in ("C0", "CX", *TOPICS):
        assert revealing not in listing


def test_each_unordered_pair_is_emitted_once_so_no_two_files_match(tmp_path):
    """Byte-identical task files told a judge which two files were one pair.

    The mutation this kills: restoring the ``for order in (0, 1)`` loop,
    which emits each passage twice under two different pair ids.
    """
    built = _emit(tmp_path)

    contents = [p.read_bytes() for p in built["judge_dir"].glob("pair*.md")]
    assert len(contents) == 8
    assert len(set(contents)) == 8


def test_the_side_of_the_guide_is_not_a_function_of_the_pair_number(tmp_path):
    """Alternating orders made every even-numbered pair guide-as-A.

    The mutation this kills: replacing the seeded draw with
    ``guide_side = "A" if index % 2 == 0 else "B"``.
    """
    sides_by_index: set[tuple[int, str]] = set()
    for seed in range(12):
        plan = builder.plan_pairs(seed, contrasts=CONTRASTS, topics=TOPICS)
        for index, entry in enumerate(plan):
            sides_by_index.add((index, entry["guide_side"]))

    # Every position takes both sides across seeds; an alternating scheme
    # would give exactly one side per position.
    for index in range(4):
        assert {(index, "A"), (index, "B")} <= sides_by_index


def test_the_pair_ids_do_not_follow_the_topic_order(tmp_path):
    """A pair id assigned in topic order encodes the content it hides.

    The mutation this kills: dropping ``rng.shuffle(plan)``, after which the
    topic sequence is the declaration order for every seed.
    """
    orders = {tuple(e["topic_id"] for e in
                    builder.plan_pairs(seed, contrasts=CONTRASTS,
                                       topics=TOPICS))
              for seed in range(12)}

    assert len(orders) > 1
    assert any(order != tuple(TOPICS) for order in orders)


def test_the_same_seed_rebuilds_an_identical_layout(tmp_path):
    """Reproducibility: the seed, recorded in the key, is enough to rebuild.

    The mutation this kills: seeding from the system clock (or not seeding),
    which makes a run unreproducible.
    """
    first = builder.plan_pairs(7, contrasts=CONTRASTS, topics=TOPICS)
    second = builder.plan_pairs(7, contrasts=CONTRASTS, topics=TOPICS)

    assert first == second


# ---------------------------------------------------------------------------
# STT-M5 — a re-run must not delete collected judgements
# ---------------------------------------------------------------------------

def test_a_rebuild_is_refused_when_answers_are_present(tmp_path):
    """``judgments.jsonl`` cannot be regenerated, so it is never destroyed.

    The mutation this kills: restoring the unconditional
    ``shutil.rmtree(JUDGE_DIR)``.
    """
    judge_dir = tmp_path / "judge-tasks"
    judge_dir.mkdir()
    answers = judge_dir / "judgments.jsonl"
    answers.write_text('{"pair_id": "pair00", "choice": "A"}\n',
                       encoding="utf-8")

    proceed = builder.prepare_judge_dir(judge_dir, force=False, dry_run=False)

    assert proceed is False
    assert answers.exists()


def test_force_allows_a_deliberate_rebuild(tmp_path):
    """The refusal is an interlock, not a wall: --force still rebuilds."""
    judge_dir = tmp_path / "judge-tasks"
    judge_dir.mkdir()
    (judge_dir / "judgments.jsonl").write_text("{}\n", encoding="utf-8")

    proceed = builder.prepare_judge_dir(judge_dir, force=True, dry_run=False)

    assert proceed is True
    assert list(judge_dir.iterdir()) == []


def test_a_dry_run_refusal_still_leaves_the_directory_alone(tmp_path):
    """A dry run must never remove anything, with or without answers."""
    judge_dir = tmp_path / "judge-tasks"
    judge_dir.mkdir()
    (judge_dir / "pair00_A.md").write_text("x\n", encoding="utf-8")

    assert builder.prepare_judge_dir(judge_dir, force=False,
                                     dry_run=True) is True
    assert (judge_dir / "pair00_A.md").exists()


def test_main_refuses_a_key_directory_inside_the_judge_directory(tmp_path):
    """The guard is on the paths, so a bad --key-dir cannot re-create ST3.

    The mutation this kills: dropping the containment check in ``main``.
    """
    judge_dir = tmp_path / "judge-tasks"
    judge_dir.mkdir()

    code = builder.main([
        "--judge-dir", str(judge_dir),
        "--key-dir", str(judge_dir / "key"),
        "--passages-dir", str(tmp_path / "passages"),
    ])

    assert code == 2


# ---------------------------------------------------------------------------
# Cross-cutting: dry run, provenance, and the spaCy-free window helper
# ---------------------------------------------------------------------------

def test_dry_run_writes_no_bytes(tmp_path):
    """``--dry-run`` must copy nothing and write no key.

    The mutation this kills: dropping the ``if dry_run: continue`` in the
    copy loop, which would write the tasks anyway.
    """
    built = _emit(tmp_path, dry_run=True)

    assert list(built["judge_dir"].iterdir()) == []
    assert list(built["key_dir"].iterdir()) == []


def test_the_key_records_the_seed_and_the_passage_hashes(tmp_path):
    """A layout is only reproducible if the seed and inputs are recorded.

    The mutation this kills: dropping the ``seed`` field from the key.
    """
    built = _emit(tmp_path, seed=3)
    key = json.loads(
        (built["key_dir"] / "judge-mapping.json").read_text(encoding="utf-8"))

    assert key["seed"] == 3
    assert key["n_pairs"] == 4
    assert key["provenance"]["script"] == "efficacy_build_judge_tasks.py"
    assert len(key["provenance"]["inputs"]) == 8
    assert all(item["sha256"] for item in key["provenance"]["inputs"])


def test_mid_window_returns_the_requested_whole_sentence_window():
    """The reference excerpt is a whole-sentence window, chosen by index.

    Uses an injected fake spaCy pipeline: the real model is not installed
    here, and the corpus it would read is private. The mutation this kills:
    returning ``windows[0]`` regardless of the index asked for.
    """
    def sentence(word: str, n: int) -> FakeSent:
        return FakeSent([FakeToken(word) for _ in range(n)])

    nlp = FakeNlp([sentence("alpha", 4), sentence("beta", 4),
                   sentence("gamma", 4)])

    assert builder.mid_window("ignored", nlp, 0, 4).startswith("alpha")
    assert builder.mid_window("ignored", nlp, 1, 4).startswith("beta")
    # An index past the end clamps to the last window rather than raising.
    assert builder.mid_window("ignored", nlp, 9, 4).startswith("gamma")
