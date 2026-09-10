#!/usr/bin/env python3
"""
phase1_pipeline.py — corpus-style-analyser v2 Phase 1 measurement extensions.

Per ~/personal-assistant/wiki/planning/style-guide-agent-v2-implementation-plan.md §2:

  * Reference-list stripping pre-pass (regex header + author-year-density fallback).
  * Six new metrics (per-paper AND aggregate): MATTR-100, hapax ratio, passive
    ratio (spaCy), nominalisation rate (spaCy), mean dependency depth (spaCy),
    top-20 POS bigrams (aggregate only).
  * Paragraph statistics (mean / median / stdev word counts).
  * Recomputation of the three "TBD" verification-gate targets:
      - announcement colons per 1k
      - hedge density per 100w
      - concession rate
  * Regression cross-check against the 10 run-1 anchor values from plan §2.5.

Re-implemented from scratch (not vendored from write-like-me). Functions are
intentionally short and self-contained so the validated body can be lifted into
the v2 agent definition as an inline Bash/Python heredoc, per plan decision D2.

Determinism: no LLM calls, no network. spaCy pinned to en_core_web_sm==3.8.0
(verified in the local write-like-me venv).

Usage:
    python phase1_pipeline.py \\
        --corpus-dir /tmp/style-corpus-extract \\
        --manifest /tmp/style-corpus-extract/manifest.json \\
        --output /tmp/style-corpus-extract/analysis/phase1-results.json
"""

# UK/Australian English used throughout (per global CLAUDE.md). Where the
# write-like-me reference inventory uses US spelling for variable / constant
# names (e.g. "nominalization"), we re-spell to "nominalisation" in this
# re-implementation. Output JSON keys also use the UK spelling.

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_support  # noqa: E402  (after the sys.path insertion above)

# ---------------------------------------------------------------------------
# Constants — vocabulary inventories
# ---------------------------------------------------------------------------

# Hedge-token / hedge-phrase / concession-word inventories are lifted verbatim
# from write-like-me/scripts/stylometry.py lines 80-108 so that the Phase 1
# verification-gate targets recomputed here are directly comparable to the
# 8-metric gate documented in write-like-me/references/07-verification.md.
HEDGE_TOKENS = frozenset({
    "might", "maybe", "perhaps", "somewhat", "roughly", "possibly", "could",
    "would", "may", "likely", "unlikely", "apparently", "presumably",
    "generally", "often", "sometimes", "occasionally", "tend", "tends",
    "suggest", "suggests", "appear", "appears", "seem", "seems",
    "indicate", "indicates",
})
HEDGE_PHRASES = (
    "i think", "i believe", "i suspect", "in some sense", "in a sense",
    "to some degree", "to some extent", "in many ways",
)
CONCESSION_WORDS = frozenset({
    "but", "however", "though", "although", "whereas", "while", "yet",
    "nonetheless", "nevertheless", "despite", "notwithstanding",
})

# First-person plural pronouns — matches run-1 §1.1 ledger definition.
FIRST_PLURAL = frozenset({"we", "us", "our", "ourselves", "ours"})

# Core UK / US orthography pairs — the 18 lemma pairs that make up the
# run-1 §5.1 "core" total of 177:55. Listed as (uk_regex, us_regex) per pair.
# (The comment said 14 while the list held 18: finding ST23. The list is the
# authority; `regression_report` sums whatever is in it.)
UK_US_CORE_PAIRS = [
    ("analyse", "analyze"),
    ("analysed", "analyzed"),
    ("organisation", "organization"),
    ("organisations", "organizations"),
    ("characterise", "characterize"),
    ("characterised", "characterized"),
    ("recognise", "recognize"),
    ("recognised", "recognized"),
    ("utilise", "utilize"),
    ("utilised", "utilized"),
    ("emphasise", "emphasize"),
    ("behaviour", "behavior"),
    ("colour", "color"),
    ("labour", "labor"),
    ("centre", "center"),
    ("centres", "centers"),
    ("catalogue", "catalog"),
    ("metre", "meter"),
]

# ---------------------------------------------------------------------------
# Reference-list stripping pre-pass
# ---------------------------------------------------------------------------

# Match a references-section header at line start (case-insensitive).
#
# Finding ST15: this used to require only that a line BEGIN with one of these
# words, anywhere in the document's last 35 %, with no end-of-line anchor and
# no heading marker. A sentence such as "References to earlier work are given
# throughout the report." therefore truncated the document at that sentence,
# and every metric downstream was computed on the fragment.
#
# A real references header is one of two things, and both are matched here:
#   1. a Markdown heading — `## References`, `### Works Cited`;
#   2. a line that is JUST the header word(s), give or take a trailing colon
#      and the second column pdftotext sometimes interleaves after a run of
#      spaces — `REFERENCES`, `References:`, `Bibliography    Author, A.`.
# A header word followed by ordinary running prose is no longer a header.
#
# The comment above has said "case-insensitive" since the file was written,
# but the pattern listed the ALL-CAPS and Title-Case spellings by hand and so
# missed every other one — `references`, `ReFerences`, and the small-caps
# renderings PDF extractors produce. It carries re.IGNORECASE now, and the
# alternation is one list rather than two.
#
# `\r?$` rather than `$`: a CRLF file (a Windows-authored extraction, or one
# round-tripped through a Windows editor) leaves a carriage return before the
# newline, and `$` in MULTILINE mode matches before the \n but AFTER the \r —
# so every header in such a file failed to match at all.
_REF_LABEL = (
    r"(?:REFERENCES\s+CITED|WORKS\s+CITED|LITERATURE\s+CITED|"
    r"REFERENCES|BIBLIOGRAPHY)"
)
_REF_HEADER_RE = re.compile(
    rf"^[ \t]*(?:\#{{1,6}}[ \t]*{_REF_LABEL}[ \t]*:?[ \t]*\r?$"
    rf"|{_REF_LABEL}[ \t]*:?[ \t]*(?:\r?$|[ ]{{3,}}\S))",
    re.MULTILINE | re.IGNORECASE,
)

