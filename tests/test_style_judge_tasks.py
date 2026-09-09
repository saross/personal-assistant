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


# ---------------------------------------------------------------------------
# Re-audit items 6 and 10 — atomic task files, and a key nobody stumbles into
# ---------------------------------------------------------------------------

def test_the_key_directory_is_not_a_sibling_of_the_judge_directory():
    """A sibling was still one `ls ..` from the blind material.

    The mutation this kills: restoring ``KEY_DIR = EXP / "judge-key"``, which
    puts the answers beside judge-tasks/ and beside the analysis outputs an
    operator opens routinely.
    """
    assert builder.KEY_DIR.parent == builder.PRIVATE_DIR
    assert builder.PRIVATE_DIR.name == "private"
    assert builder.KEY_DIR.parent != builder.JUDGE_DIR.parent


def test_a_judge_root_containing_the_key_is_refused(tmp_path):
    """The original leak: the key under the directory the judge is given."""
    judge = tmp_path / "judge-tasks"

    assert builder.key_is_private(judge, judge / "key") is False
    assert builder.key_is_private(judge, judge) is False


def test_a_key_root_containing_the_judge_directory_is_refused(tmp_path):
    """The same leak the other way up: anyone given the parent reads the key.

    The mutation this kills: checking containment in one direction only.
    """
    private = tmp_path / "private"

    assert builder.key_is_private(private / "judge-tasks", private) is False


def test_separate_trees_are_accepted(tmp_path):
    """The guard must not refuse the layout the script itself produces."""
    assert builder.key_is_private(tmp_path / "judge-tasks",
                                  tmp_path / "private" / "judge-key") is True


def test_the_private_directory_carries_its_own_warning(tmp_path):
    """The reason must outlive whoever set the experiment up."""
    built = _emit(tmp_path)
    readme = built["key_dir"].parent / "README_DO_NOT_SHARE.md"

    assert readme.exists()
    assert "never give this directory to a judge" in readme.read_text(
        encoding="utf-8").lower()


def test_a_task_file_is_written_atomically(tmp_path, monkeypatch):
    """An interrupted copy would leave a judge reading half a passage.

    ``os.replace`` is made to fail part-way, standing in for a crash. The
    mutation this kills: restoring ``shutil.copyfile``, under which the
    truncated destination survives.
    """
    import style_support

    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "private" / "judge-key"
    judge_dir.mkdir()
    key_dir.mkdir(parents=True)
    plan = builder.plan_pairs(5, contrasts=CONTRASTS, topics=TOPICS)

    def boom(*args, **kwargs):
        raise OSError("simulated crash mid-copy")

    monkeypatch.setattr(style_support.os, "replace", boom)

    with pytest.raises(OSError):
        builder.emit_tasks(plan, _passages(tmp_path), judge_dir, key_dir,
                           "# Reference\n", seed=5)

    # Nothing half-written, and no temporary debris for the judge to find.
    assert list(judge_dir.iterdir()) == []


def test_migrate_key_moves_a_legacy_key_and_leaves_the_answers(tmp_path):
    """The live judge-tasks/ still holds the key beside judgments.jsonl.

    The mutation this kills: moving (or deleting) judgments.jsonl along with
    the key, which would destroy the only irreplaceable file in the tree.
    """
    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "private" / "judge-key"
    judge_dir.mkdir()
    (judge_dir / "judge-mapping.json").write_text('{"pairs": []}',
                                                  encoding="utf-8")
    (judge_dir / "judgments.jsonl").write_text('{"pair_id": "pair00"}\n',
                                               encoding="utf-8")

    assert builder.migrate_key(judge_dir, key_dir) == 0

    assert not (judge_dir / "judge-mapping.json").exists()
    assert (key_dir / "judge-mapping.json").exists()
    assert (judge_dir / "judgments.jsonl").exists()
    assert (key_dir.parent / "README_DO_NOT_SHARE.md").exists()


def test_migrate_key_refuses_to_overwrite_an_existing_key(tmp_path):
    """Two keys for one experiment is a question, not something to resolve."""
    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "private" / "judge-key"
    judge_dir.mkdir()
    key_dir.mkdir(parents=True)
    (judge_dir / "judge-mapping.json").write_text("{}", encoding="utf-8")
    (key_dir / "judge-mapping.json").write_text("{}", encoding="utf-8")

    assert builder.migrate_key(judge_dir, key_dir) == 1
    assert (judge_dir / "judge-mapping.json").exists()


def test_migrate_key_dry_run_moves_nothing(tmp_path):
    """The migration is reported before it is run against live data."""
    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "private" / "judge-key"
    judge_dir.mkdir()
    (judge_dir / "judge-mapping.json").write_text("{}", encoding="utf-8")

    assert builder.migrate_key(judge_dir, key_dir, dry_run=True) == 0
    assert (judge_dir / "judge-mapping.json").exists()
    assert not key_dir.exists()


def test_migrate_key_does_nothing_but_migrate(tmp_path):
    """"and does nothing else" was documented but not enforced.

    Deleting the ``return`` after the migrate branch lets the run fall through
    into a full rebuild — which, with the passages present, would rmtree the
    judge directory and rebuild every task under new pair ids, orphaning the
    judgements already collected against the old ones. The mutation this
    kills: removing that ``return``.
    """
    judge_dir = tmp_path / "judge-tasks"
    key_dir = tmp_path / "private" / "judge-key"
    judge_dir.mkdir()
    (judge_dir / "judge-mapping.json").write_text('{"pairs": []}',
                                                  encoding="utf-8")
    (judge_dir / "pair00_A.md").write_text("An invented passage.\n",
                                           encoding="utf-8")
    (judge_dir / "judgments.jsonl").write_text(
        '{"pair_id": "pair00", "choice": "A"}\n', encoding="utf-8")
    before = {p.name: p.read_bytes() for p in judge_dir.iterdir()
              if p.name != "judge-mapping.json"}
    # A passages directory exists, so the fall-through gets past the argument
    # handling and into the build proper. (It then stops at the passage-file
    # check, because the default plan names the real experiment's topics — so
    # the mutation shows up as a non-zero exit here rather than as a rebuilt
    # directory. Both are asserted below; whichever fires, it is caught.)
    _passages(tmp_path)

    code = builder.main([
        "--migrate-key",
        "--judge-dir", str(judge_dir), "--key-dir", str(key_dir),
        "--passages-dir", str(tmp_path / "passages"),
    ])

    assert code == 0
    after = {p.name: p.read_bytes() for p in judge_dir.iterdir()}
    assert after == before, "the judge directory was rebuilt, not left alone"
    assert not (judge_dir / "reference.md").exists()
    assert (key_dir / "judge-mapping.json").exists()
