#!/usr/bin/env python3
"""
efficacy_build_judge_tasks.py — build BLINDED pairwise judge tasks for the
efficacy experiment (Workstream G, roadmap item #1).

The stylometric distance is a proxy; this sets up a holistic test of whether a
judge, shown genuine corpus excerpts as the target voice, prefers guide-written
passages over plain ones as "more like this author". Validity controls:

* **Blinding** — passages are copied to anonymised files (`pairNN_A.md` /
  `pairNN_B.md`); the judge never sees condition-revealing filenames, and the
  unblinding key is written to a SIBLING directory the judge is never pointed
  at (finding ST3: it used to be written into the judge's own directory).
* **Randomised position** — which side the guide passage takes is drawn per
  pair from a seeded random number generator, and the pair ids themselves are
  assigned after a seeded shuffle. The old scheme alternated (`order 0, 1`)
  and numbered pairs in topic order, so an even-numbered pair always had the
  guide as A and the id encoded the content: two deterministic leaks.
* **One file per unordered pair** — the old scheme emitted both orders, which
  made `pairNN_A.md` and `pairMM_B.md` byte-identical copies of the same
  passage. That is a third leak (a judge, or any caching layer, can see the
  duplication) and it double-counted the evidence downstream, since the same
  two passages were then tallied as two independent trials. Position bias is
  handled by randomising the side instead, and the seed makes the whole layout
  reproducible.
* **Topic-matched** — each pair is C0 vs guide on the SAME topic, so the choice
  is about voice, not content.
* **Content-cueing caveat** — reference excerpts are archaeology (the corpus's
  domain); for on-domain test topics this shares vocabulary, so the off-domain
  pairs are the cleaner voice test. The judge prompt explicitly says to ignore
  topical overlap.

Reference excerpts are real ~400-word mid-document windows of two corpus papers
(genuine author text).

Re-running is destructive by design (the judge directory is rebuilt), so a
directory that already holds `judgments.jsonl` is refused unless `--force`
(finding STT-M5): those answers cannot be regenerated.

CPU-only apart from the spaCy sentence splitter; no network. Writes atomically
and honours `--dry-run`.

Usage
-----
    python efficacy_build_judge_tasks.py
    python efficacy_build_judge_tasks.py --seed 20260531 --dry-run
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase1_pipeline as p1  # noqa: E402
import style_support  # noqa: E402
from efficacy_build_prompts import strip_citations  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EXP = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"
EXTRACTED = REPO_ROOT / "data/style-corpus/extracted"
PASSAGES = EXP / "passages"
JUDGE_DIR = EXP / "judge-tasks"
#: The unblinding key lives under a directory nobody hands to a judge. A
#: sibling of judge-tasks/ was still one `ls ..` from the blind material and
#: sat beside the analysis outputs an operator opens routinely; `private/`
#: says what it is, and README_DO_NOT_SHARE.md says it again inside.
PRIVATE_DIR = EXP / "private"
KEY_DIR = PRIVATE_DIR / "judge-key"

#: Dropped into the private directory so the reason survives the person who
#: knows it.
PRIVATE_README = """# Private — never give this directory to a judge

This directory holds the unblinding key for the pairwise judge test: which
side of each pair was written under the style guide, and which source file
each blinded task came from.