# Only accept a header positioned in the last `HEADER_TAIL_FRACTION` of the
# document — references are almost always at the end, so an early match is
# nearly always a false positive (a link label, a section called "References
# and resources", a navigation breadcrumb in a web-rendered PDF, etc.).
HEADER_TAIL_FRACTION = 0.35

# Author, A.B. (1999) — canonical reference-list entry shape, used for the
# density fallback when no explicit header survives the tail-position guard.
_AUTHOR_YEAR_RE = re.compile(
    r"[A-Z][A-Za-z'\-]+,\s+[A-Z]\.(?:\s*[A-Z]\.)?(?:[^.\n]*?)\(\d{4}[a-z]?\)"
)


def strip_references(text: str) -> tuple[str, str]:
    """Return ``(stripped_text, method)``.

    Strategy: truncate at the *last* matching ``References``-style header
    that sits in the document's tail (last 35 % by character count). If no
    eligible header is found, fall back to author-year density: identify
    the longest tail-anchored run of author-year entries and truncate at
    its start. Otherwise leave the text untouched. The chosen method is
    reported so Appendix B of the eventual guide can record which strategy
    fired per paper.

    The tail-position guard prevents over-stripping when a paper contains
    an early "References" link / metadata row (e.g. ``5INAFTVT`` from the
    Internet-Archaeology web export).
    """
    n = len(text)
    tail_threshold = int(n * (1.0 - HEADER_TAIL_FRACTION))

    # Strategy 1 — explicit header in the document tail.
    tail_matches = [m for m in _REF_HEADER_RE.finditer(text) if m.start() >= tail_threshold]
    if tail_matches:
        return text[: tail_matches[-1].start()].rstrip(), "header"

    # Strategy 2 — author-year density fallback, tail-anchored.
    ay_matches = list(_AUTHOR_YEAR_RE.finditer(text))
    if len(ay_matches) >= 10:
        # Walk back from the end while the gap between consecutive matches
        # stays under 1 500 characters; that defines the contiguous densest
        # tail run. Pairs are (prev, cur) where cur is later in the document
        # than prev — the gap to test is cur.start() - prev.end().
        run_end = ay_matches[-1].end()
        run_start = ay_matches[-1].start()
        consecutive_pairs = list(zip(ay_matches[:-1], ay_matches[1:]))
        for prev, cur in reversed(consecutive_pairs):
            if cur.start() - prev.end() < 1500:
                run_start = prev.start()
            else:
                break
        # Only strip if the densest run starts in the tail and spans ≥3 000
        # characters — short runs are likely in-body bracketed citations.
        if run_start >= tail_threshold and run_end - run_start > 3000:
            return text[:run_start].rstrip(), "author-year-density"

    return text, "none"


# ---------------------------------------------------------------------------
# Tokenisation / segmentation
# ---------------------------------------------------------------------------

# Run-1 used "regex + counts" with paragraph-aware sentence splitting and
# rejected sentences with <5 or >200 words as extraction noise. Reproduce
# that here so the regression anchors line up.

_ABBR_RE = re.compile(
    r"\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|e\.g|i\.e|fig|figs|tab|cf|al|"
    r"ed|eds|vol|vols|no|nos|pp|ca|ibid|St|Mt|Ave|Inc|Co|Ltd|Univ|Dept|"
    r"approx|chap|sec|eq|esp|misc)\.",
    re.IGNORECASE,
)
# Two-letter initials like "S. Ross", "B. Smith" must not trigger a split.
_INITIAL_RE = re.compile(r"\b([A-Z])\.\s+(?=[A-Z])")
# Unicode-aware word regex — `[^\W\d_]` matches any letter character in any
# script (Latin with diacritics, Greek, Cyrillic) but excludes digits and the
# underscore. Critical for an archaeology corpus that routinely mentions
# Sobotková, Çatalhöyük, Müller, etc.
_WORD_RE = re.compile(r"[^\W\d_][^\W\d_'’\-]*", re.UNICODE)


def tokenize_words(text: str) -> list[str]:
    """Lower-case alphabetic word tokens with internal apostrophe/hyphen kept."""
    return [t.strip("'’-").lower() for t in _WORD_RE.findall(text)]


