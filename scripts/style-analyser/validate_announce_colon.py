#!/usr/bin/env python3
"""
validate_announce_colon.py — sample-check `_ANNOUNCE_COLON_RE` precision.

Loads three target papers from /tmp/style-corpus-extract/, strips references via
phase1_pipeline.strip_references, finds every announcement-colon regex match,
draws 10 samples per paper with a fixed seed (42), and prints a 120-char window
centred on each colon. Classification is performed by string heuristics that
mirror the typology requested in the validation task (sub-heading, table/list,
metadata, caption, URL/time/ratio, other, true).

Outputs:
  * 30 numbered examples with offset, window, verdict, rationale
  * Per-paper verdict tallies
  * Corrected announcement_colon_per_1k estimates
  * Corpus-wide corrected aggregate

Run with the write-like-me venv interpreter:
    ~/Code/write-like-me/.venv/bin/python validate_announce_colon.py
"""

# UK/Australian spelling preserved throughout per global CLAUDE.md.

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

# Make the pipeline module importable.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from phase1_pipeline import _ANNOUNCE_COLON_RE, strip_references  # noqa: E402

CORPUS_DIR = Path("/tmp/style-corpus-extract")
RESULTS_JSON = CORPUS_DIR / "analysis" / "phase1-results.json"

# Per-paper reported announcement-colon rates (per 1k words) from the v2
# pipeline run. Pulled live below from phase1-results.json for honesty;
# this dict is a fallback if the JSON is unreadable.
TARGETS = ["5INAFTVT", "5Y4VT9VK", "GNPTJ3EZ"]

SEED = 42
SAMPLES_PER_PAPER = 10
LEFT_CHARS = 50
RIGHT_CHARS = 70


# ---------------------------------------------------------------------------
# Classification heuristics
# ---------------------------------------------------------------------------

# A leading newline (or two) followed by short alphabetic "Heading:" then a
# newline suggests a sub-heading artefact: the X was a bold heading on its
# own line and the [A-Z] is the first paragraph word.
def _looks_like_subheading(left: str, right: str) -> bool:
    # The 50 chars to the left should end in a newline + whitespace, OR the
    # context immediately around the colon should be "Heading\n" patterns.
    if re.search(r"\n\s*$", left) is not None:
        return True
    # Right-side: colon then optional whitespace then newline then capital.
    if re.match(r"\s*\n\s*[A-Z]", right) is not None:
        return True
    # Short heading like "Methods" or "Conclusions" preceded by blank line.
    tail = left.rstrip()[-40:]
    if "\n\n" in left and re.search(r"\n\s*[A-Z][A-Za-z]{2,30}$", tail):
        return True
    return False


# pdftotext -layout will produce runs of multiple spaces between cells. If we
# see >=4 consecutive spaces near the colon, or repeated whitespace columns,
# this is almost certainly a table / list-leader artefact.
def _looks_like_table(left: str, right: str) -> bool:
    if re.search(r" {4,}", left[-40:]) or re.search(r" {4,}", right[:40]):
        return True
    # Pipe / table-character heuristics.
    if "|" in left[-30:] or "|" in right[:30]:
        return True
    return False


_METADATA_KEYS = (
    "author", "authors", "title", "keywords", "email", "correspondence",
    "corresponding author", "affiliation", "received", "accepted",
    "published", "doi", "issn", "abstract", "subject", "subjects",
    "from", "to", "cc", "subject:", "license", "copyright",
    "publisher", "journal", "volume", "issue", "page", "pages",
)


def _looks_like_metadata(left: str) -> bool:
    # Look at the alphabetic word immediately preceding the colon.
    m = re.search(r"([A-Za-z][A-Za-z\- ]{0,40})\s*:\s*$", left + ":")
    if not m:
        return False
    key = m.group(1).strip().lower()
    # Walk back to the last word/phrase before colon.
    last_segment = key.split("\n")[-1].strip()
    if last_segment in _METADATA_KEYS:
        return True
    # Common short metadata patterns: "Tel:", "Fax:", "URL:".
    if last_segment in {"tel", "fax", "url", "isbn", "orcid"}:
        return True
    return False


def _looks_like_caption(left: str) -> bool:
    tail = left[-40:].lower()
    return bool(re.search(r"\b(figure|fig\.?|table|tab\.?|plate|map|chart)\s+\d+\s*$", tail))


def _looks_like_url_time_ratio(left: str, right: str) -> bool:
    # URL: contains "http" or "ftp" within a few chars of colon.
    if "http" in left[-10:] or "ftp" in left[-10:]:
        return True
    # Time / ratio escape: digit immediately before the colon. The regex's
    # lookbehind should already exclude these, but check anyway.
    if re.search(r"\d\s*$", left):
        return True
    return False


