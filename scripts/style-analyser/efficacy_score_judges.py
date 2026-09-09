#!/usr/bin/env python3
"""
efficacy_score_judges.py — tally the blind pairwise judge test
(Workstream G, roadmap item #1).

Reads the unblinding key (`private/judge-key/judge-mapping.json`, written
under a directory no judge is ever pointed at) and the judges' answers
(`judge-tasks/judgments.jsonl`), and reports whether judges preferred
guide-written passages over plain ones as "more like the author".

Design notes, all of them 2026-09 audit fixes:

* **Every judgement is read tolerantly** (finding ST2). A judge may answer
  with bare JSON, with a ```json fence around it, or with prose; a run must
  not abort on a JSONDecodeError half way through the file. Anything that
  cannot be read as a well-formed judgement becomes a typed `unusable`
  record and is counted separately.
* **Only `A` or `B` counts as a choice** (finding ST1). The old code scored
  `picked_guide = choice == guide_side`, so a tie, a refusal, or an empty
  string was silently a *baseline* win, biasing the headline toward "plain"
  by the number of unusable judgements.
* **The two orders of one unordered pair are ONE observation** (finding
  ST13). The counterbalanced design judges the same content twice, so
  tallying "12/16" treated one pair as two independent trials. Pairs are
  collapsed here: a pair counts for the guide only if every usable judgement
  of it chose the guide, for plain only if none did, and is a tie otherwise.
  An exact binomial (sign) test over the collapsed pairs gives the p-value.
* **The prose is derived from the data**, not hard-coded: the topic list, the
  contrast list, the design line, and the letter-bias sentence all come from
  the mapping and the judgements (finding STT-M6).

CPU-only, deterministic, no network. Writes `judge-analysis.md` +
`judge-analysis.json` atomically, each carrying a `provenance` block.

Exit codes: 0 clean; 1 a structural error (empty judgements file, duplicate or
unknown pair id); 2 a missing input file.

Usage
-----
    python efficacy_score_judges.py
    python efficacy_score_judges.py --judge-dir DIR --key-dir DIR --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_support  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EXP = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"
#: Both locations come from `style_support`, which is also where the builder
#: reads them: one description of the layout, so the writer and the reader
#: cannot disagree. They did once — the builder moved the key under `private/`
#: and this default did not follow, so a run at the defaults reported "No
#: judge-mapping.json found" with the key exactly where it belonged.
JUDGE_DIR_DEFAULT = style_support.judge_dir()
KEY_DIR_DEFAULT = style_support.judge_key_dir()

#: Stratum per topic prefix: A-topics are on the corpus's own domain,
#: B-topics are deliberately outside it. Derived from the topic id rather
#: than a hard-coded topic list, so a new topic needs no edit here.
STRATUM_BY_PREFIX = {"A": "on-domain", "B": "off-domain"}

#: The only two answers that are a choice. Anything else — a tie, a refusal,
#: an empty string, "either" — is unusable, never a win for either side.
VALID_CHOICES = ("A", "B")

#: An unordered pair is judged in at most two orders (guide as A, guide as B).
#: A key implying more than that has entries sharing one identity.
MAX_ORDERS_PER_PAIR = 2

#: A fenced code block, so a judge that wrapped its JSON in ```json ... ```
#: is read rather than crashing the run.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
#: Last resort: the first {...} span in a line of prose.
_BRACES_RE = re.compile(r"\{.*\}", re.S)
#: A line that is only a code fence is layout, not an answer: counting it as
#: an unusable judgement inflates the denominator with the judge's formatting.
_FENCE_ONLY_RE = re.compile(r"```(?:json)?")


@dataclass(frozen=True)
class Judgement:
    """One line of `judgments.jsonl`, parsed and classified.

    ``usable`` is False for anything that is not a well-formed judgement with
    a choice in ``VALID_CHOICES``; ``reason`` then says why, so the report can
    account for every line of the file rather than dropping some silently.
    """

    line_no: int
    pair_id: str | None
    choice: str | None
    confidence: str
    usable: bool
    reason: str = ""


def _json_candidates(raw: str) -> list[str]:
    """Return the substrings of ``raw`` worth trying as JSON, in order."""
    candidates = [raw]
    fenced = _FENCE_RE.search(raw)
    if fenced:
        candidates.append(fenced.group(1).strip())
    braced = _BRACES_RE.search(raw)
    if braced:
        candidates.append(braced.group(0))
    return candidates


def parse_judgement(line: str, line_no: int) -> Judgement:
    """Parse one judgement line tolerantly; never raise.

    Tries bare JSON, then a fenced block, then the first braced span in a line
    of prose. A line that survives none of those, or that lacks a pair id or a
    choice in ``VALID_CHOICES``, comes back as an ``unusable`` record.
    """
    raw = line.strip()
    payload = None
    for candidate in _json_candidates(raw):
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        break
    if payload is None:
        return Judgement(line_no, None, None, "unstated", False,
                         "not parseable as JSON")
    if not isinstance(payload, dict):
        return Judgement(line_no, None, None, "unstated", False,
                         f"not a JSON object ({type(payload).__name__})")

    pair_id = payload.get("pair_id")
    pair_id = pair_id.strip() if isinstance(pair_id, str) else None
    confidence = payload.get("confidence")
    confidence = (confidence.strip()
                  if isinstance(confidence, str) and confidence.strip()
                  else "unstated")

    if not pair_id:
        return Judgement(line_no, None, None, confidence, False, "no pair_id")

    choice = payload.get("choice")
    normalised = choice.strip().upper() if isinstance(choice, str) else ""
    if normalised not in VALID_CHOICES:
        return Judgement(line_no, pair_id, None, confidence, False,
                         f"choice {choice!r} is not one of {VALID_CHOICES}")
    return Judgement(line_no, pair_id, normalised, confidence, True)


#: The fields the fallback identity is reconstructed from. All three must be
#: present, or the entry has no identity at all.
_FALLBACK_IDENTITY_FIELDS = ("contrast", "topic_id", "guide_condition")


def unordered_pair_key(entry: dict) -> str | None:
    """Identify the unordered pair an ordered mapping entry belongs to.

    The build script records this explicitly; the fallback keeps an older key
    file scoreable by reconstructing the identity from the fields that define
    the content of a pair (its contrast, topic, and guide condition).

    Returns ``None`` when neither is available. The fallback used to fill each
    missing field with ``"?"``, which gave EVERY entry the same identity
    ``"?|?|?"`` — eight judgements collapsed into "1 unordered pair", the
    tallies came out "0/0 decided" with p = 1.0, and the run exited 0. A key
    that cannot say which pair an entry belongs to cannot be scored at all,
    and the caller refuses rather than reporting that arithmetic.
    """
    explicit = entry.get("unordered_pair_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    values = [entry.get(field) for field in _FALLBACK_IDENTITY_FIELDS]
    if any(value in (None, "") for value in values):
        return None
    return "|".join(str(value) for value in values)


def sign_test(n_guide: int, n_plain: int) -> tuple[float, float]:
    """Exact binomial (sign) test for ``n_guide`` guide-preferring pairs.

    Null: a judge is equally likely to prefer either passage, so each decided
    pair is a fair coin. Returns ``(p_one_sided_guide_better, p_two_sided)``.
    Tied pairs are excluded by the caller, per the usual sign-test convention.
    With no decided pair at all, both p-values are 1.0.
    """
    n = n_guide + n_plain
    if n == 0:
        return 1.0, 1.0
    upper = sum(math.comb(n, i) for i in range(n_guide, n + 1)) / 2 ** n
    lower = sum(math.comb(n, i) for i in range(0, n_guide + 1)) / 2 ** n
    two_sided = min(1.0, 2.0 * min(upper, lower))
    return round(upper, 5), round(two_sided, 5)


def winrate(n_guide: int, n_total: int) -> str:
    """Render a win-rate, with no division by zero on an empty cell."""
    return f"{n_guide}/{n_total}"


def percentage(n_guide: int, n_total: int) -> str:
    """Render a percentage, or `n/a` when there is nothing to divide by."""
    if n_total == 0:
        return "n/a"
    return f"{100.0 * n_guide / n_total:.0f}%"


def letter_lean_sentence(letters: Counter) -> str:
    """Describe the raw letter split, from the data rather than from memory.

    The old report hard-coded "mild B-lean" whatever the judgements said.
    """
    n_a = letters.get("A", 0)
    n_b = letters.get("B", 0)
    if n_a == n_b:
        return (f"Raw letter choices A={n_a} B={n_b} — no letter lean; the "
                "counterbalancing has nothing to correct here.")
    leader, gap = ("A", n_a - n_b) if n_a > n_b else ("B", n_b - n_a)
    total = n_a + n_b
    strength = "slight" if gap / total < 0.2 else "marked"
    return (f"Raw letter choices A={n_a} B={n_b} — a {strength} {leader}-lean "
            "(this is why the design counterbalances order).")


def collapse_to_pairs(usable: list[Judgement],
                      mapping: dict[str, dict]) -> dict[str, dict]:
    """Group usable judgements into one observation per unordered pair.

    A pair counts for a side only if EVERY usable judgement of it chose that
    side; a split pair is a tie and is excluded from the sign test. This is
    finding ST13: the two counterbalanced orders show the same content to two
    judges, so they are one paired observation, not two independent trials.
    """
    groups: dict[str, dict] = {}
    for judgement in usable:
        entry = mapping[judgement.pair_id]
        key = unordered_pair_key(entry)
        group = groups.setdefault(key, {
            "picked_guide": 0, "picked_plain": 0,
            "contrast": entry.get("contrast", "?"),
            "topic_id": entry.get("topic_id", "?"),
            "n_judgements": 0,
        })
        group["n_judgements"] += 1
        if judgement.choice == entry.get("guide_side"):
            group["picked_guide"] += 1
        else:
            group["picked_plain"] += 1
    for group in groups.values():
        if group["picked_plain"] == 0:
            group["verdict"] = "guide"
        elif group["picked_guide"] == 0:
            group["verdict"] = "plain"
        else:
            group["verdict"] = "tie"
    return groups


def tally(groups: dict[str, dict], predicate) -> tuple[int, int, int]:
    """Count (guide, plain, tie) pairs among the groups passing ``predicate``."""
    selected = [g for g in groups.values() if predicate(g)]
    guide = sum(1 for g in selected if g["verdict"] == "guide")
    plain = sum(1 for g in selected if g["verdict"] == "plain")
    ties = sum(1 for g in selected if g["verdict"] == "tie")
    return guide, plain, ties


def resolve_mapping_path(args: argparse.Namespace) -> Path | None:
    """Find the unblinding key, preferring the directory outside the judge's.

    The key used to live INSIDE `judge-tasks/` (finding ST3), so a run against
    an archived experiment falls back to that location with a warning rather
    than failing; new runs write it to `private/judge-key/`, which is where
    `--key-dir` defaults to.
    """
    if args.mapping is not None:
        return args.mapping if args.mapping.exists() else None
    preferred = args.key_dir / "judge-mapping.json"
    if preferred.exists():
        return preferred
    legacy = args.judge_dir / "judge-mapping.json"
    if legacy.exists():
        print(f"WARNING: reading the unblinding key from {legacy} — it sits "
              "inside the directory the judge reads. Re-run "
              "efficacy_build_judge_tasks.py to move it out.", file=sys.stderr)
        return legacy
    return None


def build_report(summary: dict, groups: dict[str, dict], topics: list[str],
                 contrasts: list[str], letters: Counter) -> list[str]:
    """Render the Markdown report from the tallies, with nothing hard-coded."""
    guide = summary["pairs"]["guide"]
    plain = summary["pairs"]["plain"]
    ties = summary["pairs"]["tie"]
    decided = guide + plain
    lines = ["# Blind pairwise judge test — analysis", ""]
    lines.append(
        f"- **{summary['n_judgements']} judgements** over "
        f"{summary['n_pairs_judged']} unordered pairs "
        f"({len(contrasts)} contrast(s) x {len(topics)} topics x "
        f"{summary['orders_per_pair']} order(s) in the key), one "
        "fresh-context judge each; guide vs plain (C0), blind."
    )
    lines.append(
        f"- **Guide preferred in {winrate(guide, decided)} decided pairs** "
        f"({percentage(guide, decided)}); {ties} tied pair(s) where the two "
        f"orders disagreed; {summary['n_unusable']} unusable judgement(s)."
    )
    lines.append(
        "- Exact binomial (sign) test on the decided pairs: "
        f"p(one-sided, guide better) = {summary['sign_test']['p_one_sided']}, "
        f"p(two-sided) = {summary['sign_test']['p_two_sided']}."
    )
    lines.append(f"- {letter_lean_sentence(letters)}")
    if summary["incomplete_pairs"]:
        lines.append("- **Incomplete:** no usable judgement for "
                     f"{summary['incomplete_pairs']}.")
    lines.append("")
    lines.append("## By contrast (unordered pairs)")
    lines.append("")
    lines.append("| Contrast | guide | plain | tie |")
    lines.append("|---|--:|--:|--:|")
    for contrast in contrasts:
        n_g, n_p, n_t = tally(groups, lambda g, c=contrast: g["contrast"] == c)
        lines.append(f"| {contrast} | {n_g} | {n_p} | {n_t} |")
    lines.append("")
    lines.append("## By topic (unordered pairs)")
    lines.append("")
    lines.append("| Topic | Stratum | guide | plain | tie |")
    lines.append("|---|---|--:|--:|--:|")
    for topic in topics:
        n_g, n_p, n_t = tally(groups, lambda g, t=topic: g["topic_id"] == t)
        stratum = STRATUM_BY_PREFIX.get(topic[:1], "?")
        lines.append(f"| {topic} | {stratum} | {n_g} | {n_p} | {n_t} |")
    lines.append("")
    lines.append(f"Guide-picked confidence: {summary['guide_picked_confidence']}; "
                 f"plain-picked: {summary['plain_picked_confidence']}.")
    if summary["unusable_reasons"]:
        lines.append("")
        lines.append("Unusable judgements by reason: "
                     f"{summary['unusable_reasons']}.")
    lines.append("")
    return lines


def load_key(mapping_path: Path) -> tuple[dict[str, dict], list[dict]] | None:
    """Index the key by pair id; return ``None`` if a pair id repeats.

    A repeated pair id means one identifier stands for two different ordered
    pairs, so every judgement naming it is ambiguous — an error, not a warning.
    """
    key = json.loads(mapping_path.read_text(encoding="utf-8"))
    pairs = key["pairs"]
    mapping: dict[str, dict] = {}
    for entry in pairs:
        pair_id = entry["pair_id"]
        if pair_id in mapping:
            print(f"ERROR: the key lists pair_id {pair_id!r} twice; a pair id "
                  "must identify exactly one ordered pair.", file=sys.stderr)
            return None
        mapping[pair_id] = entry
    return mapping, pairs


def check_judgement_ids(judgements: list[Judgement],
                        mapping: dict[str, dict]) -> list[str]:
    """Return the structural errors in the judgement stream (empty if clean).

    Two are fatal and both used to pass silently: a pair judged twice (the old
    code counted it twice, so one judgement could produce "2/2"), and a
    judgement naming a pair the key does not contain (a KeyError, or worse, a
    stale id scored against the wrong content).
    """
    errors: list[str] = []
    seen: dict[str, int] = {}
    for judgement in judgements:
        if judgement.pair_id is None:
            continue
        if judgement.pair_id not in mapping:
            errors.append(f"judgement for unknown pair {judgement.pair_id} "
                          f"(line {judgement.line_no})")
            continue
        if judgement.pair_id in seen:
            errors.append(
                f"duplicate judgement for pair {judgement.pair_id} "
                f"(lines {seen[judgement.pair_id]} and {judgement.line_no})")
        seen[judgement.pair_id] = judgement.line_no
    return errors


def main(argv: list[str] | None = None) -> int:
    """Score the judge run; see the module docstring for the exit codes."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    # Resolved at call time from the shared base (see the constants above).
    ap.add_argument("--judge-dir", type=Path,
                    default=style_support.judge_dir(),
                    help="directory the judges read (holds judgments.jsonl)")
    ap.add_argument("--key-dir", type=Path,
                    default=style_support.judge_key_dir(),
                    help="directory holding the unblinding key")
    ap.add_argument("--mapping", type=Path, default=None,
                    help="explicit path to judge-mapping.json")
    ap.add_argument("--judgments", type=Path, default=None,
                    help="explicit path to judgments.jsonl")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where judge-analysis.{md,json} are written "
                         "(default: the judge directory's parent)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and print, but write no files")
    args = ap.parse_args(argv)

    mapping_path = resolve_mapping_path(args)
    if mapping_path is None:
        print("No judge-mapping.json found (looked in "
              f"{args.key_dir} and {args.judge_dir}).", file=sys.stderr)
        return 2
    judgments_path = args.judgments or (args.judge_dir / "judgments.jsonl")
    if not judgments_path.exists():
        print(f"No judgments.jsonl: {judgments_path}", file=sys.stderr)
        return 2

    loaded = load_key(mapping_path)
    if loaded is None:
        return 1
    mapping, pairs = loaded

    lines = judgments_path.read_text(encoding="utf-8").splitlines()
    judgements = [parse_judgement(line, i)
                  for i, line in enumerate(lines, 1)
                  if line.strip() and not _FENCE_ONLY_RE.fullmatch(line.strip())]
    if not judgements:
        print(f"ERROR: {judgments_path} contains no judgements. Nothing was "
              "scored; this is a diagnostic, not a result.", file=sys.stderr)
        return 1

    errors = check_judgement_ids(judgements, mapping)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    # A key entry with neither an explicit unordered_pair_id nor all three
    # fallback fields has no identity. The fallback used to substitute "?" for
    # each missing field, so every entry collapsed into one group and the run
    # reported "1 unordered pair", "0/0 decided", p = 1.0 and exit 0.
    anonymous = [entry.get("pair_id", "<no pair_id>") for entry in pairs
                 if unordered_pair_key(entry) is None]
    if anonymous:
        print(f"ERROR: {len(anonymous)} key entr(y/ies) do not say which "
              f"unordered pair they belong to: {sorted(anonymous)[:8]}. "
              "Each needs an `unordered_pair_id`, or all of "
              f"{list(_FALLBACK_IDENTITY_FIELDS)}. Re-run "
              "efficacy_build_judge_tasks.py to regenerate the key.",
              file=sys.stderr)
        return 1

    usable = [j for j in judgements if j.usable]
    unusable = [j for j in judgements if not j.usable]
    groups = collapse_to_pairs(usable, mapping)

    all_keys = {unordered_pair_key(entry) for entry in pairs}
    incomplete = sorted(all_keys - set(groups))

    guide, plain, ties = tally(groups, lambda _group: True)
    p_one, p_two = sign_test(guide, plain)
    letters = Counter(j.choice for j in usable)
    topics = sorted({str(entry.get("topic_id", "?")) for entry in pairs})
    contrasts = sorted({str(entry.get("contrast", "?")) for entry in pairs})
    orders_per_pair = round(len(pairs) / max(len(all_keys), 1), 2)
    if orders_per_pair > MAX_ORDERS_PER_PAIR:
        # An unordered pair has at most two orders (guide as A, guide as B).
        # A higher ratio means several distinct pairs share one identity, so
        # every tally below would be over the wrong groups.
        print(f"ERROR: the key has {len(pairs)} entries for "
              f"{len(all_keys)} unordered pair(s) — {orders_per_pair} orders "
              f"per pair, and a pair has at most {MAX_ORDERS_PER_PAIR}. The "
              "identities in this key do not distinguish its pairs.",
              file=sys.stderr)
        return 1

    guide_conf = Counter(j.confidence for j in usable
                         if j.choice == mapping[j.pair_id].get("guide_side"))
    plain_conf = Counter(j.confidence for j in usable
                         if j.choice != mapping[j.pair_id].get("guide_side"))

    summary = {
        "n_judgements": len(judgements),
        "n_usable": len(usable),
        "n_unusable": len(unusable),
        "unusable_reasons": dict(Counter(j.reason for j in unusable)),
        "n_pairs_in_key": len(all_keys),
        "n_pairs_judged": len(groups),
        "orders_per_pair": orders_per_pair,
        "incomplete_pairs": incomplete,
        "pairs": {"guide": guide, "plain": plain, "tie": ties},
        "sign_test": {"p_one_sided": p_one, "p_two_sided": p_two,
                      "n_decided_pairs": guide + plain},
        "raw_letter_choices": dict(sorted(letters.items())),
        "topics": topics,
        "contrasts": contrasts,
        "per_pair": {k: groups[k] for k in sorted(groups)},
        "guide_picked_confidence": dict(sorted(guide_conf.items())),
        "plain_picked_confidence": dict(sorted(plain_conf.items())),
        "provenance": style_support.provenance_block(
            Path(__file__).name, [mapping_path, judgments_path],
        ),
    }

    report_lines = build_report(summary, groups, topics, contrasts, letters)
    out_dir = args.out_dir or args.judge_dir.parent
    wrote = style_support.atomic_write_json(
        out_dir / "judge-analysis.json", summary, dry_run=args.dry_run)
    style_support.atomic_write_text(
        out_dir / "judge-analysis.md", "\n".join(report_lines) + "\n",
        dry_run=args.dry_run)
    print("\n".join(report_lines))
    if not wrote:
        print(f"--dry-run: nothing written to {out_dir}", file=sys.stderr)
    if incomplete:
        print(f"WARNING: {len(incomplete)} pair(s) have no usable judgement: "
              f"{incomplete}", file=sys.stderr)
    if unusable:
        print(f"WARNING: {len(unusable)} judgement(s) were unusable and are "
              "excluded from every tally.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
