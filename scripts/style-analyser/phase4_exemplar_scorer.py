#!/usr/bin/env python3
"""
Phase 4 — Panickssery exemplar candidate scorer.

Scans the clean corpus (data/style-corpus/extracted/<key>/body.md) for
sentences that instantiate >=3 distinct attested-pattern categories from
the v2.2 style guide. Outputs the top-ranked candidates per paper with a
per-category score breakdown.

Per plan §5.2:
- Score each sentence against 18 sentence-detectable feature categories.
- Threshold: >=3 distinct categories.
- Sentence length 1-3 sentences (this script scores single sentences;
  multi-sentence stitching can be applied downstream).
- Per-paper diversity (output top N per paper; selection happens later).

No LLM calls. Deterministic.
"""
from __future__ import annotations
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

CORPUS = Path("data/style-corpus/extracted")
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


def split_sentences(text: str) -> list[str]:
    # First strip markdown headings + bullets + table rows; keep plain prose
    cleaned_lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            cleaned_lines.append("")
            continue
        if s.startswith("#"):
            continue
        if s.startswith("|") or s.startswith("- ") or s.startswith("* "):
            continue
        if re.match(r"^\d+\.\s", s):
            continue
        cleaned_lines.append(s)
    paragraph_text = " ".join(l for l in cleaned_lines if l)

    candidates = SENT_BREAK.split(paragraph_text)
    sents = []
    buf = ""
    for c in candidates:
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
    p = CORPUS / key / "metadata.json"
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

def main() -> int:
    if not CORPUS.is_dir():
        print(f"Corpus dir not found: {CORPUS}", file=sys.stderr)
        return 2

    results: dict[str, list[tuple[int, str, list[str]]]] = defaultdict(list)
    metas: dict[str, dict] = {}

    for key_dir in sorted(CORPUS.iterdir()):
        if not key_dir.is_dir():
            continue
        body = key_dir / "body.md"
        if not body.exists():
            continue
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
    }
    out_path = Path("data/style-corpus/phase4-exemplar-candidates.json")
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {out_path}")
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