def split_sentences(text: str) -> list[str]:
    """Heuristic sentence splitter; drops <5- or >200-word fragments.

    The splitter is **paragraph-aware**: paragraphs are split first, then
    each paragraph is split on sentence-final punctuation. This matters for
    PDFs whose final paragraph in a column ends mid-sentence (or with a
    colon under a sub-heading), because a non-paragraph-aware splitter
    glues that paragraph's tail onto the next paragraph's opener and
    inflates mean sentence length.

    We also accept ``[.!?]`` followed by a newline (with or without a
    capitalised opener), to recover boundaries that ``pdftotext -layout``
    inserts when the second column of a two-column PDF reflows.
    """
    sentences: list[str] = []
    # Split on sentence-final punctuation followed by any whitespace. The
    # abbreviation mask above prevents over-splits on the common academic
    # abbreviations; the two-letter-initial mask prevents over-splits on
    # author initials (e.g. "S. Ross"). Without the capital-letter lookahead
    # the splitter recovers boundaries lost when ``pdftotext -layout``
    # reflows columns and the next sentence opens with column-noise.
    boundary_re = re.compile(r"(?<=[.!?])\s+")
    for paragraph in split_paragraphs(text):
        masked = _ABBR_RE.sub(lambda m: m.group(0).replace(".", "\x00"), paragraph)
        masked = _INITIAL_RE.sub(lambda m: m.group(1) + "\x00 ", masked)
        for part in boundary_re.split(masked):
            part = part.replace("\x00", ".").strip()
            n = len(_WORD_RE.findall(part))
            if 5 <= n <= 200:
                sentences.append(part)
    return sentences


