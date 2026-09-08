"""
Tests for ``scripts/style-analyser/phase1_pipeline.py``.

Phase 1 is where the corpus's published numbers come from, and the audit found
several of them measuring something other than what they were called:

* ``hapax_ratio`` divided by tokens while its own docstring, the plan, and the
  length-matched reference all define it over TYPES (ST5);
* ``passive_ratio`` counted qualifying verbs, so it was not a fraction of
  sentences and could exceed 1, while the guide's §5.1 target is presence per
  sentence (ST8);
* the nominalisation rate divided by spaCy's token count, punctuation
  included, while every other per-1 000-word rate divided by the alphabetic
  token count (ST9);
* the references header needed only a line BEGINNING with "References", so a
  sentence about references truncated the document (ST15), and the pre-pass
  ran over already-clean ``body.md`` as well;
* ``mattr_100`` silently returned plain type-token ratio below its window
  (ST20), the announcement-colon pattern fired after a year (ST18), the
  exclusion test was a substring match (ST21), and an empty corpus raised
  ``StatisticsError`` from inside a mean (STT5).

spaCy is not installed here and the real corpus is private, so every
spaCy-dependent function is exercised through an injected fake pipeline and
the sample text is invented.
"""

from __future__ import annotations

import json
import sys
import types
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import (  # noqa: E402
    FIXTURES_DIR, FakeNlp, FakeSent, FakeToken, load_style_module,
    refuse_sockets,
)

p1 = load_style_module("phase1_pipeline")

