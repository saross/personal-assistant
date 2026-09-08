"""
Tests for ``scripts/style-analyser/phase4_exemplar_scorer.py``.

Findings covered, all from the 2026-09-08 repository audit:

* **ST22** — ``split_sentences`` joined every cleaned line of a document into
  one string before splitting, so a paragraph whose last line carried no
  terminal punctuation was glued to the next paragraph's opening and the
  stitched result could be emitted as a single "exemplar sentence" spanning a
  paragraph break. An exemplar is meant to be shown to a model as a piece of
  the author's prose; a sentence that never existed is worse than none.
* **ST23** — the module docstring claimed 18 feature categories while the
  emitted ``n_categories`` said 17. The code's count is the honest one.
* **Cross-cutting** — the output was written with a plain ``write_text`` (an
  interrupted run truncated the JSON that the next stage then parsed as
  complete), the script had no ``--dry-run``, and the JSON recorded nothing
  about what had produced it.

Every fixture here is invented. The real corpus is private and this is a
public repository, so no paper key, sentence, or number below comes from it:
keys are of the form ``AAAA1111`` and the prose is assembled by
:func:`_paragraph` out of words chosen to trip known detectors.

``CORPUS`` is monkeypatched to a ``tmp_path`` rather than edited in the
script, and the tests ``chdir`` into a temporary directory before calling
``main`` so the script's relative output path lands there. Nothing here reads
or writes the real ``data/style-corpus`` tree.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import load_style_module, refuse_sockets  # noqa: E402

phase4 = load_style_module("phase4_exemplar_scorer")

#: Where ``main`` writes, relative to the working directory. Named here so the
#: tests do not have to repeat the script's own hard-coded output path.
OUT_RELATIVE = Path("data") / "style-corpus" / "phase4-exemplar-candidates.json"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; this script is CPU-only."""
    refuse_sockets(monkeypatch)


def _paragraph(n_words: int, last_word: str, terminal: str = ".") -> str:
    """Return exactly ``n_words`` synthetic words scoring five categories.

    The opening seven words trip ``first_plural`` ("We"), ``hedge`` ("may"),
    ``discipline_vocab`` ("fieldwork"), ``uk_orth`` ("behaviour"), and
    ``semicolon``; the rest is inert filler, so the score is stable at five
    whatever length is asked for. ``terminal`` is the sentence-final
    punctuation, and passing ``""`` produces the unterminated paragraph tail
    that finding ST22 is about.
    """
    head = ["We", "may", "note", "the", "fieldwork", "behaviour", "here;"]
    filler = ["alpha"] * (n_words - len(head) - 1)
    return " ".join(head + filler + [last_word + terminal])


