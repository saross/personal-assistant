#!/usr/bin/env python3
"""
extract_corpus.py — Build the clean text archive of Shawn's 18-paper style corpus.

Reuses the mature PDF extraction pipeline from
``~/Code/llm-reproducibility/extraction-system/scripts/pdf_processing/`` (PyMuPDF
for reading-order text blocks with bbox positioning, pdfplumber for tables,
plus header/footer removal, section detection, and reference-section
formatting). This wrapper adds:

  * A driver that walks the 18-paper corpus manifest
    (``/tmp/style-corpus-extract/manifest.json``) and produces a per-paper
    output bundle under
    ``~/personal-assistant/data/style-corpus/extracted/<key>/``.
  * Heading-aware body/references split — the Markdown the upstream extractor
    produces has explicit ``## References`` (or similar) section headings, so
    the split is a clean structural operation, not a regex pre-pass over raw
    text. This dissolves the CI2Q7VXD over-strip bug class identified in
    diagnostic 1 of the v2 Phase 1 review.
  * A QA flag set per paper (qa.json): reading-order confidence, header/footer
    suppression count, references-section detected, abstract detected,
    word-count delta vs the upstream manifest.

Per the global CLAUDE.md, all output uses UK/Australian English.

Usage:
    ~/Code/write-like-me/.venv/bin/python \\
        ~/personal-assistant/scripts/style-analyser/extract_corpus.py \\
        --manifest /tmp/style-corpus-extract/manifest.json \\
        --output-dir ~/personal-assistant/data/style-corpus/extracted/ \\
        [--keys KEY1,KEY2,...]      # subset; default: all 18 included papers
        [--include-excluded]        # also re-extract the manifest's EXCLUDED items
                                    # (SXC9W525, I3IDESQN) — useful to verify
                                    # whether a better extractor recovers them
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Bring the canonical extractor into scope. Per the user's "import in place"
# decision (2026-05-24), the cleaner module is not vendored — fixes flow back
# to llm-reproducibility upstream.
_LLM_REPRO_PDF = Path.home() / "Code" / "llm-reproducibility" / "extraction-system" / "scripts" / "pdf_processing"
if not _LLM_REPRO_PDF.is_dir():
    sys.exit(f"FATAL: expected canonical extractor at {_LLM_REPRO_PDF} (not found)")
sys.path.insert(0, str(_LLM_REPRO_PDF))

from extract_pdf_text import PDFExtractor  # noqa: E402
from pdf_cleaner import clean_reference_section  # noqa: E402


# ---------------------------------------------------------------------------
# Body / references split
# ---------------------------------------------------------------------------

# Match an opening markdown heading whose text is a references-section label.
# The extractor's section detector ALL-CAPS headings get formatted as `## TEXT`
# while Title-Case headings get `## Text` — both supported here. We deliberately
# accept `Acknowledgements` / `Acknowledgments` too because in some journals the
# acknowledgements block sits between the body and the references and contains
# author-affiliation prose that should not enter the body metrics.
_REF_HEADING_RE = re.compile(
    r"^\s{0,3}(#{1,4})\s+("
    r"REFERENCES?|References?|"
    r"BIBLIOGRAPHY|Bibliography|"
    r"WORKS\s+CITED|Works\s+Cited|"
    r"LITERATURE\s+CITED|Literature\s+Cited|"
    r"REFERENCES\s+CITED|References\s+Cited"
    r")\s*$",
    re.MULTILINE,
)

# Slightly looser secondary fallback: a heading whose text begins with the word
# "References" or "Bibliography" (e.g. "References and resources" — rare but
# observed). Only tried if the strict pattern misses.
_REF_HEADING_LOOSE_RE = re.compile(
    r"^\s{0,3}(#{1,4})\s+(References?|Bibliography|Works\s+Cited).*$",
    re.MULTILINE | re.IGNORECASE,
)

# Tertiary fallback: a paragraph whose first word is "References" (or similar)
# followed by what looks like the start of the first reference entry (a
# capitalised author surname plus comma or initial). This catches the case
# where the upstream extractor's section detector failed to promote the
# References heading to its own line — instead concatenating it with the first
# reference, e.g. "References Akata, Z., Reed, S., …" or
# "References About. (2023)." The boundary check on the second token
# (capital letter, then comma / initial / period / paren) keeps this from
# matching prose like "References to earlier studies were extensive."
_REF_PARAGRAPH_RE = re.compile(
    r"(?:^|\n)\s*(References?|Bibliography|Works\s+Cited)\s+"
    # Lookahead for the start of the first reference entry. The
    # ``[A-Z][A-Z][a-z]`` branch (was ``[A-Z][A-Z]``) requires an all-caps
    # surname prefix followed by a lower-case letter, so "References IN this
    # section" no longer false-matches.
    r"(?=[A-Z][a-z]*[,.\s]|[A-Z]\.|[A-Z][A-Z][a-z]|\[\d+\]\s+[A-Z])",
    re.MULTILINE,
)

# Quaternary fallback: bracketed-numbered references lists with no explicit
# "References" heading (e.g. SoftwareX-style journals). We look for the first
# ``[1]`` at line start followed soon by ``[2]`` — this defines the start of
# the bracketed reference block. The two-bracket sequence requirement keeps
# this from triggering on prose references like ``in [1]`` mid-document. The
# 1500-char window is generous enough to accommodate long first-reference
# entries (CRediT-style author lists, abstract-like descriptions, DOI URLs).
_REF_BRACKETED_RE = re.compile(
    r"(?:^|\n)\s*\[1\]\s+[A-Z].{0,1500}?\n.{0,1500}?\[2\]\s+[A-Z]",
    re.DOTALL,
)

# Final fallback: detect end-of-body markers (Disclosure Statement, Funding,
# Acknowledgements, etc.) and look for a dense author-year run after the LAST
# such marker. This catches papers like 592YDKFM where pdfplumber's section
# detector failed to recognise the "References" heading at all, but the
# bibliography is still present in the extracted text. The end-marker prefix
# requirement avoids triggering on in-body author-year citation density.
_END_OF_BODY_MARKERS_RE = re.compile(
    # Require at least one leading ``#`` so prose like "Funding for the
    # project came from…" doesn't trigger the fallback. Case-sensitive on
    # the heading text — pdfplumber preserves the source-document case.
    r"^#{1,4}\s+("
    r"Disclosure\s+Statement|"
    r"Funding(?:\s+(?:Statement|Information))?|"
    r"Acknowledg(?:e)?ments?|"
    r"Author\s+Contributions?|"
    r"Conflict\s+of\s+Interest|"
    r"Declaration\s+of\s+(?:Competing|Conflicting)\s+Interests?|"
    r"Supplementary\s+(?:Data|Materials?)|"
    r"Appendix\s+[A-Z](?:\.|\s)"
    r")\b",
    re.MULTILINE | re.IGNORECASE,
)

_AUTHOR_YEAR_TAIL_RE = re.compile(
    r"[A-Z][A-Za-z'\-]+,\s+[A-Z]\.(?:\s*[A-Z]\.)?[^.\n]*?\(\d{4}[a-z]?\)"
)


# ---------------------------------------------------------------------------
# Per-key manifest overrides
# ---------------------------------------------------------------------------

# The Zotero manifest's automatic field guesses are occasionally wrong. Where
# the QA agent (2026-05-24 audit report) confirmed a manifest mistake, we
# pin the correct value here so the QA flagging logic does the right thing.
PER_KEY_MANIFEST_OVERRIDES = {
    # GNPTJ3EZ is the Survey Methodology chapter of the TRAP final report
    # (volume key I3IDESQN). The chapter has no chapter-level references —
    # the volume bibliography is a separate Zotero item. Manifest's
    # has_references=True is wrong; override to False so the
    # `references_split_failed` flag is correctly suppressed.
    "GNPTJ3EZ": {"has_references": False},
}


def apply_manifest_overrides(entry: dict) -> dict:
    key = entry.get("key")
    if key in PER_KEY_MANIFEST_OVERRIDES:
        return {**entry, **PER_KEY_MANIFEST_OVERRIDES[key]}
    return entry


# ---------------------------------------------------------------------------
# Post-extraction cleanup passes
# ---------------------------------------------------------------------------

# Single-word section headings that ARE legitimate (whitelist used by the
# fragment-heading dropper). All-lower-case for comparison.
SECTION_WORDS = frozenset({
    "abstract", "introduction", "methods", "methodology", "results",
    "discussion", "conclusion", "conclusions", "bibliography", "references",
    "acknowledgements", "acknowledgments", "funding", "background",
    "materials", "procedure", "findings", "implications", "limitations",
    "summary", "appendix", "appendices", "preface", "foreword", "epilogue",
    "afterword", "notes", "footnotes", "endnotes", "glossary", "index",
    "preliminaries", "data", "supplementary", "overview", "scope",
})


def strip_running_headers(markdown: str, min_chars: int = 15, min_occurrences: int = 4) -> tuple[str, int]:
    """Strip lines that appear verbatim many times (PDF running headers).

    The QA agent (2026-05-24) found that PyMuPDF / pdfplumber preserve
    journal running headers, chapter running titles, and other per-page
    boilerplate when those tokens get H2-promoted by the section detector.
    A line of ≥``min_chars`` chars appearing ≥``min_occurrences`` times
    verbatim is almost always such boilerplate (genuine repeated section
    headings are short and on a whitelist; see ``drop_fragment_headings``).

    Returns ``(cleaned_markdown, n_lines_stripped)``.
    """
    lines = markdown.split("\n")

    def normalise(line: str) -> str:
        return line.strip().lstrip("#").strip()

    counts: collections.Counter[str] = collections.Counter()
    for line in lines:
        key = normalise(line)
        if len(key) >= min_chars:
            counts[key] += 1

    repeating = {k for k, c in counts.items() if c >= min_occurrences}
    if not repeating:
        return markdown, 0

    n_stripped = 0
    kept = []
    for line in lines:
        if normalise(line) in repeating:
            n_stripped += 1
            continue
        kept.append(line)
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n_stripped


def drop_fragment_headings(markdown: str) -> tuple[str, int]:
    """Drop H1-H6 lines whose text is a 1-2 word fragment.

    PyMuPDF / pdfplumber's section detector aggressively promotes title-case
    or all-caps lines to headings. On PDFs with rich masthead typography this
    explodes the H2 count (ENPYIZQF: 562 H2s; 592YDKFM: 556 H2s per the
    2026-05-24 QA audit). Most are fragments such as ``## JD`` (running
    header), ``## Z.,`` (broken reference initial), ``## (AI)``
    (parenthetical), or ``## M7K64G4T`` (DOI fragment). These are not
    section structure and should not be in the Markdown at all.

    Keep:
    - Numbered section headings (``1.``, ``3.2``, ``A.1 Methods``)
    - Whitelisted single-word section names (``Abstract``, ``References`` …)
    - 2-word all-caps section labels (``AUTHOR AFFILIATIONS``)
    - 3+ word headings

    Drop everything else.
    """
    n_dropped = 0

    def maybe_drop(match: re.Match) -> str:
        nonlocal n_dropped
        text = match.group(2).strip()
        words = text.split()
        # Numbered section headings — keep
        if re.match(r"^([A-Z]?\d+)(\.\d+)*\.?\s+\S", text):
            return match.group(0)
        # 3+ word headings — keep (likely real section titles)
        if len(words) >= 3:
            return match.group(0)
        # 2-word all-caps headings (e.g. AUTHOR AFFILIATIONS) — keep
        if len(words) == 2 and text.isupper():
            return match.group(0)
        # Whitelisted single-word section names — keep
        if words:
            first = words[0].lower().rstrip(":.,;").strip("()")
            if first in SECTION_WORDS:
                return match.group(0)
        # Everything else (1-2 word fragments) — drop
        n_dropped += 1
        return ""

    cleaned = re.sub(r"^(#{1,6})\s+(.+)$", maybe_drop, markdown, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n_dropped


_AFFILIATION_TAIL_RE = re.compile(
    r"^#{1,4}\s+(AUTHOR\s+AFFILIATIONS?|Author\s+Affiliations?|"
    r"AFFILIATIONS?|Affiliations?|Corresponding\s+Author)\s*$",
    re.MULTILINE,
)


def strip_affiliation_tail(markdown: str) -> tuple[str, int]:
    """Strip from an ``AUTHOR AFFILIATIONS`` (or similar) heading to EOF.

    Some journals (Ubiquity, COPIM, Open Library of the Humanities) place
    an author-affiliations block with ORCIDs and institutional addresses
    at the end of the body, after the references. When that block leaks
    into the body, it pollutes pronoun counts and lexical metrics.
    Returns ``(cleaned_markdown, n_chars_stripped)``.
    """
    match = _AFFILIATION_TAIL_RE.search(markdown)
    if not match:
        return markdown, 0
    cleaned = markdown[: match.start()].rstrip()
    return cleaned, len(markdown) - len(cleaned)


# ---------------------------------------------------------------------------
# Per-key chapter-slicing rules
# ---------------------------------------------------------------------------

# Some Zotero entries reference a chapter or paper inside a larger PDF. The
# raw extraction returns the whole document; we need to slice down to the
# Shawn-authored portion before the body/refs split runs. Each rule is a
# ``(start_regex, end_regex)`` pair applied to the extracted Markdown — text
# between the LAST start match and the next end match (after that point) is
# kept. The same chapter-8 boundary that run-1 used for SP2R6FF9 (see
# style-guide-academic-2026-05-22.md Appendix B note at line 912-919) is
# reproduced here so the metric basis remains comparable across runs.
CHAPTER_SLICE_RULES = {
    "SP2R6FF9": (
        # Second occurrence of the chapter title (first occurrence is in the
        # volume's TOC at line ~41 of the extracted Markdown).
        re.compile(r"^##\s+Building the Bazaar.*$", re.MULTILINE),
        # Chapter 9 author block — Joshua Wells starts the next chapter.
        re.compile(r"^##\s+Joshua Wells, Christopher Parr.*$", re.MULTILINE),
    ),
}

# Per-key body/references split overrides. Used when the generic detector
# chain (strict heading → loose heading → paragraph-prefix → bracketed-numbered
# → end-marker + author-year density) cannot find the split — typically
# because PyMuPDF's section detector destroyed the structure of the
# reference list. Maps key → regex whose first match marks the start of the
# references block.
PER_KEY_REF_SPLIT_RULES = {
    # 592YDKFM (Sobotkova et al. 2021, JFA) — JFA uses bare-year refs and the
    # extractor scrambled them; first reference entry is "Banning, E. B., …"
    # and there's no surviving "References" heading.
    "592YDKFM": re.compile(r"^Banning,\s+E\.\s+B\.", re.MULTILINE),
}


def apply_chapter_slice(key: str, markdown: str) -> tuple[str, str]:
    """Slice the extracted Markdown for keys whose PDF carries a larger work.

    Returns ``(sliced_markdown, slice_method)``. For keys without a rule, the
    input is returned untouched with ``slice_method='none'``.
    """
    if key not in CHAPTER_SLICE_RULES:
        return markdown, "none"

    start_re, end_re = CHAPTER_SLICE_RULES[key]
    starts = list(start_re.finditer(markdown))
    if not starts:
        return markdown, "chapter-slice-start-not-found"
    start = starts[-1].start()  # last occurrence = body, not TOC

    end_match = end_re.search(markdown, start + 1)
    if not end_match:
        # Fail open: return the FULL original markdown rather than the
        # truncated chapter+tail. Truncating to ``markdown[start:]`` would
        # silently bundle the next chapter, volume bibliography, and back
        # matter into the body (the SP2R6FF9 over-bundle failure mode).
        # The "chapter-slice-end-not-found" label flags the issue for QA.
        return markdown, "chapter-slice-end-not-found"
    return markdown[start : end_match.start()].rstrip(), "chapter-slice-applied"


def split_body_references(markdown: str) -> tuple[str, str, str]:
    """Return ``(body_md, references_md, method)``.

    The upstream extractor emits a single Markdown document; we split it at
    the last References-style boundary, trying five detectors in order:
    strict heading → loose heading → paragraph-prefix "References Author,…" →
    bracketed-numbered "[1] Author …" → end-of-body marker + author-year
    density tail. If none fires, body keeps everything and references is
    empty. The chosen split method is reported so the QA layer can flag
    papers where reference detection failed.
    """
    # Use the LAST match — papers may mention the word "references" earlier
    # (e.g. "see references in §3") but the actual section is at end.
    matches = list(_REF_HEADING_RE.finditer(markdown))
    if matches:
        cut = matches[-1].start()
        return markdown[:cut].rstrip(), markdown[cut:].strip(), "strict-heading"

    matches = list(_REF_HEADING_LOOSE_RE.finditer(markdown))
    if matches:
        cut = matches[-1].start()
        return markdown[:cut].rstrip(), markdown[cut:].strip(), "loose-heading"

    matches = list(_REF_PARAGRAPH_RE.finditer(markdown))
    if matches:
        cut = matches[-1].start()
        return markdown[:cut].rstrip(), markdown[cut:].strip(), "paragraph-prefix"

    matches = list(_REF_BRACKETED_RE.finditer(markdown))
    if matches:
        cut = matches[-1].start()
        return markdown[:cut].rstrip(), markdown[cut:].strip(), "bracketed-numbered"

    # Final fallback — end-of-body marker + dense author-year tail run.
    end_markers = list(_END_OF_BODY_MARKERS_RE.finditer(markdown))
    if end_markers:
        # Probe the text after the last marker for an author-year run.
        tail_start = end_markers[-1].end()
        tail = markdown[tail_start:]
        ay_in_tail = list(_AUTHOR_YEAR_TAIL_RE.finditer(tail))
        if len(ay_in_tail) >= 8:
            # Cut at the line containing the first author-year entry.
            cut_in_tail = ay_in_tail[0].start()
            abs_cut = tail_start + cut_in_tail
            line_start = markdown.rfind("\n", 0, abs_cut) + 1
            return (
                markdown[:line_start].rstrip(),
                markdown[line_start:].strip(),
                "end-marker-author-year-density",
            )

    return markdown.strip(), "", "no-references-heading-found"


# ---------------------------------------------------------------------------
# QA flag computation
# ---------------------------------------------------------------------------

# Unicode-aware word regex for the per-paper word counts. Matches a letter
# token in any script (Latin with diacritics, Greek, Cyrillic) — important
# for an archaeology corpus that routinely cites Müller, Sobotková,
# Çatalhöyük etc.
_QA_WORD_RE = re.compile(r"[^\W\d_][^\W\d_'’\-]*", re.UNICODE)


def compute_qa_flags(
    body_md: str,
    references_md: str,
    split_method: str,
    extractor_stats: dict,
    manifest_entry: dict,
) -> dict:
    """Per-paper QA flags written to qa.json.

    Designed to be machine-readable so a downstream QA agent can iterate
    over all 18 qa.json files and flag anything that looks wrong.
    """
    body_words = len(_QA_WORD_RE.findall(body_md))
    ref_words = len(_QA_WORD_RE.findall(references_md))

    manifest_words = manifest_entry.get("n_words", 0)
    # Manifest n_words includes the entire PDF text (refs + body + headers).
    # Our body_words excludes refs and headers/footers. A loose comparison:
    # body+refs should be in the ballpark of manifest_words.
    extracted_total = body_words + ref_words
    delta_pct = (
        (extracted_total - manifest_words) / manifest_words * 100
        if manifest_words else 0.0
    )

    flags = []
    # The Zotero manifest's ``has_references`` field declares whether a
    # references section is expected. Several papers (e.g. book chapters
    # whose references live in a separate volume bibliography) genuinely
    # have no references section; flagging those as "split failed" is a
    # false positive. Only flag when references are expected but absent.
    expects_refs = manifest_entry.get("has_references", True)
    if expects_refs and split_method == "no-references-heading-found":
        flags.append("references_split_failed")
    if expects_refs and ref_words == 0:
        flags.append("zero_reference_words")
    if body_words == 0:
        flags.append("zero_body_words")
    if abs(delta_pct) > 25:
        flags.append(f"word_count_delta_{delta_pct:+.0f}pct")
    if "## Abstract" not in body_md and "Abstract" in body_md[:2000]:
        flags.append("abstract_present_but_not_promoted")
    if extractor_stats.get("sections_detected", 0) < 3:
        flags.append("few_sections_detected")

    return {
        "split_method": split_method,
        "body_words": body_words,
        "reference_words": ref_words,
        "extracted_total_words": extracted_total,
        "manifest_n_words": manifest_words,
        "word_count_delta_pct": round(delta_pct, 2),
        "pages": extractor_stats.get("pages", 0),
        "sections_detected": extractor_stats.get("sections_detected", 0),
        "tables_found": extractor_stats.get("tables_found", 0),
        "extractor_stats_raw": extractor_stats,
        "flags": flags,
        "needs_review": bool(flags),
    }


# ---------------------------------------------------------------------------
# Per-paper extraction
# ---------------------------------------------------------------------------

def extract_one(manifest_entry: dict, output_dir: Path) -> dict:
    """Extract a single paper and write its output bundle.

    Returns a dict summarising the outcome (key, status, qa_flags, paths).
    Captures exceptions so that a single bad PDF doesn't abort the whole run.

    Pipeline order:
      1. Apply per-key manifest overrides (e.g. correct ``has_references``).
      2. Raw extract via ``PDFExtractor.extract()`` → full Markdown.
      3. Apply per-key chapter slice (e.g. SP2R6FF9 chapter 8 of edited volume).
      4. Strip running headers / per-page boilerplate (lines repeated ≥4×).
      5. Drop fragment H2 headings (single-word noise from PyMuPDF's section
         detector) before they confuse the body/refs splitter.
      6. Try the body/refs split detector chain.
      7. Strip any author-affiliation tail block from the body.
      8. Clean reference-section formatting.
    """
    manifest_entry = apply_manifest_overrides(manifest_entry)
    key = manifest_entry["key"]
    pdf_path = Path(manifest_entry["pdf_path"])
    paper_dir = output_dir / key
    paper_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        msg = f"PDF not found: {pdf_path}"
        (paper_dir / "extraction-error.txt").write_text(msg)
        return {"key": key, "status": "error", "error": msg}

    extractor = PDFExtractor()
    try:
        markdown = extractor.extract(pdf_path)
    except Exception as exc:
        tb = traceback.format_exc()
        (paper_dir / "extraction-error.txt").write_text(f"{exc}\n\n{tb}")
        return {"key": key, "status": "error", "error": str(exc)}

    sliced_md, slice_method = apply_chapter_slice(key, markdown)

    # Post-extraction cleanup — running headers + fragment H2s — before split.
    cleaned_md, n_running_stripped = strip_running_headers(sliced_md)
    cleaned_md, n_fragment_h2_dropped = drop_fragment_headings(cleaned_md)

    body_md, references_md, split_method = split_body_references(cleaned_md)

    # Per-key body/refs split override — used when the generic chain failed
    # but we know the split point from a previous QA pass.
    if split_method == "no-references-heading-found" and key in PER_KEY_REF_SPLIT_RULES:
        match = PER_KEY_REF_SPLIT_RULES[key].search(cleaned_md)
        if match:
            line_start = cleaned_md.rfind("\n", 0, match.start()) + 1
            body_md = cleaned_md[:line_start].rstrip()
            references_md = cleaned_md[line_start:].strip()
            split_method = "per-key-override"

    body_md, n_affiliation_chars = strip_affiliation_tail(body_md)
    references_md = clean_reference_section(references_md) if references_md else ""

    # Paper outputs
    (paper_dir / "body.md").write_text(body_md, encoding="utf-8")
    (paper_dir / "references.md").write_text(references_md, encoding="utf-8")
    (paper_dir / "full.md").write_text(markdown, encoding="utf-8")  # forensic copy

    # Metadata — Zotero manifest fields + extraction provenance
    metadata = {
        "key": key,
        "zotero": {
            "itemID": manifest_entry.get("itemID"),
            "typeName": manifest_entry.get("typeName"),
            "title": manifest_entry.get("title"),
            "date": manifest_entry.get("date"),
            "pub": manifest_entry.get("pub"),
            "authors": manifest_entry.get("authors", []),
            "role": manifest_entry.get("role"),
            "pdf_path": str(pdf_path),
        },
        "extraction": {
            "tool": "PyMuPDF (fitz) + pdfplumber via llm-reproducibility/extract_pdf_text.py",
            "tool_versions": _tool_versions(),
            "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
            "config": extractor.config,
        },
    }
    (paper_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    qa = compute_qa_flags(body_md, references_md, split_method, extractor.stats, manifest_entry)
    qa["slice_method"] = slice_method
    qa["cleanup"] = {
        "running_header_lines_stripped": n_running_stripped,
        "fragment_h2_dropped": n_fragment_h2_dropped,
        "affiliation_chars_stripped": n_affiliation_chars,
    }
    (paper_dir / "qa.json").write_text(json.dumps(qa, indent=2))

    return {
        "key": key,
        "status": "ok",
        "body_words": qa["body_words"],
        "reference_words": qa["reference_words"],
        "split_method": split_method,
        "slice_method": slice_method,
        "needs_review": qa["needs_review"],
        "flags": qa["flags"],
    }


def _tool_versions() -> dict:
    versions = {}
    try:
        import fitz  # type: ignore

        versions["pymupdf"] = fitz.__version__
    except Exception:
        versions["pymupdf"] = "unknown"
    try:
        import pdfplumber  # type: ignore

        versions["pdfplumber"] = pdfplumber.__version__
    except Exception:
        versions["pdfplumber"] = "unknown"
    return versions


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument(
        "--keys",
        default="",
        help="comma-separated subset of Zotero keys to extract (default: all included)",
    )
    ap.add_argument(
        "--include-excluded",
        action="store_true",
        help="also extract manifest entries marked EXCLUDED from analysis",
    )
    args = ap.parse_args()

    with args.manifest.open() as f:
        manifest = json.load(f)

    # Filter — by default skip EXCLUDED items, but the user opted in to the
    # 18-paper scope (2026-05-24 scoping question), so the excluded ones stay
    # out unless --include-excluded is passed. Match is case-insensitive on
    # "exclude" so "EXCLUDED", "Excluded", "excluded" all hit.
    def is_excluded(entry):
        notes = (entry.get("extraction_notes") or "").lower()
        return "exclude" in notes

    if args.keys:
        # Strip whitespace and drop empty tokens — natural CLI spacing
        # (e.g. "--keys SP2R6FF9, 5INAFTVT") and trailing commas would
        # otherwise silently fail to match any entry.
        wanted = {k.strip() for k in args.keys.split(",") if k.strip()}
        entries = [e for e in manifest if e.get("key") in wanted]
        if not entries:
            print(
                f"ERROR: --keys {args.keys!r} matched no manifest entries.",
                file=sys.stderr,
            )
            return 2
    elif args.include_excluded:
        entries = manifest
    else:
        entries = [e for e in manifest if not is_excluded(e)]

    args.output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for entry in entries:
        key = entry.get("key")
        if not key:
            print(f"\nSKIP: manifest entry without 'key' field: {entry}", file=sys.stderr)
            results.append({"key": None, "status": "error", "error": "manifest entry has no 'key' field"})
            continue
        print(f"\n=== {key} ({entry.get('typeName', '?')}, {entry.get('date', '?')}) ===")
        try:
            result = extract_one(entry, args.output_dir)
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"  UNHANDLED ERROR: {exc}", file=sys.stderr)
            print(tb, file=sys.stderr)
            result = {"key": key, "status": "error", "error": str(exc)}
        results.append(result)
        if result["status"] == "ok":
            review = " ⚠ needs review" if result["needs_review"] else ""
            print(
                f"  body={result['body_words']}w  refs={result['reference_words']}w  "
                f"split={result['split_method']}{review}"
            )
            if result["flags"]:
                for flag in result["flags"]:
                    print(f"    flag: {flag}")
        else:
            print(f"  ERROR: {result.get('error', 'unknown')}")

    # Corpus-level manifest
    corpus_manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(args.manifest),
        "n_papers_extracted": sum(1 for r in results if r["status"] == "ok"),
        "n_errors": sum(1 for r in results if r["status"] == "error"),
        "n_needs_review": sum(
            1 for r in results if r["status"] == "ok" and r["needs_review"]
        ),
        "results": results,
    }
    (args.output_dir.parent / "corpus-manifest.json").write_text(
        json.dumps(corpus_manifest, indent=2)
    )
    print(f"\nWrote {args.output_dir.parent / 'corpus-manifest.json'}")
    print(
        f"Extracted: {corpus_manifest['n_papers_extracted']}  "
        f"Errors: {corpus_manifest['n_errors']}  "
        f"Needs review: {corpus_manifest['n_needs_review']}"
    )

    return 0 if corpus_manifest["n_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