SAMPLE = (FIXTURES_DIR / "corpus-sample.md").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; this script is CPU-only."""
    refuse_sockets(monkeypatch)


# ---------------------------------------------------------------------------
# ST15 — reference stripping
# ---------------------------------------------------------------------------

def test_a_references_heading_in_the_tail_still_truncates():
    """The intended case: a bare `References` line ends the body."""
    stripped, method = p1.strip_references(SAMPLE)

    assert method == "header"
    assert "Journal of Nowhere" not in stripped
    assert "The survey team recorded" in stripped


def test_a_sentence_about_references_no_longer_truncates_the_paper():
    """"References to earlier work are given throughout" is not a heading.

    The mutation this kills: restoring the old
    ``^\\s*(...|References|...)\\b`` pattern, which matches this sentence and
    throws away everything after it.
    """
    text = SAMPLE.replace(
        "References\n",
        "References to earlier work are given throughout the report here.\n")

    stripped, method = p1.strip_references(text)

    assert method == "none"
    assert "Journal of Nowhere" in stripped


def test_a_markdown_references_heading_is_recognised():
    """`## References` is the shape the clean extraction actually writes."""
    text = SAMPLE.replace("References\n", "## References\n")

    _stripped, method = p1.strip_references(text)

    assert method == "header"


def test_process_paper_does_not_strip_already_clean_text():
    """A clean body.md has no references to remove, so none are removed.

    The mutation this kills: dropping the ``strip_refs`` parameter and always
    running the pre-pass, which can only take real prose off a clean body.
    """
    nlp = _fake_nlp()

    record = p1.process_paper("AAAA1111", SAMPLE, nlp, strip_refs=False)

    assert record["ref_strip_method"] == "not-attempted"
    assert record["n_chars_stripped"] == len(
        unicodedata.normalize("NFC", SAMPLE))


# ---------------------------------------------------------------------------
# ST5 / ST20 — hapax and MATTR
# ---------------------------------------------------------------------------

def test_hapax_ratio_is_computed_over_types():
    """Six tokens, four types, three hapaxes: the definition gives 0.75.

    The mutation this kills: dividing by ``len(words)`` (0.5, the old value).
    """
    words = ["a", "a", "a", "b", "c", "d"]

    assert p1.hapax_ratio(words) == 0.75
    assert p1.hapax_per_token(words) == 0.5


def test_mattr_is_none_below_one_window():
    """A text shorter than the window has no MATTR, and must not fake one.

    The mutation this kills: restoring the plain type-token fallback, which
    returns a different statistic under the same name.
    """
    assert p1.mattr_100(["word"] * 50) is None
    assert p1.mattr_100([]) is None


def test_mattr_over_a_full_window_is_the_mean_of_its_windows():
    """Hand-computed: two windows of two words, TTR 1.0 and 0.5."""
    assert p1.mattr_100(["a", "b", "b"], window=2) == 0.75


def test_a_short_record_flags_the_missing_mattr():
    """The record says WHY the number is absent, so null is not read as zero."""
    record = p1.process_paper("AAAA1111", "One short line of prose here.",
                              _fake_nlp())

    assert record["mattr_100"] is None
    assert record["mattr_100_short_text"] is True


# ---------------------------------------------------------------------------
# ST8 / ST9 — the spaCy features
# ---------------------------------------------------------------------------

def _passive_sentence(n_passive_verbs: int) -> FakeSent:
    """A scripted sentence with ``n_passive_verbs`` passive constructions."""
    tokens = [FakeToken("subject", pos="NOUN")]
    for _ in range(n_passive_verbs):
        tokens.append(FakeToken("recorded", pos="VERB"))
        tokens.append(FakeToken("was", pos="AUX", dep="auxpass"))
    sent = FakeSent(tokens)
    for index in range(1, len(tokens), 2):
        sent.link(index + 1, index)
    return sent


def _plain_sentence() -> FakeSent:
    """A scripted sentence with no passive and two nominalisations."""
    tokens = [
        FakeToken("team", pos="NOUN"),
        FakeToken("recorded", pos="VERB", dep="ROOT"),
        FakeToken("transcription", pos="NOUN", lemma="transcription"),
        FakeToken("documentation", pos="NOUN", lemma="documentation"),
    ]
    sent = FakeSent(tokens)
    sent.link(0, 1)
    sent.link(2, 1)
    sent.link(3, 1)
    return sent


def _fake_nlp() -> FakeNlp:
    """Three scripted sentences: two passive (three passive verbs), one not."""
    return FakeNlp([_passive_sentence(1), _passive_sentence(2),
                    _plain_sentence()])


def test_passive_ratio_is_presence_per_sentence_and_bounded():
    """Two of three sentences carry a passive, whatever the verb count.

    The mutation this kills: restoring ``passive_count / sent_count`` over
    qualifying VERBS, which returns 1.0 here — a "ratio" that is not a
    fraction of sentences and can exceed 1.
    """
    features = p1.spacy_features("ten words of invented prose for the "
                                 "denominator here now", _fake_nlp())

    assert features["passive_ratio"] == pytest.approx(2 / 3, abs=1e-4)
    assert features["passive_verbs_per_sentence"] == pytest.approx(1.0)


def test_the_nominalisation_rate_uses_the_alphabetic_word_count():
    """Every per-1k rate in this file must share one denominator.

    The text below has exactly ten alphabetic tokens and three punctuation
    marks; two nominalisations over ten words is 200.0/1k. The mutation this
    kills: dividing by spaCy's token count again — the scripted document has
    twelve tokens, so the rate would come back as 166.667.
    """
    text = "alpha, beta gamma delta epsilon zeta eta theta iota kappa."

    features = p1.spacy_features(text, _fake_nlp())

    assert len(p1.tokenize_words(text)) == 10
    assert features["nominalisation_count"] == 2
    assert features["nominalisation_per_1000w"] == 200.0


# ---------------------------------------------------------------------------
# ST18 / ST19 / ST21 and the segmentation rules
# ---------------------------------------------------------------------------

def test_the_sample_has_exactly_one_announcement_colon():
    """One real announcement colon, two decoys (a time and a ratio).

    The mutation this kills: dropping the ``(?<![0-9])`` guard before the
    colon, which counts "at 10:30 each morning" as an announcement.
    """
    assert len(p1._ANNOUNCE_COLON_RE.findall(SAMPLE)) == 1


def test_a_quoted_announcement_is_counted():
    """A curly opening quotation mark used to score zero (finding ST18)."""
    assert len(p1._ANNOUNCE_COLON_RE.findall(
        "The claim is simple: “Digital capture wins.”")) == 1


def test_decomposed_accents_are_normalised_before_counting():
    """The same name written two ways must not become two word types.

    The mutation this kills: dropping the NFC normalisation in
    ``process_paper`` (finding ST19).
    """
    composed = "Sobotková recorded the site. Sobotková recorded it."
    decomposed = unicodedata.normalize("NFD", composed)

    record = p1.process_paper("AAAA1111", decomposed, _fake_nlp())

    assert record["n_words"] == len(p1.tokenize_words(composed))
    assert record["hapax_ratio"] == p1.hapax_ratio(p1.tokenize_words(composed))


def test_sentences_outside_the_word_window_are_dropped():
    """The documented 5-200-word filter, and paragraph awareness with it."""
    sentences = p1.split_sentences(p1.strip_references(SAMPLE)[0])

    assert len(sentences) == 6
    assert not any(s.startswith("It rained") for s in sentences)


def test_a_sentence_never_spans_a_paragraph_break():
    """A column that ends mid-sentence must not glue onto the next paragraph."""
    text = "The first paragraph ends without a full stop here\n\n" \
           "The second paragraph starts with its own clause and continues."

    sentences = p1.split_sentences(text)

    assert len(sentences) == 2


def test_concession_is_counted_once_per_sentence():
    """One "However" in six sentences is 1/6, however many words match."""
    sentences = p1.split_sentences(p1.strip_references(SAMPLE)[0])

    assert p1.concession_rate(sentences) == 0.1667


def test_hedge_density_respects_word_boundaries():
    """"in some sensemaking" must not match the phrase "in some sense"."""
    words = p1.tokenize_words("in some sensemaking we proceed anyway")

    assert p1.hedge_density(words, "in some sensemaking we proceed anyway") == 0.0


def test_only_a_real_em_dash_counts():
    """Two hyphens are not an em-dash in PDF-extracted academic prose."""
    counters = p1.regression_counters("one — two -- three", ["one", "two"])

    assert counters["em_dash_count"] == 1


def test_a_note_that_denies_exclusion_does_not_exclude_the_paper():
    """"not excluded" excluded the paper, because the test was a substring.

    The mutation this kills: restoring ``if "exclude" in notes``.
    """
    manifest = [
        {"key": "AAAA1111", "extraction_notes": "not excluded; QA passed"},
        {"key": "BBBB2222", "extraction_notes": "EXCLUDED: unreadable scan"},
        {"key": "CCCC3333", "extraction_notes": "this excludes nothing"},
        {"key": "DDDD4444", "excluded": True, "extraction_notes": ""},
    ]

    assert p1.included_keys(manifest) == ["AAAA1111", "CCCC3333"]


# ---------------------------------------------------------------------------
# STT5 and the driver
# ---------------------------------------------------------------------------

def _install_fake_spacy(monkeypatch) -> FakeNlp:
    """Put a fake ``spacy`` module in ``sys.modules`` for ``main`` to load."""
    nlp = _fake_nlp()
    module = types.ModuleType("spacy")
    module.load = lambda name: nlp
    monkeypatch.setitem(sys.modules, "spacy", module)
    return nlp


def _corpus(tmp_path: Path, keys: list[str]) -> tuple[Path, Path]:
    """Write a clean-layout corpus and its manifest, and return both paths."""
    corpus_dir = tmp_path / "extracted"
    for key in keys:
        (corpus_dir / key).mkdir(parents=True)
        (corpus_dir / key / "body.md").write_text(SAMPLE, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"key": k} for k in keys]),
                        encoding="utf-8")
    return corpus_dir, manifest


def test_an_empty_corpus_is_a_diagnostic_not_a_statistics_error(tmp_path,
                                                                monkeypatch,
                                                                capsys):
    """No readable paper must produce an explanation and a non-zero exit.

    The mutation this kills: removing the ``if not per_paper`` guard, which
    restores ``StatisticsError`` from inside ``aggregate``'s first mean.
    """
    _install_fake_spacy(monkeypatch)
    _corpus_dir, manifest = _corpus(tmp_path, [])
    empty = tmp_path / "nothing"
    empty.mkdir()

    code = p1.main(["--corpus-dir", str(empty), "--manifest", str(manifest),
                    "--output", str(tmp_path / "out.json"), "--clean-corpus"])

    assert code == 2
    assert "No papers could be read" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()


def test_a_run_writes_results_with_provenance(tmp_path, monkeypatch):
    """The results file records the code, manifest, and model behind it."""
    _install_fake_spacy(monkeypatch)
    corpus_dir, manifest = _corpus(tmp_path, ["AAAA1111", "BBBB2222"])
    out = tmp_path / "analysis" / "phase1-results.json"

    code = p1.main(["--corpus-dir", str(corpus_dir), "--manifest",
                    str(manifest), "--output", str(out), "--clean-corpus"])

    # The run-1 regression anchors cannot hold for a two-paper synthetic
    # corpus, so a non-zero exit here is the anchor check working.
    assert code == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["per_paper"]) == 2
    assert payload["provenance"]["script"] == "phase1_pipeline.py"
    assert payload["provenance"]["inputs"][0]["sha256"]
    assert payload["provenance"]["clean_corpus"] is True


def test_dry_run_writes_no_results_file(tmp_path, monkeypatch):
    """``--dry-run`` measures and reports, and writes nothing.

    The mutation this kills: dropping ``dry_run=args.dry_run`` from the write.
    """
    _install_fake_spacy(monkeypatch)
    corpus_dir, manifest = _corpus(tmp_path, ["AAAA1111"])
    out = tmp_path / "out.json"

    p1.main(["--corpus-dir", str(corpus_dir), "--manifest", str(manifest),
             "--output", str(out), "--clean-corpus", "--dry-run"])

    assert not out.exists()


def test_a_clean_corpus_run_does_not_re_strip_references(tmp_path,
                                                         monkeypatch):
    """With --clean-corpus the pre-pass is skipped for record and stream alike.

    The mutation this kills: passing ``strip_refs=True`` regardless of the
    flag, which strips real prose off an already-clean body.
    """
    _install_fake_spacy(monkeypatch)
    corpus_dir, manifest = _corpus(tmp_path, ["AAAA1111"])
    out = tmp_path / "out.json"

    p1.main(["--corpus-dir", str(corpus_dir), "--manifest", str(manifest),
             "--output", str(out), "--clean-corpus"])

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["per_paper"][0]["ref_strip_method"] == "not-attempted"


def test_the_aggregate_survives_a_corpus_of_no_papers():
    """``aggregate([])`` reports None means rather than raising."""
    agg = p1.aggregate([], "")

    assert agg["n_papers"] == 0
    assert agg["passive_ratio_mean_of_papers"] is None