def _write_paper(corpus: Path, key: str, body: str,
                 meta: dict | None = None) -> Path:
    """Create ``<corpus>/<key>/body.md`` (and metadata.json when given)."""
    paper = corpus / key
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "body.md").write_text(body, encoding="utf-8")
    if meta is not None:
        (paper / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return paper


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """An empty synthetic corpus directory, wired in as the module's ``CORPUS``.

    The module constant is monkeypatched rather than edited: the path default
    on the constant's own line belongs to another audit round.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    monkeypatch.setattr(phase4, "CORPUS", root)
    return root


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A working directory for ``main``, with the output path pointed into it.

    The output default is now absolute (an audit round moved both production
    paths off the working directory), so pointing ``main`` at a throwaway file
    means monkeypatching the module's ``OUT`` constant, exactly as ``corpus``
    does for ``CORPUS``. Relying on ``chdir`` alone would write into the real
    checkout's ``data/`` directory — which is precisely what it did, once,
    before this fixture was corrected.
    """
    root = tmp_path / "run"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(phase4, "OUT", root / OUT_RELATIVE)
    return root


def _candidates(run_dir: Path, key: str) -> list[dict]:
    """Return the emitted candidate list for one paper."""
    payload = json.loads((run_dir / OUT_RELATIVE).read_text(encoding="utf-8"))
    for paper in payload["per_paper"]:
        if paper["key"] == key:
            return paper["candidates"]
    return []


# ---------------------------------------------------------------------------
# ST22 — a sentence must never span a paragraph break
# ---------------------------------------------------------------------------

def test_split_sentences_never_joins_across_a_blank_line():
    """Two paragraphs stay two sentences even when the first is unterminated.

    The mutation this kills: restoring ``paragraph_text = " ".join(...)`` over
    the whole document, which glued the tail of one paragraph to the head of
    the next (finding ST22).
    """
    text = (
        _paragraph(25, "alphaend", terminal="")
        + "\n\n"
        + _paragraph(25, "omegaend")
        + "\n"
    )

    sents = phase4.split_sentences(text)

    assert len(sents) == 2
    assert not any("alphaend" in s and "omegaend" in s for s in sents)


def test_a_dropped_heading_also_ends_the_paragraph():
    """A markdown heading between two paragraphs is a boundary, not a join.

    Headings are stripped as non-prose; the mutation this kills is stripping
    them while leaving the surrounding lines adjacent, which stitches the
    paragraph before a heading onto the paragraph after it.
    """
    text = (
        _paragraph(12, "alphaend", terminal="")
        + "\n## A heading line\n"
        + _paragraph(12, "omegaend")
        + "\n"
    )

    sents = phase4.split_sentences(text)

    assert not any("alphaend" in s and "omegaend" in s for s in sents)


def test_a_stitched_sentence_is_never_emitted_as_a_candidate(corpus, run_dir):
    """End to end: the paragraph-spanning sentence never reaches the output.

    Both paragraphs qualify on their own (25 words, five categories each), and
    their concatenation would qualify too. The mutation this kills: the
    document-wide join, under which this paper emitted ONE candidate holding
    text from both paragraphs instead of two candidates holding one each.
    """
    _write_paper(corpus, "AAAA1111", (
        _paragraph(25, "alphaend", terminal="")
        + "\n\n"
        + _paragraph(25, "omegaend")
        + "\n"
    ))

    assert phase4.main([]) == 0

    candidates = _candidates(run_dir, "AAAA1111")
    assert len(candidates) == 2
    assert not any(
        "alphaend" in c["sentence"] and "omegaend" in c["sentence"]
        for c in candidates
    )


# ---------------------------------------------------------------------------
# ST23 — the documented category count must be the scored category count
# ---------------------------------------------------------------------------

def test_the_documented_category_count_matches_the_code():
    """The docstring's number is the one the code actually scores (ST23).

    ``n_categories`` is the regex categories plus the nominalisation detector.
    The mutation this kills: restoring the "18 sentence-detectable feature
    categories" prose, which disagreed with the 17 the file emits — and, if a
    category is ever genuinely added, this fails until the prose is updated
    with it.
    """
    doc = phase4.__doc__ or ""

    assert f"{len(phase4.PATTERNS) + 1} in total" in doc
    assert "18 sentence-detectable feature categories" not in doc


def test_the_emitted_category_count_is_derived_from_the_patterns(corpus, run_dir):
    """``n_categories`` in the JSON is computed, not typed in.

    The mutation this kills: hard-coding the number in the output dictionary,
    which is how the prose and the data came apart in the first place.
    """
    _write_paper(corpus, "AAAA1111", _paragraph(25, "omegaend") + "\n")

    assert phase4.main([]) == 0

    payload = json.loads((run_dir / OUT_RELATIVE).read_text(encoding="utf-8"))
    assert payload["n_categories"] == len(phase4.PATTERNS) + 1


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------

def test_a_category_is_counted_once_however_often_it_matches():
    """Three first-person pronouns are still one ``first_plural`` category.

    The mutation this kills: counting matches instead of categories (say,
    ``matched.extend(rx.findall(sent))``), which would let one repeated
    feature clear the three-category threshold on its own.
    """
    sentence = "We took our notes and we filed them ourselves in our record."

    score, matched = phase4.score_sentence(sentence, is_pre_2023=True)

    assert matched.count("first_plural") == 1
    assert score == len(matched)
    assert len(matched) == len(set(matched))


def test_em_dash_counts_only_for_a_pre_2023_paper():
    """The year-binning rule drops ``em_dash`` for 2023-and-later papers.

    The mutation this kills: removing the ``continue``, which would score the
    em dash as an attested pattern in papers where the guide treats it as an
    anti-pattern.
    """
    sentence = _paragraph(25, "omegaend").replace("here;", "here — and;")

    _, pre = phase4.score_sentence(sentence, is_pre_2023=True)
    _, post = phase4.score_sentence(sentence, is_pre_2023=False)

    assert "em_dash" in pre
    assert "em_dash" not in post
    assert set(pre) - set(post) == {"em_dash"}


@pytest.mark.parametrize("date,expected", [
    ("2019-04-01", True),
    ("2022", True),
    ("2023", False),
    ("2024-11", False),
    ("no date", True),
    ("", True),
])
def test_is_pre_2023_defaults_to_true_on_an_unparsable_date(date, expected):
    """An undated paper is treated as pre-2023, the conservative direction.

    The mutation this kills: returning ``False`` when the year will not parse,
    which silently drops the em-dash category for every paper whose metadata
    is missing or malformed.
    """
    assert phase4.is_pre_2023({"zotero": {"date": date}}) is expected


def test_an_absent_metadata_file_still_scores_as_pre_2023():
    """No metadata.json at all is the same conservative default.

    The mutation this kills: raising, or defaulting to 2023+, when
    ``load_meta`` returns an empty dictionary.
    """
    assert phase4.is_pre_2023({}) is True


def test_the_word_window_boundaries_are_inclusive(corpus, run_dir):
    """20 and 80 words are in; 19 and 81 are out.

    Each paragraph scores five categories, so length is the only thing
    separating them. The mutation this kills: turning either comparison
    strict (``wc <= MIN_WORDS`` / ``wc >= MAX_WORDS``), which quietly loses
    the exemplars sitting exactly on the boundary.
    """
    body = "\n\n".join(
        _paragraph(n, f"omega{n}") for n in (19, 20, 80, 81)
    ) + "\n"
    _write_paper(corpus, "AAAA1111", body)
    # Every qualifying sentence must survive the per-paper truncation.
    assert phase4.TOP_PER_PAPER < 4

    assert phase4.main([]) == 0

    emitted = {len(c["sentence"].split()) for c in _candidates(run_dir, "AAAA1111")}
    assert emitted == {20, 80}


def test_the_per_paper_top_n_is_ordered_and_truncated_deterministically(corpus,
                                                                        run_dir):
    """Ties on score break on sentence length, shortest first, and N is capped.

    Four sentences score five categories each, so only the tie-break
    distinguishes them. The mutation this kills: dropping the ``len(r[1])``
    tie-break (leaving the order dependent on document position) or dropping
    the ``[:TOP_PER_PAPER]`` truncation.
    """
    body = "\n\n".join(
        _paragraph(n, f"omega{n}") for n in (50, 20, 40, 30)
    ) + "\n"
    _write_paper(corpus, "AAAA1111", body)

    assert phase4.main([]) == 0

    lengths = [len(c["sentence"].split()) for c in _candidates(run_dir, "AAAA1111")]
    assert lengths == [20, 30, 40]


def test_papers_are_emitted_in_sorted_key_order_and_rerun_byte_identical(corpus,
                                                                         run_dir):
    """Output order is by key, and an unchanged re-run rewrites the same bytes.

    Byte-identical re-runs are the cheapest determinism check available, and
    they only hold because the provenance block carries no wall-clock field.
    The mutation this kills: iterating ``results`` in insertion order, or
    adding a timestamp to the output.
    """
    _write_paper(corpus, "BBBB2222", _paragraph(25, "omegaend") + "\n")
    _write_paper(corpus, "AAAA1111", _paragraph(25, "omegaend") + "\n")

    assert phase4.main([]) == 0
    first = (run_dir / OUT_RELATIVE).read_bytes()
    assert phase4.main([]) == 0
    second = (run_dir / OUT_RELATIVE).read_bytes()

    payload = json.loads(first.decode("utf-8"))
    assert [p["key"] for p in payload["per_paper"]] == ["AAAA1111", "BBBB2222"]
    assert first == second


# ---------------------------------------------------------------------------
# Cross-cutting: corpus guard, dry run, atomic write, provenance
# ---------------------------------------------------------------------------

def test_a_missing_corpus_directory_exits_two(tmp_path, monkeypatch, run_dir,
                                              capsys):
    """A corpus that is not there is exit status 2, not an empty success.

    The mutation this kills: dropping the ``CORPUS.is_dir()`` guard, after
    which ``iterdir`` raises — or, worse, a ``return 0`` that writes an empty
    candidate file over a good one.
    """
    monkeypatch.setattr(phase4, "CORPUS", tmp_path / "absent")

    code = phase4.main([])

    captured = capsys.readouterr()
    assert code == 2
    assert "Corpus dir not found" in captured.err
    assert not (run_dir / OUT_RELATIVE).exists()


def test_dry_run_writes_no_bytes_at_all(corpus, run_dir, capsys):
    """``--dry-run`` scores the corpus and creates nothing on disk.

    The mutation this kills: passing the flag through as ``dry_run=False``, or
    writing first and reporting the dry run afterwards — either of which
    overwrites a production output the operator was only inspecting.
    """
    _write_paper(corpus, "AAAA1111", _paragraph(25, "omegaend") + "\n")

    code = phase4.main(["--dry-run"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Dry run: nothing written" in captured.out
    assert not (run_dir / "data").exists()


def test_the_output_carries_a_provenance_block(corpus, run_dir):
    """The JSON records the script and the SHA-256 of every body.md read.

    The mutation this kills: dropping the ``provenance`` key, which left a
    results file that could not be tied back to the code or the input bytes
    behind it.
    """
    body_path = _write_paper(corpus, "AAAA1111",
                             _paragraph(25, "omegaend") + "\n") / "body.md"

    assert phase4.main([]) == 0

    payload = json.loads((run_dir / OUT_RELATIVE).read_text(encoding="utf-8"))
    provenance = payload["provenance"]
    assert provenance["script"] == "phase4_exemplar_scorer.py"
    assert [entry["path"] for entry in provenance["inputs"]] == [str(body_path)]
    assert provenance["inputs"][0]["sha256"] is not None
    # No wall-clock field: that is what makes a re-run byte-identical.
    assert "timestamp" not in provenance


def test_an_interrupted_write_leaves_the_previous_output_intact(corpus, run_dir,
                                                                monkeypatch):
    """A crash mid-write must not truncate the file the next stage reads.

    ``os.replace`` is made to raise, standing in for a Ctrl-C between opening
    the destination and finishing it. The mutation this kills: reverting to
    ``out_path.write_text(json.dumps(out, ...))``, under which the previous
    complete result is destroyed the instant the write begins.
    """
    _write_paper(corpus, "AAAA1111", _paragraph(25, "omegaend") + "\n")
    out = run_dir / OUT_RELATIVE
    out.parent.mkdir(parents=True)
    out.write_text('{"complete": true}\n', encoding="utf-8")

    def refuse_replace(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", refuse_replace)

    with pytest.raises(KeyboardInterrupt):
        phase4.main([])

    assert json.loads(out.read_text(encoding="utf-8")) == {"complete": True}
    # No temporary debris left behind for the next run to trip over.
    assert [p.name for p in out.parent.iterdir()] == [out.name]