def classify(left: str, right: str, full_match: str) -> tuple[str, str]:
    """Return (verdict, rationale)."""
    if _looks_like_url_time_ratio(left, right):
        return "URL/TIME/RATIO/RANGE", "digit or URL token adjacent to colon"
    if _looks_like_metadata(left):
        return "SPEAKER OR METADATA", "preceded by metadata field name"
    if _looks_like_caption(left):
        return "FIGURE_CAPTION", "preceded by Figure/Table N pattern"
    if _looks_like_table(left, right):
        return "TABLE OR LIST ARTEFACT", "multi-space gap or pipe near colon"
    if _looks_like_subheading(left, right):
        return "SUB-HEADING ARTEFACT", "newline boundary at colon (heading + next paragraph)"
    return "TRUE ANNOUNCEMENT COLON", ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_reported_rates() -> dict[str, float]:
    if not RESULTS_JSON.exists():
        return {}
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    pp = data.get("per_paper", data)
    rates = {}
    if isinstance(pp, list):
        for entry in pp:
            k = entry.get("key")
            v = entry.get("announcement_colon_per_1k")
            if k and v is not None:
                rates[k] = float(v)
    return rates


def window(stripped: str, colon_pos: int) -> tuple[str, str, str]:
    lo = max(0, colon_pos - LEFT_CHARS)
    hi = min(len(stripped), colon_pos + 1 + RIGHT_CHARS)
    left = stripped[lo:colon_pos]
    right = stripped[colon_pos + 1: hi]
    centred = stripped[lo:hi].replace("\n", "\\n")
    return left, right, centred


def main() -> int:
    reported = load_reported_rates()
    rng = random.Random(SEED)

    per_paper_tallies: dict[str, dict[str, int]] = {}
    corrected_rates: dict[str, float] = {}

    for key in TARGETS:
        path = CORPUS_DIR / f"{key}.txt"
        raw = path.read_text(encoding="utf-8", errors="replace")
        stripped, method = strip_references(raw)

        matches = list(_ANNOUNCE_COLON_RE.finditer(stripped))
        total = len(matches)

        print("=" * 78)
        print(f"Paper {key}  |  strip-method={method}  |  total matches={total}"
              f"  |  reported rate={reported.get(key, 'NA')}/1k")
        print("=" * 78)

        if total == 0:
            per_paper_tallies[key] = {}
            corrected_rates[key] = 0.0
            continue

        # Sample without replacement; fall back to all matches if fewer than 10.
        sample = matches if total <= SAMPLES_PER_PAPER else rng.sample(matches, SAMPLES_PER_PAPER)

        tally: dict[str, int] = {}
        for i, m in enumerate(sample, 1):
            # The match spans "<word(s)>: <Cap>". Find the colon inside it.
            colon_offset = m.start() + m.group(0).find(":")
            left, right, centred = window(stripped, colon_offset)
            verdict, rationale = classify(left, right, m.group(0))
            tally[verdict] = tally.get(verdict, 0) + 1
            print(f"\n  [{i:02d}] offset={colon_offset}  verdict={verdict}")
            if rationale:
                print(f"       rationale: {rationale}")
            print(f"       window: ...{centred}...")

        per_paper_tallies[key] = tally
        true_count = tally.get("TRUE ANNOUNCEMENT COLON", 0)
        n_sampled = len(sample)
        precision = true_count / n_sampled if n_sampled else 0.0
        reported_rate = reported.get(key, 0.0)
        corrected_rates[key] = precision * reported_rate

        print()
        print(f"  Tally for {key} (n={n_sampled}):")
        for v, c in sorted(tally.items(), key=lambda x: -x[1]):
            print(f"    {v:<28s} {c}")
        print(f"  Sample precision: {true_count}/{n_sampled} = {precision:.2f}")
        print(f"  Corrected rate (precision × reported): {corrected_rates[key]:.3f}/1k")

    # Corpus-wide corrected aggregate — weight per-paper corrected rate by the
    # paper's word count, which is implicit in reported_rate × words_per_paper.
    # We don't have words readily; instead compute a simple unweighted mean
    # over the three targets for the corrected estimate. The user can rerun
    # on the full corpus from per_paper.json if desired.
    print()
    print("=" * 78)
    print("Summary")
    print("=" * 78)
    for k in TARGETS:
        r = reported.get(k, 0.0)
        c = corrected_rates.get(k, 0.0)
        print(f"  {k}: reported {r:.3f}/1k  ->  corrected {c:.3f}/1k")

    if corrected_rates:
        mean_corrected = sum(corrected_rates.values()) / len(corrected_rates)
        mean_reported = sum(reported.get(k, 0.0) for k in TARGETS) / len(TARGETS)
        print(f"\n  Unweighted mean (n=3) — reported: {mean_reported:.3f}/1k  "
              f"corrected: {mean_corrected:.3f}/1k")

    return 0


if __name__ == "__main__":
    sys.exit(main())
