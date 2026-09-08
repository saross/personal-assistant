#!/usr/bin/env python3
"""
Phase 4 — Panickssery exemplar candidate scorer.

Scans the clean corpus (data/style-corpus/extracted/<key>/body.md) for
sentences that instantiate >=3 distinct attested-pattern categories from
the v2.2 style guide. Outputs the top-ranked candidates per paper with a
per-category score breakdown.

Per plan §5.2:
- Score each sentence against every sentence-detectable feature category
  implemented here: the regular-expression categories in ``PATTERNS`` plus
  the nominalisation detector, 17 in total. Plan §5.2 asks for 18 and this
  file has only ever implemented 17; the prose used to claim 18 while the
  emitted ``n_categories`` said 17 (audit finding ST23). That emitted number
  is computed from ``PATTERNS`` and so cannot drift from what is actually
  scored — the prose was the wrong half, and it is corrected here.
- Threshold: >=3 distinct categories.
- Sentence length 1-3 sentences (this script scores single sentences;
  multi-sentence stitching can be applied downstream).
- Per-paper diversity (output top N per paper; selection happens later).

No LLM calls. Deterministic. The output is written through
``style_support.atomic_write_json`` (an interrupted run used to truncate the
JSON, which the next stage then parsed as if it were complete), carries a
``provenance`` block naming the code and input hashes it came from, and is
suppressed entirely by ``--dry-run``.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# The tranche's scripts import each other as flat siblings. Running this file
# directly already puts its own directory on ``sys.path``; ``python -m`` and an
# import from elsewhere do not, so put it there explicitly.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import style_support  # noqa: E402

# See phase3_promotion.py: __file__-derived so the documented absolute-path
# invocation works from any working directory. Overridable on the CLI.
PA_ROOT = Path(__file__).resolve().parents[2]
CORPUS = PA_ROOT / "data" / "style-corpus" / "extracted"
OUT = PA_ROOT / "data" / "style-corpus" / "phase4-exemplar-candidates.json"
MIN_CATS = 3
TOP_PER_PAPER = 3
MIN_WORDS = 20
MAX_WORDS = 80  # single sentence; multi-sentence joins handled later

# -- Feature detectors (sentence-level) ---------------------------------------

# Each entry: (category_name, compiled_regex_or_callable)
# A category counts as "present" if the regex finds >=1 match in the sentence.

PATTERNS = {
    "first_plural": re.compile(r"\b(we|our|us|ourselves)\b", re.I),
    "citation_paren": re.compile(
        r"\([A-Z][A-Za-zÀ-ſ\-]+"
        r"(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-zÀ-ſ\-]+))?"
        r"[,\s]+\d{4}"
    ),
    "multi_cite": re.compile(r"\([^)]*?\d{4}[^)]*?;[^)]*?\d{4}"),
    "latin_abbr": re.compile(r"\b(cf|i\.e|e\.g)\.", re.I),
    "necessity_modal": re.compile(
        r"\b(should|must|need\s+to|ought\s+to|have\s+to)\b", re.I
    ),
    "hedge": re.compile(
        r"\b(may|might|appears?|seems?|seemed|suggests?|perhaps|possibly"
        r"|likely|probable|probably|presumably)\b",
        re.I,
    ),
    "persuasive_opener": re.compile(
        r"^(?:This|The)\s+(?:article|paper|chapter|study|volume|book)\s+"
        r"(?:presents?|argues?|proposes?|describes?|examines?|investigates?"
        r"|explores?|discusses?|considers?|reviews?)\b",
        re.I,
    ),
    # Passive heuristic: be-form followed within 0-2 words by past participle.
    # Past participle approximated as word ending in 'ed' or strong-irregular set.
    "passive": re.compile(
        r"\b(is|are|was|were|be|been|being)\s+(?:\w+\s+){0,2}"
        r"(?:\w+ed|made|done|given|seen|taken|shown|known|found|held|set|"
        r"led|sent|brought|built|written|drawn|carried|conducted|developed|"
        r"described|presented|reported|used|placed)\b",
        re.I,
    ),
    # Nominalisations: >=2 tokens ending in nominalising suffixes.
    "semicolon": re.compile(r";"),
    "em_dash": re.compile(r"—"),
    # Announcement colon: lowercase-letter colon space uppercase-letter mid-sentence.
    "announce_colon": re.compile(r"[a-z]\s*:\s+[A-Z]"),
    "concession_subord": re.compile(
        r"\b(while|although|however|despite|nevertheless|whereas|though"
        r"|yet|even\s+if|even\s+though)\b",
        re.I,
    ),
    "sequential_signpost": re.compile(
        r"\b(First|Second|Third|Fourth|Fifth|Finally)\b[,;]?\s",
    ),
    "coordinator_connect": re.compile(
        r"\b(as\s+well\s+as|in\s+addition|furthermore|moreover|in\s+particular"
        r"|notably)\b",
        re.I,
    ),
    "uk_orth": re.compile(
        r"\b(behaviour|colour|honour|favour|labour|neighbour|harbour"
        r"|analyse[ds]?|recognise[ds]?|organise[ds]?|emphasise[ds]?"
        r"|theorise[ds]?|prioritise[ds]?|categorise[ds]?|characterise[ds]?"
        r"|metre[s]?|centre[s]?|fibre[s]?|defence|licence"
        r"|catalogue[ds]?|dialogue[ds]?|programme[s]?|whilst|ageing"
        r"|modelling|travelling|labelling|signalling|cancelling)\b",
        re.I,
    ),
    "discipline_vocab": re.compile(
        r"\b(open[\s-]?source|FAIR|born[\s-]digital|fieldwork|repository|"
        r"workflow|reproducibility|reproducible|provenance|metadata|"
        r"crowd-?sourc|citizen\s+science|open\s+data|open\s+access)\b",
        re.I,
    ),
}


def count_nominalisations(sent: str) -> bool:
    """>=2 nominalising-suffix tokens in the sentence."""
    tokens = re.findall(r"\b\w{6,}\b", sent)
    n = sum(1 for t in tokens if re.search(r"(tion|ment|ness|ity|ism|ance|ence)s?$", t, re.I))
    return n >= 2


def score_sentence(sent: str, is_pre_2023: bool) -> tuple[int, list[str]]:
    """Return (category_count, list_of_matched_category_names)."""
    matched: list[str] = []
    for name, rx in PATTERNS.items():
        if name == "em_dash" and not is_pre_2023:
            continue  # year-binning rule: em-dash is anti-pattern in 2023+
        if rx.search(sent):
            matched.append(name)
    if count_nominalisations(sent):
        matched.append("nominalisation")
    return len(matched), matched


# -- Sentence segmentation ----------------------------------------------------

# Conservative sentence-end detector: punctuation followed by whitespace + capital,
# but not after common abbreviations.
ABBR = {"e.g", "i.e", "cf", "et al", "Dr", "Mr", "Mrs", "Ms", "Prof",
        "Fig", "fig", "Tab", "vs", "St", "etc", "no", "No", "vol", "Vol",
        "pp", "p", "c", "ca", "Ca"}

SENT_BREAK = re.compile(r"(?<=[.!?])\s+(?=[\"A-ZÀ-ſ])")


def split_paragraphs(text: str) -> list[str]:
    """Group the prose lines of ``text`` into paragraphs, one string each.

    Markdown headings, bullets, numbered list items, and table rows are
    dropped: they are not prose, and their punctuation confuses the sentence
    boundary regex. A blank line ends the current paragraph, and so does a
    dropped structural line — a heading between two paragraphs is a stronger
    boundary than a blank line, not a weaker one.
    """
    paragraphs: list[list[str]] = [[]]

    def close() -> None:
        """Start a new paragraph, unless the current one is still empty."""
        if paragraphs[-1]:
            paragraphs.append([])

    for line in text.splitlines():
        s = line.strip()
        if not s:
            close()
            continue
        if s.startswith("#"):
            close()
            continue
        if s.startswith("|") or s.startswith("- ") or s.startswith("* "):
            close()
            continue
        if re.match(r"^\d+\.\s", s):
            close()
            continue
        paragraphs[-1].append(s)

    # Lines within one paragraph are soft-wrapped, so joining them with a
    # single space reconstitutes the paragraph's prose.
    return [" ".join(lines) for lines in paragraphs if lines]


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into candidate sentences, never crossing a blank line.

    Each paragraph is segmented independently (audit finding ST22). The
    previous version joined *every* surviving line of the document into one
    string before splitting, so a paragraph whose last line ended without
    terminal punctuation — a heading run-on, a truncated column, a line ending
    in a colon — was glued to the opening of the next paragraph, and the
    stitched result could be emitted as a single "exemplar sentence" spanning
    a paragraph break.
    """
    sents: list[str] = []
    for paragraph in split_paragraphs(text):
        sents.extend(_split_paragraph_sentences(paragraph))
    return sents