A judge who sees any of it is no longer blind, and the run is void. Point
judges at the judge-tasks/ directory ONLY. `efficacy_build_judge_tasks.py`
refuses to write a key inside the judge's directory, or a judge directory
inside this one, but it cannot stop a person copying a path.
"""

# Two reference papers chosen for voice variety + recency: a first-author 2022
# methods/argument paper and a last-author 2024 paper. Real author text.
REFERENCE_PAPERS = ["NQGD7QXT", "9B2FJ6SL"]
REFERENCE_WINDOW_INDEX = 2          # mid-document (skips abstract/intro)
REFERENCE_TARGET_WORDS = 400

TOPICS = ["A1", "A2", "B1", "B3"]
# (contrast label, guide condition) — compared against C0 (plain). C3 was
# dropped in the 2026-05-31 citation-corrected re-run (rejected condition;
# its overshoot issues are citation-independent).
CONTRASTS = [("C2vC0", "C2")]
REP = "rep1"                          # one representative passage per cell
#: Default seed. Recorded in the key, so a layout can always be rebuilt.
DEFAULT_SEED = 20260531


def mid_window(text: str, nlp, idx: int, target: int) -> str:
    """Return the idx-th contiguous ~target-word whole-sentence window."""
    doc = nlp(text)
    windows, buf, n = [], [], 0
    for sent in doc.sents:
        s = sent.text.strip()
        if not s:
            continue
        buf.append(s)
        n += len(s.split())
        if n >= target:
            windows.append(" ".join(buf))
            buf, n = [], 0
    if buf:
        windows.append(" ".join(buf))
    if not windows:
        raise ValueError("no sentence window could be built from this text")
    return windows[min(idx, len(windows) - 1)]


def plan_pairs(seed: int, contrasts: list[tuple[str, str]] | None = None,
               topics: list[str] | None = None, rep: str = REP) -> list[dict]:
    """Plan one blinded task per unordered pair, in a seeded random layout.

    Each entry records the unordered pair it came from, which side the guide
    passage takes, and the source filenames — the last of these goes into the
    key only, never into the judge's directory. Pair ids are assigned AFTER
    the shuffle, so an id carries no information about topic or condition.
    """
    contrasts = contrasts if contrasts is not None else CONTRASTS
    topics = topics if topics is not None else TOPICS
    rng = random.Random(seed)
    plan: list[dict] = []
    for contrast, guide_cond in contrasts:
        for topic in topics:
            guide_name = f"{topic}__{guide_cond}__{rep}.md"
            plain_name = f"{topic}__C0__{rep}.md"
            guide_side = rng.choice(("A", "B"))
            a_source, b_source = ((guide_name, plain_name)
                                  if guide_side == "A"
                                  else (plain_name, guide_name))
            plan.append({
                "unordered_pair_id": f"{contrast}|{topic}",
                "topic_id": topic,
                "contrast": contrast,
                "guide_condition": guide_cond,
                "rep": rep,
                "guide_side": guide_side,
                "A_source": a_source,
                "B_source": b_source,
            })
    rng.shuffle(plan)
    for index, entry in enumerate(plan):
        entry["pair_id"] = f"pair{index:02d}"
    return plan


def key_is_private(judge_dir: Path, key_dir: Path) -> bool:
    """True when neither directory contains the other.

    Checked in BOTH directions: a key inside the judge's root is the original
    leak, and a judge root inside the key directory is the same leak wearing a
    different hat, since anyone given the parent can read the key.
    """
    judge = judge_dir.resolve()
    key = key_dir.resolve()
    if judge == key:
        return False
    return judge not in key.parents and key not in judge.parents


def migrate_key(judge_dir: Path, key_dir: Path, *, dry_run: bool = False) -> int:
    """Move a legacy `judge-mapping.json` out of the judge's own directory.

    The first runs of this experiment wrote the key beside the tasks, so a
    live judge-tasks/ still holds it next to judgments.jsonl. This moves that
    file — and only that file — into the key directory, leaving the collected
    judgements untouched. Returns a process exit status.
    """
    legacy = judge_dir / "judge-mapping.json"
    if not legacy.exists():
        print(f"Nothing to migrate: no {legacy}")
        return 0
    destination = key_dir / "judge-mapping.json"
    if destination.exists():
        print(f"REFUSING: {destination} already exists; move or remove it "
              "first so no key is silently overwritten.", file=sys.stderr)
        return 1
    if dry_run:
        print(f"--dry-run: would move {legacy} -> {destination}")
        return 0
    style_support.atomic_write_text(
        destination, legacy.read_text(encoding="utf-8"))
    style_support.atomic_write_text(key_dir.parent / "README_DO_NOT_SHARE.md",
                                    PRIVATE_README)
    legacy.unlink()
    print(f"Moved {legacy} -> {destination}")
    print("The judge directory no longer holds the answer key; its "
          "judgments.jsonl is untouched.")
    return 0


def prepare_judge_dir(judge_dir: Path, *, force: bool,
                      dry_run: bool) -> bool:
    """Clear the judge directory, refusing to destroy collected judgements.

    Rebuilding is destructive by design, but `judgments.jsonl` holds answers
    that cannot be regenerated — a second run used to delete them without a
    word (finding STT-M5). Returns False when the caller should stop.
    """
    answers = judge_dir / "judgments.jsonl"
    if answers.exists() and not force:
        print(f"REFUSING to rebuild {judge_dir}: it holds {answers.name}, "
              "which cannot be regenerated. Move it aside, or pass --force "
              "if you really mean to discard those judgements.",
              file=sys.stderr)
        return False
    if dry_run:
        return True
    if judge_dir.exists():
        shutil.rmtree(judge_dir)
    judge_dir.mkdir(parents=True)
    return True


def build_reference_text(keys: list[str], extracted_dir: Path, nlp,
                         window_index: int, target_words: int) -> str:
    """Assemble the judge's reference samples from real corpus excerpts.

    Citations are stripped from the reference as well as from the candidates:
    citation format is venue-determined and excluded from the voice being
    judged.
    """
    parts = ["# Reference writing samples by the target author\n",
             "These are genuine samples of the author's voice. Use them to "
             "judge which candidate passage reads more like the same "
             "author.\n"]
    for i, key in enumerate(keys, 1):
        body = (extracted_dir / key / "body.md").read_text(
            encoding="utf-8", errors="replace")
        stripped, _method = p1.strip_references(body)
        excerpt = strip_citations(
            mid_window(stripped, nlp, window_index, target_words))
        parts.append(f"## Reference sample {i}\n\n{excerpt}\n")
    return "\n".join(parts)


def emit_tasks(plan: list[dict], passages_dir: Path, judge_dir: Path,
               key_dir: Path, reference_text: str, *, seed: int,
               dry_run: bool = False) -> dict:
    """Copy the blinded passages and write the key; return the key payload.

    Nothing that names a condition, a topic, or a source file reaches
    ``judge_dir``: the key, which carries all three, is written to
    ``key_dir``.
    """
    sources: list[Path] = []
    for entry in plan:
        for side in ("A", "B"):
            source = passages_dir / entry[f"{side}_source"]
            sources.append(source)
            if dry_run:
                continue
            # Not shutil.copyfile: an interrupted copy leaves a truncated
            # task file, and a judge reading half a passage produces a
            # judgement nobody can tell apart from a real one.
            style_support.atomic_write_text(
                judge_dir / f"{entry['pair_id']}_{side}.md",
                source.read_text(encoding="utf-8"),
            )
    style_support.atomic_write_text(judge_dir / "reference.md",
                                    reference_text, dry_run=dry_run)
    key = {
        "seed": seed,
        "rep": plan[0]["rep"] if plan else REP,
        "n_pairs": len(plan),
        "layout_note": (
            "One task per unordered pair; the guide's side is drawn from the "
            "seeded RNG and the pair ids are assigned after a seeded shuffle, "
            "so neither the filename nor the id encodes the condition."
        ),
        "pairs": plan,
        "provenance": style_support.provenance_block(
            Path(__file__).name, sorted(set(sources)), seed=seed,
        ),
    }
    style_support.atomic_write_json(key_dir / "judge-mapping.json", key,
                                    dry_run=dry_run)
    # The warning travels with the directory, not with whoever set it up.
    style_support.atomic_write_text(key_dir.parent / "README_DO_NOT_SHARE.md",
                                    PRIVATE_README, dry_run=dry_run)
    return key


def main(argv: list[str] | None = None) -> int:
    """Build the judge tasks; returns 0 on success, non-zero on refusal."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--judge-dir", type=Path, default=JUDGE_DIR,
                    help="directory handed to the judges")
    ap.add_argument("--key-dir", type=Path, default=KEY_DIR,
                    help="directory for the unblinding key (never the judge's)")
    ap.add_argument("--passages-dir", type=Path, default=PASSAGES)
    ap.add_argument("--extracted-dir", type=Path, default=EXTRACTED)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help="seed for the pair order and side assignment")
    ap.add_argument("--spacy-model", default="en_core_web_sm")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the judge directory holds answers")
    ap.add_argument("--migrate-key", action="store_true",
                    help="move an existing judge-mapping.json out of the "
                         "judge directory into the key directory, and do "
                         "nothing else")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be built; write nothing")
    args = ap.parse_args(argv)

    if not key_is_private(args.judge_dir, args.key_dir):
        print("REFUSING: the key directory and the judge directory must not "
              f"contain one another ({args.key_dir} vs {args.judge_dir}). A "
              "judge given either root could reach the answers.",
              file=sys.stderr)
        return 2

    if args.migrate_key:
        return migrate_key(args.judge_dir, args.key_dir, dry_run=args.dry_run)

    # Everything that can fail is done BEFORE the judge directory is cleared:
    # planning, the passage-file check, and the spaCy-dependent reference
    # build. Wiping first meant a missing passage or a spaCy failure left the
    # previous run's tasks deleted and nothing in their place.
    plan = plan_pairs(args.seed)
    missing = sorted({entry[f"{side}_source"] for entry in plan
                      for side in ("A", "B")
                      if not (args.passages_dir / entry[f"{side}_source"]).exists()})
    if missing:
        print(f"Missing passage file(s) in {args.passages_dir}: {missing}",
              file=sys.stderr)
        return 2

    import spacy
    nlp = spacy.load(args.spacy_model)
    nlp.select_pipes(disable=["ner"])
    nlp.max_length = 2_000_000
    reference_text = build_reference_text(
        REFERENCE_PAPERS, args.extracted_dir, nlp, REFERENCE_WINDOW_INDEX,
        REFERENCE_TARGET_WORDS)

    if not prepare_judge_dir(args.judge_dir, force=args.force,
                             dry_run=args.dry_run):
        return 1
    emit_tasks(plan, args.passages_dir, args.judge_dir, args.key_dir,
               reference_text, seed=args.seed, dry_run=args.dry_run)

    where = "would write" if args.dry_run else "Wrote"
    print(f"{where} {len(plan)} blinded pairs + reference.md to "
          f"{args.judge_dir}/")
    print(f"  key (unblinding) -> {args.key_dir / 'judge-mapping.json'}; "
          f"seed {args.seed}")
    print(f"  contrasts: {[c for c, _ in CONTRASTS]}; topics: {TOPICS}; "
          f"one task per unordered pair with a randomised side")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
