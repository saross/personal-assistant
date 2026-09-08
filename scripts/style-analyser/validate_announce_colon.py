#!/usr/bin/env python3
"""
validate_announce_colon.py — HUMAN-AUDIT PRINTER for ``_ANNOUNCE_COLON_RE``.

**This script asserts nothing and decides nothing.** It samples announcement-
colon regex hits from a handful of corpus papers, labels each one with crude
string heuristics, and prints the surrounding window so that *a person* can
read the sample and judge whether the regex is measuring announcement colons
or extraction artefacts (sub-headings, table cells, metadata rows, captions,
URLs). The verdicts printed below are a first pass for that reader to
overrule, not a test result: nothing here fails a build, and the "corrected"
rates are only as good as the heuristics plus the human classification that
follows them.

Corpus layout
-------------
Reads the clean extraction at ``data/style-corpus/extracted/<key>/body.md``,
resolved against the repository root derived from ``__file__`` — so the script
behaves the same from any working directory, and never depends on ``~``.
``--corpus-dir`` points it at some other extraction and ``--keys`` chooses the
papers. The pre-2026-05-24 layout it used to read
(``/tmp/style-corpus-extract/<key>.txt``) no longer exists; reading it, and
dying with an unhandled ``FileNotFoundError`` when it was absent, was audit
finding ST14.

Exit status
-----------
``0`` when at least one example was printed; ``1`` when the sample came out
empty — no paper readable, or no regex match in any paper that was. An audit
printer that printed nothing must not be mistaken for a pass.

Outputs:
  * numbered examples with offset, window, verdict, and rationale
  * per-paper verdict tallies
  * corrected ``announcement_colon_per_1k`` estimates where phase 1 reported a
    rate to correct, and an explicit "not available" where it did not (a
    missing ``phase1-results.json`` used to be reported as a rate of 0.000/1k,
    indistinguishable from a measured zero — audit finding L2)
  * an unweighted mean over exactly those papers that had both a reported rate
    and a non-empty sample, with the count of those papers derived from the
    data rather than hard-coded (audit finding L1)

Run with this repository's interpreter, e.g.:
    ~/personal-assistant/venv/bin/python3 \\
        scripts/style-analyser/validate_announce_colon.py --help
"""

# UK/Australian spelling preserved throughout per global CLAUDE.md.

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

# Make the pipeline module importable.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from phase1_pipeline import _ANNOUNCE_COLON_RE, strip_references  # noqa: E402

#: Repository root, derived from this file's location (``<root>/scripts/
#: style-analyser/``). Deliberately not ``Path.home()``: the script must work
#: from a worktree, a checkout under another name, or any working directory.
REPO_ROOT = SCRIPT_DIR.parent.parent

#: The QA-passed clean extraction: one directory per paper, prose in body.md.
DEFAULT_CORPUS_DIR = REPO_ROOT / "data" / "style-corpus" / "extracted"

#: Papers sampled when ``--keys`` is not given. Chosen in the original
#: validation task as the three highest reported announcement-colon rates.
DEFAULT_KEYS = ["5INAFTVT", "5Y4VT9VK", "GNPTJ3EZ"]

SEED = 42
SAMPLES_PER_PAPER = 10
LEFT_CHARS = 50
RIGHT_CHARS = 70


# ---------------------------------------------------------------------------
# Corpus access
# ---------------------------------------------------------------------------

def body_path(corpus_dir: Path, key: str) -> Path:
    """Return the prose file for paper ``key`` in the clean-extraction layout."""
    return corpus_dir / key / "body.md"


def default_results_json(corpus_dir: Path) -> Path:
    """Return the phase 1 results file that accompanies ``corpus_dir``.

    Kept relative to the corpus directory, as it was under the old layout, so
    pointing ``--corpus-dir`` at a different extraction picks up that
    extraction's own results without a second flag.
    """
    return corpus_dir / "analysis" / "phase1-results.json"