def _split_paragraph_sentences(paragraph: str) -> list[str]:
    """Split one paragraph on sentence-final punctuation.

    The buffer re-joins a candidate that was split at a known abbreviation's
    full stop ("cf.", "e.g.", "Fig. 3"). Any text still in the buffer when the
    paragraph ends is emitted as it stands: the buffer never survives into the
    next paragraph, which is what stops a sentence spanning a blank line.
    """
    sents: list[str] = []
    buf = ""
    for c in SENT_BREAK.split(paragraph):
        c = c.strip()
        if not c:
            continue
        if buf:
            buf = buf + " " + c
        else:
            buf = c
        # Reject merge if buf ends in known abbreviation that took the .
        tail = re.search(r"(\w+)\.\s*$", buf)
        if tail and tail.group(1) in ABBR:
            continue
        sents.append(buf)
        buf = ""
    if buf:
        sents.append(buf)
    return sents


# -- Per-paper metadata -------------------------------------------------------

def load_meta(key: str) -> dict:
    p = corpus_dir() / key / "metadata.json"
    if not p.exists():
        return {}
    return json.load(open(p))


def is_pre_2023(meta: dict) -> bool:
    date = meta.get("zotero", {}).get("date", "")
    m = re.match(r"^(\d{4})", date)
    if not m:
        return True  # default conservative
    return int(m.group(1)) <= 2022