# ---------------------------------------------------------------------------
# Prose-paragraph filter (added 2026-05-30)
# ---------------------------------------------------------------------------
# `split_paragraphs` returns every blank-line-separated block. In the
# PyMuPDF/pdfplumber markdown that includes non-prose: markdown headings,
# surviving front-matter (author lines, mastheads, "Pages:"/"Edited by"), and
# line-break/reflow fragments. Counting those as "paragraphs" depresses the
# paragraph-length median below the mean sentence length — impossible for real
# prose — and manufactures a spurious short-paragraph register (investigation
# 2026-05-30: non-prose ~41% of blocks but only ~4.4% of words). To keep the
# §6.5 paragraph metric honest WITHOUT disturbing any other metric, this filter
# is applied ONLY on the paragraph-stats path (process_paper / aggregate), never
# inside `split_paragraphs` itself — so sentence splitting and every word-level
# metric (and the 8-metric gate) are unchanged.
_HEADING_RE = re.compile(r"^\s*#")
_FRONTMATTER_RE = re.compile(
    r"(published by|emerald publishing|oxbow books|©|creative commons|"
    r"\bISBN\b|\bdoi\.org|https?://|www\.|sciencedirect|all rights reserved|"
    r"copyright|licen[cs]e|offprints|\bReceived\b|\bRevised\b|\bAccepted\b)",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(
    r"^\s*(\*?\*?(Pages?|Authors?)\*?\*?:|Edited by\b)", re.IGNORECASE
)
PARA_WORD_FLOOR = 5  # blocks with <= this many word tokens are reflow fragments


def _is_prose_block(block: str) -> bool:
    """True if a blank-line block is an authorial paragraph.

    Rejects markdown headings, labelled/masthead front-matter, and
    sub-sentence reflow fragments. The 5-word floor matches the existing
    5–200-word sentence filter in ``split_sentences`` — the same threshold the
    pipeline already trusts for "too short to be a real sentence". Front-matter
    markers disqualify only a *short* (<= 40-word) block, so a genuine paragraph
    that happens to cite a DOI mid-sentence is retained.
    """
    first = next((ln for ln in block.splitlines() if ln.strip()), "")
    if _HEADING_RE.match(first):
        return False
    if _LABEL_RE.match(block.lstrip()):
        return False
    n_words = len(tokenize_words(block))
    if _FRONTMATTER_RE.search(block) and n_words <= 40:
        return False
    return n_words > PARA_WORD_FLOOR


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; drop paragraphs that contain no word tokens."""
    chunks = re.split(r"\n\s*\n+", text)
    return [c.strip() for c in chunks if _WORD_RE.search(c)]


# ---------------------------------------------------------------------------
# Lifted metrics — re-implemented under run-1 evidence discipline
# ---------------------------------------------------------------------------

def mattr_100(words: list[str], window: int = 100) -> float | None:
    """Moving-window type-token ratio (Covington & McFall 2010).

    Returns ``None`` when the text is shorter than one window. Finding ST20:
    it used to fall back to plain type-token ratio, which is a DIFFERENT and
    strongly length-dependent statistic, and returned it under the same name
    — so a short passage's number was silently incomparable with a corpus
    paper's. Callers record the ``None`` (and the accompanying short-text
    flag) rather than a number that means something else.
    """
    if len(words) < window:
        return None
    ttrs = [
        len(set(words[i : i + window])) / window
        for i in range(len(words) - window + 1)
    ]
    return round(statistics.mean(ttrs), 4)


def hapax_ratio(words: list[str]) -> float:
    """Proportion of word TYPES occurring exactly once in the document.

    Finding ST5: the divisor used to be ``len(words)`` — the token count —
    while this docstring, the plan, and `efficacy_build_reference.py` all
    define the measure over types. On a 6-token/4-type text with 3 hapaxes
    the old code returned 0.5 where the definition gives 0.75, and the
    length artefact that the length-matched reference exists to correct was
    correspondingly larger than assumed. `hapax_per_token` below keeps the
    old quantity under an honest name.
    """
    if not words:
        return 0.0
    counts = collections.Counter(words)
    hapaxes = sum(1 for c in counts.values() if c == 1)
    return round(hapaxes / len(counts), 4)


def hapax_per_token(words: list[str]) -> float:
    """Hapax types per TOKEN — the quantity `hapax_ratio` used to return.

    Kept, under a name that says what it is, so the pre-fix per-paper figures
    remain reproducible and the two can be compared directly.
    """
    if not words:
        return 0.0
    counts = collections.Counter(words)
    hapaxes = sum(1 for c in counts.values() if c == 1)
    return round(hapaxes / len(words), 4)


def paragraph_stats(paragraphs: list[str]) -> dict:
    """Word-count distribution across paragraphs."""
    lengths = [len(tokenize_words(p)) for p in paragraphs]
    lengths = [l for l in lengths if l > 0]
    if not lengths:
        return {"paragraph_count": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0}
    return {
        "paragraph_count": len(lengths),
        "mean": round(statistics.mean(lengths), 2),
        "median": round(statistics.median(lengths), 2),
        "stdev": round(statistics.stdev(lengths) if len(lengths) > 1 else 0.0, 2),
    }


def sentence_stats(sentences: list[str]) -> dict:
    """Mean / median / stdev sentence length (in word tokens)."""
    lengths = [len(_WORD_RE.findall(s)) for s in sentences]
    lengths = [l for l in lengths if l > 0]
    if not lengths:
        return {"count": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0}
    return {
        "count": len(lengths),
        "mean": round(statistics.mean(lengths), 2),
        "median": round(statistics.median(lengths), 2),
        "stdev": round(statistics.stdev(lengths) if len(lengths) > 1 else 0.0, 2),
    }


# ---------------------------------------------------------------------------
# spaCy features — passive ratio, nominalisation, dependency depth, POS bigrams
# ---------------------------------------------------------------------------

# Suffixes used to flag noun-as-nominalisation. Matches Biber (1988) feature
# family; same suffix set as write-like-me, retained for comparability.
_NOMINAL_SUFFIXES = ("tion", "ness", "ment", "ity", "ism", "ance", "ence")


def spacy_features(text: str, nlp) -> dict:
    """Passive ratio, nominalisation rate, mean dependency depth, POS bigrams.

    Per plan §2.2, no 50 000-character sampling cap — each paper is processed
    whole. The largest paper in the corpus (15 413 words) is well under
    spaCy's 1 000 000-character ``max_length`` default.
    """
    doc = nlp(text)
    pos_bigrams: collections.Counter = collections.Counter()
    depths: list[int] = []
    passive_verb_count = 0
    passive_sentences = 0
    nominalisation_count = 0
    sent_count = 0
    token_count = 0

    for sent in doc.sents:
        tokens = [t for t in sent if not t.is_space]
        if not tokens:
            continue
        sent_count += 1
        token_count += len(tokens)
        pos_seq = [t.pos_ for t in tokens]
        for a, b in zip(pos_seq, pos_seq[1:]):
            pos_bigrams[(a, b)] += 1

        # Maximum dependency-tree depth in this sentence (root-hop distance).
        sent_depths = []
        for tok in tokens:
            d, cur = 0, tok
            while cur.head != cur and d < 50:
                cur = cur.head
                d += 1
            sent_depths.append(d)
        depths.append(max(sent_depths) if sent_depths else 0)

        # Passive. Two quantities, because they answer different questions
        # and the old code conflated them (finding ST8): the guide's §5.1
        # target is the FRACTION OF SENTENCES carrying a passive, which is
        # bounded 0..1, while counting every qualifying VERB gives a ratio
        # that can exceed 1 and is not a fraction of anything.
        sentence_has_passive = False
        for tok in tokens:
            if tok.pos_ == "VERB":
                child_deps = {c.dep_ for c in tok.children}
                if "nsubjpass" in child_deps or "auxpass" in child_deps:
                    passive_verb_count += 1
                    sentence_has_passive = True
        if sentence_has_passive:
            passive_sentences += 1

        # Nominalisation: NOUN with characteristic Latin-derived suffix.
        for tok in tokens:
            if tok.pos_ == "NOUN" and tok.lemma_.endswith(_NOMINAL_SUFFIXES):
                nominalisation_count += 1

    # Finding ST9: the nominalisation rate used to divide by spaCy's token
    # count, which includes punctuation, while every other per-1 000-word rate
    # in this file divides by the alphabetic `tokenize_words` count. The
    # denominators differed by 15-20 %, so 38.6/1k was not comparable with
    # 6.54/1k. Both rates now share one denominator.
    n_alpha_words = len(tokenize_words(text))
    return {
        "passive_ratio": round(passive_sentences / max(sent_count, 1), 4),
        "passive_verbs_per_sentence": round(
            passive_verb_count / max(sent_count, 1), 4),
        "nominalisation_per_1000w": round(
            nominalisation_count / max(n_alpha_words, 1) * 1000, 3),
        "nominalisation_count": nominalisation_count,
        "mean_dep_depth": round(statistics.mean(depths) if depths else 0.0, 3),
        "pos_bigrams": pos_bigrams,  # raw Counter — aggregated and top-20 sliced later
    }


# ---------------------------------------------------------------------------
# Verification-gate metrics — the three TBD targets from plan §2.4
# ---------------------------------------------------------------------------

# Announcement colon: a prose colon "X: Y" where X is alphabetic content and
# Y starts with a capital letter. Excludes URLs, times, numeric ratios, and
# Latin abbreviations by virtue of the lookbehind. The middle class is
# `[^\n]` (not `\s`) so the X portion cannot span paragraph breaks — without
# this constraint, the lazy `*?` could swallow entire sub-sections (verified
# on 5INAFTVT/body.md: 5 of 10 sampled hits crossed paragraph breaks).
# Finding ST18: the leading lookbehind guards the START of the match, not the
# colon, so "In 2019: The" was counted — exactly what
# `validate_announce_colon.py` classifies as a URL/TIME/RATIO artefact. The
# second lookbehind puts the guard where the decision is made. The optional
# opening quotation mark (straight or curly) stops a quoted announcement
# scoring zero.
_ANNOUNCE_COLON_RE = re.compile(
    r"(?<![:/\d])[A-Za-z][A-Za-z'\-]*[^\n:]*?(?<![0-9]):\s+[\"\u201c'\u2018]?[A-Z]"
)


def announcement_colons(text: str, words: list[str]) -> float:
    """Announcement-colon rate per 1 000 words."""
    hits = len(_ANNOUNCE_COLON_RE.findall(text))
    return round(hits / max(len(words), 1) * 1000, 3)


# Pre-compile word-boundary patterns for each hedge phrase so the substring
# scan can't match across word boundaries (e.g. ``in some sense`` no longer
# matches inside ``in some sensemaking``).
_HEDGE_PHRASE_RES = [
    re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE)
    for p in HEDGE_PHRASES
]


def hedge_density(words: list[str], lower_text: str) -> float:
    """Hedge tokens + hedge phrases per 100 words.

    Uses the write-like-me ``HEDGE_TOKENS`` and ``HEDGE_PHRASES`` inventories
    so the result is directly comparable to the 8-metric gate's hedge target.
    Phrase matches use word boundaries to avoid swallowing other words.
    """
    n = len(words)
    if n == 0:
        return 0.0
    token_hits = sum(1 for w in words if w in HEDGE_TOKENS)
    phrase_hits = sum(len(p.findall(lower_text)) for p in _HEDGE_PHRASE_RES)
    return round((token_hits + phrase_hits) / n * 100, 3)


# Multi-token concession patterns that the token-set intersection cannot
# detect (e.g. ``in spite of`` contains no word in CONCESSION_WORDS;
# ``even though`` is detected via ``though`` but the modifier carries
# information). Counted per sentence in addition to the token-set hit.
_CONCESSION_PHRASE_RES = [
    re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE)
    for p in ("in spite of", "regardless of", "even so", "all the same")
]


def concession_rate(sentences: list[str]) -> float:
    """Fraction of sentences containing at least one concession word/phrase."""
    if not sentences:
        return 0.0
    hits = 0
    for s in sentences:
        tokens = set(tokenize_words(s))
        if tokens & CONCESSION_WORDS:
            hits += 1
            continue
        if any(p.search(s) for p in _CONCESSION_PHRASE_RES):
            hits += 1
    return round(hits / len(sentences), 4)


# ---------------------------------------------------------------------------
# Regression-anchor counters — plan §2.5
# ---------------------------------------------------------------------------

def whole_word_count(text: str, term: str) -> int:
    """Case-insensitive ``\\b<term>\\b`` count over raw text."""
    return len(re.findall(r"\b" + re.escape(term) + r"\b", text, flags=re.IGNORECASE))


def regression_counters(stripped_text: str, words: list[str]) -> dict:
    """Capture the run-1 anchors that the v2 pipeline must reproduce."""
    # Count only U+2014 EM DASH, not "--", because the corpus is
    # PDF-extracted academic prose where "--" almost never represents an
    # em-dash (run-1 §2.3 likewise only counted true em-dashes).
    em_dashes = stripped_text.count("—")
    semis = stripped_text.count(";")
    fp = sum(1 for w in words if w in FIRST_PLURAL)
    n = max(len(words), 1)

    uk_us = {}
    for uk, us in UK_US_CORE_PAIRS:
        uk_us[uk] = whole_word_count(stripped_text, uk)
        uk_us[us] = whole_word_count(stripped_text, us)

    return {
        "first_plural_count": fp,
        "first_plural_per_1k": round(fp / n * 1000, 3),
        "em_dash_count": em_dashes,
        "em_dash_per_1k": round(em_dashes / n * 1000, 3),
        "semicolon_count": semis,
        "semicolon_per_1k": round(semis / n * 1000, 3),
        "while_count": whole_word_count(stripped_text, "while"),
        "whilst_count": whole_word_count(stripped_text, "whilst"),
        "however_count": whole_word_count(stripped_text, "however"),
        "although_count": whole_word_count(stripped_text, "although"),
        "pace_count_case_sensitive": len(
            re.findall(r"\bpace\b", stripped_text)
        ),
        "uk_us_counts": uk_us,
    }


# ---------------------------------------------------------------------------
# Per-paper driver
# ---------------------------------------------------------------------------

def process_paper(key: str, raw_text: str, nlp, *,
                  strip_refs: bool = True) -> dict:
    """Measure one paper (or one excerpt) and return its record.

    ``strip_refs=False`` for text that is already references-free — the clean
    ``body.md`` archive, and the generated passages the efficacy experiment
    scores. Finding ST15: the pre-pass was run over clean text too, where it
    can only ever remove real prose.

    The input is NFC-normalised first (finding ST19). Without it, a corpus
    that mixes composed and decomposed accents — routine for an archaeology
    corpus full of Sobotková, Çatalhöyük and Müller — counts the same word as
    two types, which moves the type-token ratio, the hapax ratio, and every
    word-boundary count.
    """
    normalised = unicodedata.normalize("NFC", raw_text)
    if strip_refs:
        stripped, ref_method = strip_references(normalised)
    else:
        stripped, ref_method = normalised, "not-attempted"
    lower = stripped.lower()
    words = tokenize_words(stripped)
    sentences = split_sentences(stripped)
    paragraphs = [p for p in split_paragraphs(stripped) if _is_prose_block(p)]

    sp_feats = spacy_features(stripped, nlp)
    pos_bigrams = sp_feats.pop("pos_bigrams")

    record = {
        "key": key,
        "ref_strip_method": ref_method,
        "n_chars_raw": len(raw_text),
        "n_chars_stripped": len(stripped),
        "n_words": len(words),
        "sentence_stats": sentence_stats(sentences),
        "paragraph_stats": paragraph_stats(paragraphs),
        "mattr_100": mattr_100(words),
        # True when the text is shorter than one MATTR window, so a `null`
        # above is "not measurable here", not "zero" (finding ST20).
        "mattr_100_short_text": len(words) < 100,
        "hapax_ratio": hapax_ratio(words),
        "hapax_per_token": hapax_per_token(words),
        "passive_ratio": sp_feats["passive_ratio"],
        "passive_verbs_per_sentence": sp_feats["passive_verbs_per_sentence"],
        "nominalisation_per_1000w": sp_feats["nominalisation_per_1000w"],
        "mean_dep_depth": sp_feats["mean_dep_depth"],
        "announcement_colon_per_1k": announcement_colons(stripped, words),
        "hedge_per_100w": hedge_density(words, lower),
        "concession_rate": concession_rate(sentences),
        "regression": regression_counters(stripped, words),
    }
    # Stash the raw bigram counter under a separate key so the JSON dump can
    # serialise it once we know the per-paper picture; for now keep tuple keys.
    record["_pos_bigrams_counter"] = pos_bigrams
    return record


# ---------------------------------------------------------------------------
# Aggregation across the 18-paper corpus
# ---------------------------------------------------------------------------

def _round_or_none(value: float | None, digits: int) -> float | None:
    """Round ``value``, passing ``None`` (an empty corpus) straight through."""
    return None if value is None else round(value, digits)


def _mean_or_none(values: list[float]) -> float | None:
    """Mean of ``values``, or ``None`` when there is nothing to average.

    ``statistics.mean([])`` raises ``StatisticsError``. Every caller here is
    summarising a corpus that may legitimately have come out empty (finding
    STT5/C5), and an empty corpus is a diagnostic, not a crash.
    """
    return statistics.mean(values) if values else None


def aggregate(per_paper: list[dict], full_text: str) -> dict:
    """Corpus-level summaries from per-paper records + the concatenated text.

    The concatenated ``full_text`` is the reference-stripped prose of every
    included paper joined by double newlines — it is the canonical input
    against which the regression anchors in plan §2.5 are checked.

    Returns ``None`` for any mean over an empty corpus rather than raising.
    """
    words = tokenize_words(full_text)
    sentences = split_sentences(full_text)
    paragraphs = [p for p in split_paragraphs(full_text) if _is_prose_block(p)]

    # Sum POS bigrams across papers.
    bigrams: collections.Counter = collections.Counter()
    for rec in per_paper:
        bigrams.update(rec["_pos_bigrams_counter"])

    # Spec: corpus-level MATTR and hapax are recomputed on the joined stream
    # so the aggregate isn't just a mean-of-means.
    agg = {
        "n_papers": len(per_paper),
        "n_words": len(words),
        "n_sentences": len(sentences),
        "n_paragraphs": len(paragraphs),
        "sentence_stats": sentence_stats(sentences),
        "paragraph_stats": paragraph_stats(paragraphs),
        "mattr_100": mattr_100(words),
        "hapax_ratio": hapax_ratio(words),
        "passive_ratio_mean_of_papers": _round_or_none(
            _mean_or_none([r["passive_ratio"] for r in per_paper]), 4
        ),
        "passive_verbs_per_sentence_mean_of_papers": _round_or_none(
            _mean_or_none([r["passive_verbs_per_sentence"]
                           for r in per_paper]), 4
        ),
        "nominalisation_per_1000w_mean_of_papers": _round_or_none(
            _mean_or_none([r["nominalisation_per_1000w"]
                           for r in per_paper]), 3
        ),
        "mean_dep_depth_mean_of_papers": _round_or_none(
            _mean_or_none([r["mean_dep_depth"] for r in per_paper]), 3
        ),
        "announcement_colon_per_1k": announcement_colons(full_text, words),
        "hedge_per_100w": hedge_density(words, full_text.lower()),
        "concession_rate": concession_rate(sentences),
        "regression": regression_counters(full_text, words),
        "top_20_pos_bigrams": [
            {"pos_bigram": f"{a}+{b}", "count": c}
            for (a, b), c in bigrams.most_common(20)
        ],
    }
    return agg


# ---------------------------------------------------------------------------
# Regression check against the anchors (plan §2.5)
# ---------------------------------------------------------------------------

# (anchor_name, reference_value, tolerance_lo, tolerance_hi, kind)
# kind = "pct" → tolerance is ±% of the anchor; "abs" → ±absolute units
#
# Re-baselined 2026-09-10 (audit decision D9). The original values were
# run 1's (2026-05, raw PDFs with references included: 139,105 words).
# The clean corpus (references separated, 127,718 words) has failed 12 of
# 13 of those since 2026-05-24, so every clean run exited 1 and the exit
# code meant nothing. The values below are the clean corpus measured
# under metric schema 2 on 2026-09-10; the bands are unchanged. The
# output key stays `regression_vs_run_1` for its readers; the `run_1`
# field in each row now holds this reference value.
RUN1_ANCHORS = [
    ("n_words",         127718, 0.02, 0.02, "pct"),
    ("n_sentences",     5832,   0.02, 0.02, "pct"),
    ("mean_sentence",   21.45,  0.5,  0.5,  "abs"),
    ("first_plural_per_1k", 4.988, 0.05, 0.05, "abs"),
    ("em_dash_per_1k",  0.572,  0.05, 0.05, "abs"),
    ("semicolon_per_1k", 6.538, 0.10, 0.10, "abs"),
    ("while_count",     227,    0, 0,    "exact"),
    ("whilst_count",    0,      0, 0,    "exact"),
    ("however_count",   123,    0, 0,    "exact"),
    ("although_count",  70,     0, 0,    "exact"),
    ("pace_count",      8,      0, 0,    "exact"),
    ("uk_core_total",   168,    0, 0,    "exact"),
    ("us_core_total",   44,     0, 0,    "exact"),
]


def regression_report(agg: dict) -> list[dict]:
    reg = agg["regression"]
    uk_us = reg["uk_us_counts"]
    uk_total = sum(uk_us[uk] for uk, _ in UK_US_CORE_PAIRS)
    us_total = sum(uk_us[us] for _, us in UK_US_CORE_PAIRS)
    actual = {
        "n_words": agg["n_words"],
        "n_sentences": agg["n_sentences"],
        "mean_sentence": agg["sentence_stats"]["mean"],
        "first_plural_per_1k": reg["first_plural_per_1k"],
        "em_dash_per_1k": reg["em_dash_per_1k"],
        "semicolon_per_1k": reg["semicolon_per_1k"],
        "while_count": reg["while_count"],
        "whilst_count": reg["whilst_count"],
        "however_count": reg["however_count"],
        "although_count": reg["although_count"],
        "pace_count": reg["pace_count_case_sensitive"],
        "uk_core_total": uk_total,
        "us_core_total": us_total,
    }
    report = []
    for name, ref, lo, hi, kind in RUN1_ANCHORS:
        observed = actual[name]
        if kind == "pct":
            tol = ref * lo
            passed = abs(observed - ref) <= tol
            margin = f"±{tol:.1f} (±{lo*100:.0f}%)"
        elif kind == "abs":
            tol = lo
            passed = abs(observed - ref) <= tol
            margin = f"±{tol}"
        else:  # exact
            passed = observed == ref
            margin = "exact"
        report.append({
            "anchor": name,
            "run_1": ref,
            "observed": observed,
            "tolerance": margin,
            "pass": passed,
        })
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> list[dict]:
    with manifest_path.open() as f:
        return json.load(f)


#: "excluded" as a word of its own, and the negations that cancel it.
_EXCLUDE_WORD_RE = re.compile(r"\bexcluded?\b", re.IGNORECASE)
_NOT_EXCLUDED_RE = re.compile(r"\b(?:not|never|no longer)\s+excluded?\b",
                              re.IGNORECASE)


def included_keys(manifest: list[dict]) -> list[str]:
    """Return the list of paper keys to process.

    A manifest entry is excluded if its ``extraction_notes`` field carries
    "exclude"/"excluded" AS A WHOLE WORD, or if the entry sets an explicit
    ``excluded`` boolean. Finding ST21: the test was a bare substring match,
    so a note reading "not excluded" or "excludes nothing" dropped the paper
    from the corpus. Entries that lack a ``key`` field are silently skipped —
    they cannot be referenced by any other part of the pipeline.
    """
    excluded = set()
    for entry in manifest:
        key = entry.get("key")
        if not key:
            continue
        flag = entry.get("excluded")
        if isinstance(flag, bool):
            if flag:
                excluded.add(key)
            continue
        notes = (entry.get("extraction_notes") or "").lower()
        if _EXCLUDE_WORD_RE.search(notes) and not _NOT_EXCLUDED_RE.search(notes):
            excluded.add(key)
    return [e["key"] for e in manifest if e.get("key") and e["key"] not in excluded]


def main(argv: list[str] | None = None) -> int:
    """Measure the corpus and write the phase 1 results file.

    Returns 0 when every regression anchor is within tolerance, 1 when one is
    not, and 2 when no paper could be read at all.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--corpus-dir", required=True, type=Path,
        help="legacy: directory of <key>.txt files OR clean: directory of "
        "<key>/body.md bundles (auto-detected by checking for body.md)",
    )
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument(
        "--clean-corpus",
        action="store_true",
        help="read body.md from <corpus_dir>/<key>/body.md (the QA-passed "
        "extraction at ~/personal-assistant/data/style-corpus/extracted/); "
        "skips the reference-stripping pre-pass because references are "
        "already separated. Required for the post-2026-05-24 clean archive.",
    )
    ap.add_argument(
        "--spacy-model",
        default="en_core_web_sm",
        help="spaCy model name; pin to en_core_web_sm 3.8.0 per plan D3",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="measure and report, but write no results file",
    )
    args = ap.parse_args(argv)

    import spacy

    nlp = spacy.load(args.spacy_model)
    if nlp.meta["version"] != "3.8.0":
        print(
            f"WARNING: spaCy model {args.spacy_model} version "
            f"{nlp.meta['version']} != pinned 3.8.0",
            file=sys.stderr,
        )
    # Disable NER — unused here and 30 % faster without it.
    # ``select_pipes`` replaces the deprecated ``disable_pipes`` in spaCy 3.x.
    nlp.select_pipes(disable=["ner"])
    # Lift max_length safely; the largest corpus paper is <100 000 chars.
    nlp.max_length = 2_000_000

    manifest = load_manifest(args.manifest)
    keys = included_keys(manifest)
    print(f"Processing {len(keys)} papers (excluded {len(manifest) - len(keys)}).",
          file=sys.stderr)

    per_paper = []
    stripped_streams = []
    for key in keys:
        if args.clean_corpus:
            txt_path = args.corpus_dir / key / "body.md"
        else:
            txt_path = args.corpus_dir / f"{key}.txt"
        if not txt_path.exists():
            print(f"  MISSING: {txt_path}", file=sys.stderr)
            continue
        raw = txt_path.read_text(encoding="utf-8", errors="replace")
        rec = process_paper(key, raw, nlp, strip_refs=not args.clean_corpus)
        per_paper.append(rec)
        # The aggregate stream must be exactly the text the per-paper records
        # were measured on. With --clean-corpus the body.md is already
        # references-free, so the pre-pass is skipped here too: running it
        # over clean text could only remove real prose (finding ST15).
        normalised = unicodedata.normalize("NFC", raw)
        if args.clean_corpus:
            stripped_streams.append(normalised)
        else:
            stripped, _method = strip_references(normalised)
            stripped_streams.append(stripped)
        print(
            f"  {key}: ref_strip={rec['ref_strip_method']} "
            f"n_words={rec['n_words']} "
            f"mean_sl={rec['sentence_stats']['mean']} "
            f"passive={rec['passive_ratio']} "
            f"nom/1k={rec['nominalisation_per_1000w']}",
            file=sys.stderr,
        )

    if not per_paper:
        # Finding STT5/C5: `aggregate([])` used to raise StatisticsError deep
        # inside a mean, which reads like a bug in the pipeline rather than
        # what it is — a corpus directory with nothing readable in it.
        print(
            f"\nNo papers could be read from {args.corpus_dir} "
            f"({len(keys)} key(s) in the manifest). Nothing was measured; "
            "check --corpus-dir and --clean-corpus.",
            file=sys.stderr,
        )
        return 2

    full_text = "\n\n".join(stripped_streams)
    agg = aggregate(per_paper, full_text)
    regression = regression_report(agg)

    # Strip non-serialisable Counter objects before dumping.
    for rec in per_paper:
        rec.pop("_pos_bigrams_counter", None)

    output = {
        # What the metric NAMES in this file mean. A consumer that measures
        # its input with different definitions and compares the two gets a
        # number with no meaning, and nothing downstream can see it happen.
        "metric_schema": style_support.metric_schema_stamp(),
        "per_paper": per_paper,
        "aggregate": agg,
        "regression_vs_run_1": regression,
        "verification_gate_recompute": {
            "announcement_colons_per_1k": agg["announcement_colon_per_1k"],
            "hedge_per_100w": agg["hedge_per_100w"],
            "concession_rate": agg["concession_rate"],
        },
        # Which code, which manifest, and which model produced these numbers.
        "provenance": style_support.provenance_block(
            Path(__file__).name, [args.manifest],
            spacy_model=args.spacy_model,
            extra={"spacy_model_version": nlp.meta.get("version"),
                   "clean_corpus": bool(args.clean_corpus),
                   "metric_schema_version": style_support.METRIC_SCHEMA_VERSION},
        ),
    }

    wrote = style_support.atomic_write_json(args.output, output,
                                            dry_run=args.dry_run)
    print(f"\nWrote {args.output}" if wrote
          else f"\n--dry-run: nothing written to {args.output}",
          file=sys.stderr)

    fails = [r for r in regression if not r["pass"]]
    if fails:
        print(f"\nRegression FAIL: {len(fails)}/{len(regression)} anchors out of tolerance",
              file=sys.stderr)
        for r in fails:
            print(f"  {r['anchor']}: run_1={r['run_1']} observed={r['observed']} "
                  f"tol={r['tolerance']}", file=sys.stderr)
        return 1
    print(f"\nRegression PASS: all {len(regression)} anchors within tolerance",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