def read_body(path: Path) -> str | None:
    """Return the text of ``path``, or ``None`` if it cannot be read.

    A missing or unreadable paper is a diagnostic on stderr and a skipped
    paper, never a traceback: one absent extraction must not stop the operator
    from auditing the papers that *are* present (audit finding ST14).
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"  SKIPPED: cannot read {path} ({exc})", file=sys.stderr)
        return None


def load_reported_rates(results_json: Path) -> dict[str, float]:
    """Map paper key to its phase 1 ``announcement_colon_per_1k``.

    An empty mapping means "no reported rate is available", which the caller
    renders as "not available" rather than as a rate of zero.
    """
    if not results_json.exists():
        print(f"  NOTE: no phase 1 results at {results_json}; reported and "
              f"corrected rates will be shown as not available",
              file=sys.stderr)
        return {}
    data = json.loads(results_json.read_text(encoding="utf-8"))
    pp = data.get("per_paper", data)
    rates: dict[str, float] = {}
    if isinstance(pp, list):
        for entry in pp:
            k = entry.get("key")
            v = entry.get("announcement_colon_per_1k")
            if k and v is not None:
                rates[k] = float(v)
    return rates


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

def window(stripped: str, colon_pos: int) -> tuple[str, str, str]:
    """Return (left context, right context, printable window) around a colon."""
    lo = max(0, colon_pos - LEFT_CHARS)
    hi = min(len(stripped), colon_pos + 1 + RIGHT_CHARS)
    left = stripped[lo:colon_pos]
    right = stripped[colon_pos + 1: hi]
    centred = stripped[lo:hi].replace("\n", "\\n")
    return left, right, centred


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line for this printer.

    Every path default is a *default*, not a constant: an operator auditing a
    re-extraction points ``--corpus-dir`` at it and gets the same report.
    """
    parser = argparse.ArgumentParser(
        description="Print a sample of announcement-colon regex hits for a "
                    "human to classify. Asserts nothing.",
    )
    parser.add_argument(
        "--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR,
        help="directory of <key>/body.md bundles "
             f"(default: {DEFAULT_CORPUS_DIR})",
    )
    parser.add_argument(
        "--keys", nargs="+", default=list(DEFAULT_KEYS),
        help=f"paper keys to sample (default: {' '.join(DEFAULT_KEYS)})",
    )
    parser.add_argument(
        "--results-json", type=Path, default=None,
        help="phase 1 results file supplying the reported per-1k rates "
             "(default: <corpus-dir>/analysis/phase1-results.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Print the sample and return a process exit status.

    Returns ``1`` when nothing was printed, so that a run against a missing or
    empty extraction cannot be mistaken for a clean audit.
    """
    args = parse_args(argv)
    corpus_dir: Path = args.corpus_dir
    results_json: Path = args.results_json or default_results_json(corpus_dir)
    reported = load_reported_rates(results_json)
    rng = random.Random(SEED)

    per_paper_tallies: dict[str, dict[str, int]] = {}
    corrected_rates: dict[str, float] = {}
    examples_printed = 0

    for key in args.keys:
        raw = read_body(body_path(corpus_dir, key))
        if raw is None:
            continue
        stripped, method = strip_references(raw)

        matches = list(_ANNOUNCE_COLON_RE.finditer(stripped))
        total = len(matches)
        reported_rate = reported.get(key)
        reported_str = "not available" if reported_rate is None else f"{reported_rate:.3f}/1k"

        print("=" * 78)
        print(f"Paper {key}  |  strip-method={method}  |  total matches={total}"
              f"  |  reported rate={reported_str}")
        print("=" * 78)

        if total == 0:
            # No corrected estimate is recorded: there is no sample to correct
            # with, and a stored 0.0 would later be averaged as if it were one.
            per_paper_tallies[key] = {}
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
            examples_printed += 1
            print(f"\n  [{i:02d}] offset={colon_offset}  verdict={verdict}")
            if rationale:
                print(f"       rationale: {rationale}")
            print(f"       window: ...{centred}...")

        per_paper_tallies[key] = tally
        true_count = tally.get("TRUE ANNOUNCEMENT COLON", 0)
        n_sampled = len(sample)
        precision = true_count / n_sampled if n_sampled else 0.0

        print()
        print(f"  Tally for {key} (n={n_sampled}):")
        for v, c in sorted(tally.items(), key=lambda x: -x[1]):
            print(f"    {v:<28s} {c}")
        print(f"  Sample precision: {true_count}/{n_sampled} = {precision:.2f}")
        if reported_rate is None:
            print(f"  Corrected rate: not available "
                  f"(no reported rate for {key} in {results_json})")
        else:
            corrected_rates[key] = precision * reported_rate
            print(f"  Corrected rate (precision × reported): {corrected_rates[key]:.3f}/1k")

    # Corpus-wide corrected aggregate — an unweighted mean over the papers that
    # produced BOTH a sample and a reported rate. It is unweighted because
    # per-paper word counts are not read here; weight it by words from
    # phase1-results.json if a corpus-level figure is wanted.
    print()
    print("=" * 78)
    print("Summary")
    print("=" * 78)
    for k in args.keys:
        r = reported.get(k)
        c = corrected_rates.get(k)
        r_str = "not available" if r is None else f"{r:.3f}/1k"
        c_str = "not available" if c is None else f"{c:.3f}/1k"
        print(f"  {k}: reported {r_str}  ->  corrected {c_str}")

    if corrected_rates:
        # n is counted from the papers that actually contributed, not assumed:
        # with a skipped paper or a missing reported rate the old hard-coded
        # "n=3" divided by a denominator no paper stood behind (finding L1).
        contributing = sorted(corrected_rates)
        n_papers = len(contributing)
        mean_corrected = sum(corrected_rates[k] for k in contributing) / n_papers
        mean_reported = sum(reported[k] for k in contributing) / n_papers
        print(f"\n  Unweighted mean (n={n_papers}) — reported: {mean_reported:.3f}/1k  "
              f"corrected: {mean_corrected:.3f}/1k")
    else:
        print("\n  Unweighted mean: not available (no paper produced both a "
              "sample and a reported rate)")

    if examples_printed == 0:
        print(
            "EMPTY SAMPLE: no example was printed — every paper was unreadable "
            "or contained no announcement-colon match. Nothing was audited; "
            "check --corpus-dir and --keys.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