def author_role(meta: dict) -> str:
    return meta.get("zotero", {}).get("role", "?")


# -- Driver -------------------------------------------------------------------

#: Set by ``main`` so ``load_meta`` (called deep in the scoring loop) can see
#: the corpus directory without threading it through every helper.
_CORPUS_DIR: Path = CORPUS


def corpus_dir() -> Path:
    """Return the corpus directory the current run is reading."""
    return _CORPUS_DIR


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line.

    ``--corpus`` and ``--out`` move the two production paths off the working
    directory. ``--dry-run`` scores and summarises exactly as a real run does
    and writes nothing at all, so an operator can see what the script *would*
    put in the output path without touching the file already there.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--corpus", type=Path, default=CORPUS,
                        help=f"extracted-corpus directory (default: {CORPUS})")
    parser.add_argument("--out", type=Path, default=OUT,
                        help=f"where to write the candidates (default: {OUT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="score and summarise, but write no output file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Score every corpus sentence and write the exemplar candidates.

    Returns ``2`` when the corpus directory is missing, ``0`` otherwise.
    """
    global _CORPUS_DIR
    args = parse_args(argv)
    _CORPUS_DIR = args.corpus

    if not args.corpus.is_dir():
        print(f"Corpus dir not found: {args.corpus}", file=sys.stderr)
        return 2

    results: dict[str, list[tuple[int, str, list[str]]]] = defaultdict(list)
    metas: dict[str, dict] = {}
    #: Every body.md actually read, in read order — hashed into the provenance
    #: block so a result can be tied to the exact input bytes behind it.
    inputs: list[Path] = []

    for key_dir in sorted(args.corpus.iterdir()):
        if not key_dir.is_dir():
            continue
        body = key_dir / "body.md"
        if not body.exists():
            continue
        inputs.append(body)
        key = key_dir.name
        meta = load_meta(key)
        metas[key] = meta
        pre_2023 = is_pre_2023(meta)
        text = body.read_text(encoding="utf-8")
        for sent in split_sentences(text):
            wc = len(sent.split())
            if wc < MIN_WORDS or wc > MAX_WORDS:
                continue
            score, cats = score_sentence(sent, pre_2023)
            if score >= MIN_CATS:
                results[key].append((score, sent, cats))
        # sort + truncate per paper
        results[key].sort(key=lambda r: (-r[0], len(r[1])))
        results[key] = results[key][:TOP_PER_PAPER]

    # Emit JSON for downstream selection
    out = {
        "min_cats": MIN_CATS,
        "min_words": MIN_WORDS,
        "max_words": MAX_WORDS,
        "top_per_paper": TOP_PER_PAPER,
        "n_categories": len(PATTERNS) + 1,  # +1 for nominalisation
        "per_paper": [
            {
                "key": key,
                "year": metas[key].get("zotero", {}).get("date", "")[:4],
                "role": author_role(metas[key]),
                "candidates": [
                    {"score": s, "sentence": sent, "categories": cats}
                    for (s, sent, cats) in results[key]
                ],
            }
            for key in sorted(results.keys())
        ],
        # What produced this file: the script, the commit, and the SHA-256 of
        # every body.md read. No wall-clock field, so two runs over unchanged
        # inputs are byte-identical (see style_support's module docstring).
        "provenance": style_support.provenance_block(
            Path(__file__).name, inputs,
            extra={"corpus_dir": str(args.corpus)},
        ),
    }
    # The atomic writer creates the parent directory itself, and only on a
    # real write, so a dry run leaves no directory behind either.
    out_path = args.out
    wrote = style_support.atomic_write_json(out_path, out, dry_run=args.dry_run)
    if wrote:
        print(f"Wrote {out_path}")
    else:
        print(f"Dry run: nothing written (would have written {out_path})")
    # Brief stdout summary
    print(f"\n{'key':10} {'year':5} {'role':10} {'n_cand':>6}  top_score")
    print("-" * 60)
    for paper in out["per_paper"]:
        if paper["candidates"]:
            top = paper["candidates"][0]["score"]
        else:
            top = 0
        print(f"{paper['key']:10} {paper['year']:5} {paper['role']:10}"
              f" {len(paper['candidates']):>6}  {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
