"""
Tests for ``scripts/style-analyser/extract_corpus.py``.

The script turns a Zotero manifest plus PDFs into a per-paper bundle
(``body.md``, ``references.md``, ``metadata.json``, ``qa.json``) and a
corpus-level summary. It carried five audit findings, and this module pins
the fix for each of them:

* **STT-M7(a)** — the corpus-level summary was written to
  ``output_dir.parent``, so ``--output-dir /tmp/x/extracted`` dropped
  ``corpus-manifest.json`` in ``/tmp/x``, outside the directory the operator
  named. It now lands inside ``--output-dir``.
* **STT-M7(b)** — ``--keys`` short-circuited the EXCLUDED filter entirely, so
  naming an excluded paper silently re-extracted it into a corpus the rest of
  the pipeline treats as the agreed scope. Naming one is now refused with a
  non-zero exit code.
* **STT-M7(c)** — the module called ``sys.exit`` at *import* time when the
  upstream ``llm-reproducibility`` checkout was missing, so it could not be
  imported at all on a machine without it, and therefore had no tests. The
  import is now lazy and the failure is a catchable exception.
* **ST21** — the exclusion test was the bare substring ``"exclude" in
  notes``, which also fired on "not excluded" and "excludes nothing".
* **Cross-cutting** — every output write now goes through
  ``style_support.atomic_write_text``/``atomic_write_json`` (an interrupted
  run used to leave a truncated file the next stage read as complete), honours
  a new ``--dry-run``, and the corpus manifest carries a provenance block.

Everything here runs on the standard library. PyMuPDF and pdfplumber are not
installed in this repository's virtual environment, the corpus PDFs are
private, and the extractor is never invoked against a real document: the
pure-text stages (the split detectors, the cleanup passes, the QA thresholds,
the CLI wiring) are exercised directly with invented fixtures, and the
extractor-dependent path is exercised only through its unavailability.

Every fixture below is synthetic. No paper key, title, sentence, or number is
taken from the real corpus.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import load_style_module, refuse_sockets  # noqa: E402

extract_corpus = load_style_module("extract_corpus")

#: The script's own source, for the two structural assertions below.
SCRIPT_SOURCE = Path(extract_corpus.__file__).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; this script is CPU-only by design."""
    refuse_sockets(monkeypatch)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

#: Eight invented author-year entries, enough to trip the density fallback's
#: ``>= 8`` threshold. Surnames and years are invented.
_INVENTED_REFERENCE_TAIL = "\n".join(
    f"{surname}, {initial}. An invented entry title ({2000 + n})"
    for n, (surname, initial) in enumerate(
        [
            ("Aardvark", "Q"), ("Beetle", "R"), ("Cormorant", "S"),
            ("Dormouse", "T"), ("Egret", "U"), ("Ferret", "V"),
            ("Gannet", "W"), ("Heron", "X"),
        ]
    )
)

_INVENTED_BODY = "## Introduction\n\nThe invented survey ran for three seasons.\n"


def _manifest_entry(key: str, **overrides) -> dict:
    """One synthetic manifest entry, with a PDF path that does not exist."""
    entry = {
        "key": key,
        "pdf_path": f"/nonexistent/invented/{key}.pdf",
        "typeName": "journalArticle",
        "date": "2011",
        "title": f"An invented paper titled {key}",
        "n_words": 100,
        "has_references": True,
        "extraction_notes": "clean extraction",
    }
    entry.update(overrides)
    return entry


def _write_manifest(directory: Path, entries: list[dict]) -> Path:
    """Serialise a synthetic manifest and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return path


def _stub_extract_one(recorder: list[dict]):
    """Return a stand-in for ``extract_one`` that writes nothing.

    The real function needs PyMuPDF and a PDF; the CLI-wiring tests are about
    what ``main`` does *around* it, so it is replaced by a stub that records
    the call and reports success.
    """

    def stub(manifest_entry: dict, output_dir: Path, *, dry_run: bool = False) -> dict:
        recorder.append({"key": manifest_entry.get("key"), "dry_run": dry_run})
        return {
            "key": manifest_entry.get("key"),
            "status": "ok",
            "body_words": 120,
            "reference_words": 30,
            "split_method": "strict-heading",
            "slice_method": "none",
            "needs_review": False,
            "flags": [],
            "dry_run": dry_run,
            "outputs": [],
        }

    return stub


def _run_main(monkeypatch, argv: list[str]) -> int:
    """Invoke ``main`` with a synthetic ``sys.argv`` and return its exit code."""
    monkeypatch.setattr(sys, "argv", ["extract_corpus.py", *argv])
    return extract_corpus.main()


# ---------------------------------------------------------------------------
# STT-M7(c) — the module imports without the upstream extractor
# ---------------------------------------------------------------------------

def test_the_module_imports_on_the_standard_library_alone():
    """Importing the script must not require llm-reproducibility.

    The mutation this kills: restoring the module-level
    ``from extract_pdf_text import PDFExtractor`` / ``from pdf_cleaner import
    clean_reference_section``, which made the module unimportable — and so
    untestable — anywhere the sibling checkout is absent.
    """
    assert re.search(r"(?m)^from extract_pdf_text import", SCRIPT_SOURCE) is None
    assert re.search(r"(?m)^from pdf_cleaner import", SCRIPT_SOURCE) is None
    assert not hasattr(extract_corpus, "PDFExtractor")
    assert not hasattr(extract_corpus, "clean_reference_section")
    # The functions the rest of this file exercises are all present, so the
    # import genuinely succeeded rather than half-failing.
    assert callable(extract_corpus.split_body_references)
    assert callable(extract_corpus.main)


def test_a_missing_extractor_raises_a_catchable_error_naming_the_path(tmp_path,
                                                                     monkeypatch):
    """A missing checkout must raise, not exit the process.

    The mutation this kills: restoring the import-time
    ``sys.exit(f"FATAL: ...")``, which no caller can catch and which no test
    can survive.
    """
    absent = tmp_path / "no-such-checkout"
    monkeypatch.setattr(extract_corpus, "_LLM_REPRO_PDF", absent)

    with pytest.raises(extract_corpus.ExtractorUnavailableError) as excinfo:
        extract_corpus.load_extractor()

    assert str(absent) in str(excinfo.value)
    # RuntimeError, not SystemExit: a caller can catch and carry on.
    assert isinstance(excinfo.value, RuntimeError)
    assert not isinstance(excinfo.value, SystemExit)


def test_extract_one_surfaces_the_missing_extractor_rather_than_exiting(tmp_path,
                                                                       monkeypatch):
    """``extract_one`` reaches the lazy load only when it needs the extractor.

    The mutation this kills: moving the ``load_extractor()`` call back to
    module scope, which would turn a broken installation into an import-time
    process exit again.
    """
    monkeypatch.setattr(extract_corpus, "_LLM_REPRO_PDF", tmp_path / "absent")
    pdf = tmp_path / "invented.pdf"
    pdf.write_bytes(b"%PDF-1.4 not a real document\n")
    entry = _manifest_entry("AAAA1111", pdf_path=str(pdf))

    with pytest.raises(extract_corpus.ExtractorUnavailableError):
        extract_corpus.extract_one(entry, tmp_path / "out")


# ---------------------------------------------------------------------------
# STT-M7(a) — where the corpus manifest lands
# ---------------------------------------------------------------------------

def test_the_corpus_manifest_lands_inside_the_output_directory(tmp_path,
                                                               monkeypatch):
    """The summary must be inside ``--output-dir``, not beside it.

    The mutation this kills: restoring
    ``args.output_dir.parent / "corpus-manifest.json"``, which wrote the file
    outside the directory the operator named.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))

    code = _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir)])

    assert code == 0
    assert (output_dir / "corpus-manifest.json").is_file()
    assert not (output_dir.parent / "corpus-manifest.json").exists()


def test_the_corpus_manifest_records_the_run(tmp_path, monkeypatch):
    """The summary counts what happened, so a mislocated file is not the only tell."""
    manifest = _write_manifest(
        tmp_path / "input",
        [_manifest_entry("AAAA1111"), _manifest_entry("BBBB2222")],
    )
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))

    _run_main(monkeypatch, ["--manifest", str(manifest),
                            "--output-dir", str(output_dir)])

    written = json.loads((output_dir / "corpus-manifest.json").read_text(encoding="utf-8"))
    assert written["n_papers_extracted"] == 2
    assert written["n_errors"] == 0
    assert [r["key"] for r in written["results"]] == ["AAAA1111", "BBBB2222"]


# ---------------------------------------------------------------------------
# STT-M7(b) — --keys must not smuggle an EXCLUDED paper back in
# ---------------------------------------------------------------------------

def test_naming_an_excluded_key_is_refused_with_a_non_zero_exit(tmp_path,
                                                                monkeypatch,
                                                                capsys):
    """An excluded paper named on ``--keys`` must stop the run.

    The mutation this kills: restoring the bare
    ``entries = [e for e in manifest if e.get("key") in wanted]`` with no
    exclusion check, under which the excluded paper was silently extracted.
    """
    manifest = _write_manifest(
        tmp_path / "input",
        [
            _manifest_entry("AAAA1111"),
            _manifest_entry("BBBB2222", extraction_notes="EXCLUDED: no text layer"),
        ],
    )
    output_dir = tmp_path / "out" / "extracted"
    calls: list[dict] = []
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one(calls))

    code = _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir),
                                   "--keys", "AAAA1111,BBBB2222"])

    assert code != 0
    assert code != 2, "matched-but-excluded must be distinguishable from matched-nothing"
    assert "BBBB2222" in capsys.readouterr().err
    # Nothing ran and nothing was written: the refusal is before the loop.
    assert calls == []
    assert not output_dir.exists()


def test_include_excluded_lets_the_same_key_through(tmp_path, monkeypatch):
    """The refusal is an opt-in gate, not a ban.

    The mutation this kills: dropping the ``if not args.include_excluded``
    guard, which would make the excluded set unreachable altogether.
    """
    manifest = _write_manifest(
        tmp_path / "input",
        [_manifest_entry("BBBB2222", extraction_notes="EXCLUDED: no text layer")],
    )
    output_dir = tmp_path / "out" / "extracted"
    calls: list[dict] = []
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one(calls))

    code = _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir),
                                   "--keys", "BBBB2222", "--include-excluded"])

    assert code == 0
    assert [c["key"] for c in calls] == ["BBBB2222"]


def test_an_included_key_is_not_refused(tmp_path, monkeypatch):
    """The gate must not reject ordinary keys; a blanket refusal would pass
    the test above while breaking every real run.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_dir = tmp_path / "out" / "extracted"
    calls: list[dict] = []
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one(calls))

    code = _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir),
                                   "--keys", "AAAA1111"])

    assert code == 0
    assert [c["key"] for c in calls] == ["AAAA1111"]


def test_keys_matching_nothing_still_exits_2(tmp_path, monkeypatch, capsys):
    """The pre-existing "matched no entries" contract survives the new gate.

    The mutation this kills: replacing the ``return 2`` with the new
    exclusion return code, which would erase the distinction an operator
    script needs.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))

    code = _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir),
                                   "--keys", "ZZZZ9999"])

    assert code == 2
    assert "matched no manifest entries" in capsys.readouterr().err


def test_the_default_run_still_drops_excluded_entries(tmp_path, monkeypatch):
    """With no ``--keys``, EXCLUDED entries stay out as they always did."""
    manifest = _write_manifest(
        tmp_path / "input",
        [
            _manifest_entry("AAAA1111"),
            _manifest_entry("BBBB2222", extraction_notes="EXCLUDED: no text layer"),
        ],
    )
    output_dir = tmp_path / "out" / "extracted"
    calls: list[dict] = []
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one(calls))

    _run_main(monkeypatch, ["--manifest", str(manifest),
                            "--output-dir", str(output_dir)])

    assert [c["key"] for c in calls] == ["AAAA1111"]


# ---------------------------------------------------------------------------
# ST21 — what counts as "EXCLUDED"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "notes",
    [
        "EXCLUDED: scanned image, no text layer",
        "Excluded pending a rescan",
        "excluded from the analysis set",
    ],
)
def test_a_genuine_exclusion_note_still_excludes(notes):
    """The predicate must keep doing its job, case-insensitively.

    The mutation this kills: narrowing the match to the exact upper-case
    literal ``"EXCLUDED"``, which would silently re-admit every paper whose
    note was written in sentence case.
    """
    assert extract_corpus.is_excluded({"key": "AAAA1111", "extraction_notes": notes}) is True


@pytest.mark.parametrize(
    "notes",
    [
        "Reviewed 2026-01-02; not excluded from analysis",
        "no longer excluded after the rescan",
        "This filter excludes nothing at all",
        "an exclusionary heading style, kept anyway",
        "clean extraction",
        "",
    ],
)
def test_a_note_that_is_not_an_exclusion_does_not_exclude(notes):
    """"not excluded" and "excludes nothing" must not drop a good paper.

    The mutation this kills: restoring ``"exclude" in notes.lower()``, the
    bare substring test that dropped papers whose notes said the opposite.
    """
    assert extract_corpus.is_excluded({"key": "AAAA1111", "extraction_notes": notes}) is False


def test_an_explicit_boolean_flag_beats_the_prose():
    """A manifest that states the fact outright is believed over its notes.

    The mutation this kills: deleting the ``entry.get("excluded")`` branch,
    which would leave the decision to prose parsing even where the manifest
    had said so explicitly.
    """
    assert extract_corpus.is_excluded(
        {"key": "AAAA1111", "excluded": True, "extraction_notes": "clean extraction"}
    ) is True
    assert extract_corpus.is_excluded(
        {"key": "AAAA1111", "excluded": False, "extraction_notes": "EXCLUDED: stale note"}
    ) is False


def test_an_entry_with_no_signal_at_all_is_included():
    """A bare entry defaults to being part of the corpus."""
    assert extract_corpus.is_excluded({"key": "AAAA1111"}) is False


# ---------------------------------------------------------------------------
# Cross-cutting — atomic writes
# ---------------------------------------------------------------------------

def test_no_output_is_written_with_a_plain_write_text():
    """Every output must go through the atomic helper.

    An interrupted ``Path.write_text`` leaves a truncated ``body.md`` or
    ``metadata.json`` that the next pipeline stage parses as complete. The
    mutation this kills: reinstating any ``(path).write_text(...)`` call in
    the script.
    """
    assert ".write_text(" not in SCRIPT_SOURCE
    assert ".write_bytes(" not in SCRIPT_SOURCE
    assert "atomic_write_text" in SCRIPT_SOURCE
    assert "atomic_write_json" in SCRIPT_SOURCE


def test_the_corpus_manifest_goes_through_the_atomic_json_writer(tmp_path,
                                                                 monkeypatch):
    """``main``'s own write is atomic too, not only the per-paper ones.

    The mutation this kills: leaving ``main`` on ``json.dumps`` +
    ``write_text`` while the per-paper writes were converted.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))
    seen: list[Path] = []
    real_writer = extract_corpus.atomic_write_json

    def spy(path, payload, **kwargs):
        """Record the destination, then perform the real atomic write."""
        seen.append(Path(path))
        return real_writer(path, payload, **kwargs)

    monkeypatch.setattr(extract_corpus, "atomic_write_json", spy)

    _run_main(monkeypatch, ["--manifest", str(manifest),
                            "--output-dir", str(output_dir)])

    assert seen == [output_dir / "corpus-manifest.json"]


# ---------------------------------------------------------------------------
# Cross-cutting — --dry-run
# ---------------------------------------------------------------------------

def test_dry_run_creates_no_file_anywhere(tmp_path, monkeypatch, capsys):
    """``--dry-run`` must leave the output tree byte-for-byte untouched.

    The mutation this kills: dropping ``dry_run=args.dry_run`` from the
    corpus-manifest write (or from ``output_dir.mkdir``), under which a dry
    run against a production path would overwrite the real summary.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_root = tmp_path / "out"
    output_dir = output_root / "extracted"
    calls: list[dict] = []
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one(calls))

    code = _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir), "--dry-run"])

    assert code == 0
    assert calls == [{"key": "AAAA1111", "dry_run": True}]
    # Zero files created: the only file under tmp_path is the input manifest.
    created = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert created == [manifest]
    assert not output_root.exists()
    assert "dry-run" in capsys.readouterr().out


def test_dry_run_reports_the_destination_it_did_not_write(tmp_path, monkeypatch,
                                                          capsys):
    """A dry run has to say what a real run would have produced.

    The mutation this kills: making ``--dry-run`` a silent no-op, which
    would give the operator no way to check the plan.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))

    _run_main(monkeypatch, ["--manifest", str(manifest),
                            "--output-dir", str(output_dir), "--dry-run"])

    assert str(output_dir / "corpus-manifest.json") in capsys.readouterr().out


def test_extract_one_dry_run_writes_no_error_file(tmp_path):
    """Even the failure path must write nothing under ``--dry-run``.

    ``extract_one`` records a missing PDF by writing ``extraction-error.txt``.
    The mutation this kills: leaving that one write on a plain ``write_text``
    while the success-path writes were converted.
    """
    output_dir = tmp_path / "out"
    entry = _manifest_entry("AAAA1111")

    result = extract_corpus.extract_one(entry, output_dir, dry_run=True)

    assert result["status"] == "error"
    assert result["outputs"] == [str(output_dir / "AAAA1111" / "extraction-error.txt")]
    assert not output_dir.exists()


def test_extract_one_records_a_missing_pdf_when_not_dry_running(tmp_path):
    """The same path really does write the error file on a live run."""
    output_dir = tmp_path / "out"

    result = extract_corpus.extract_one(_manifest_entry("AAAA1111"), output_dir)

    assert result["status"] == "error"
    error_file = output_dir / "AAAA1111" / "extraction-error.txt"
    assert "PDF not found" in error_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Cross-cutting — provenance
# ---------------------------------------------------------------------------

def test_the_corpus_manifest_carries_a_provenance_block(tmp_path, monkeypatch):
    """The summary must name the script, the input bytes, and the extractors.

    The mutation this kills: deleting the ``provenance`` key, which would
    leave a results file that cannot be tied back to the code and inputs that
    made it.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))

    _run_main(monkeypatch, ["--manifest", str(manifest),
                            "--output-dir", str(output_dir)])

    written = json.loads((output_dir / "corpus-manifest.json").read_text(encoding="utf-8"))
    provenance = written["provenance"]
    assert provenance["script"] == "extract_corpus.py"
    assert provenance["inputs"] == [
        {
            "path": str(manifest),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        }
    ]
    assert set(provenance["extractor_versions"]) == {"pymupdf", "pdfplumber"}


def test_the_provenance_block_has_no_wall_clock_field(tmp_path, monkeypatch):
    """Provenance stays byte-identical across runs, so re-runs can be diffed.

    ``generated_at_utc`` remains a sibling field for anyone who wants the
    wall clock. The mutation this kills: folding a timestamp into the
    provenance block itself.
    """
    manifest = _write_manifest(tmp_path / "input", [_manifest_entry("AAAA1111")])
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))

    _run_main(monkeypatch, ["--manifest", str(manifest),
                            "--output-dir", str(output_dir)])

    provenance = json.loads(
        (output_dir / "corpus-manifest.json").read_text(encoding="utf-8")
    )["provenance"]
    assert not [k for k in provenance if "time" in k or "date" in k or "_at" in k]


# ---------------------------------------------------------------------------
# main's exit code
# ---------------------------------------------------------------------------

def test_main_returns_1_when_any_entry_errored(tmp_path, monkeypatch):
    """One bad paper must make the whole run report failure.

    The mutation this kills: returning 0 unconditionally, which would let a
    scripted pipeline carry on over a corpus that is missing a paper.
    """
    manifest = _write_manifest(
        tmp_path / "input",
        [_manifest_entry("AAAA1111"), _manifest_entry("BBBB2222")],
    )
    output_dir = tmp_path / "out" / "extracted"

    def half_failing(manifest_entry, output_dir_arg, *, dry_run=False):
        """Succeed for the first key, fail for the second."""
        if manifest_entry["key"] == "AAAA1111":
            return _stub_extract_one([])(manifest_entry, output_dir_arg, dry_run=dry_run)
        return {"key": manifest_entry["key"], "status": "error",
                "error": "invented failure", "outputs": []}

    monkeypatch.setattr(extract_corpus, "extract_one", half_failing)

    assert _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir)]) == 1


def test_main_returns_0_when_every_entry_succeeded(tmp_path, monkeypatch):
    """The converse: a clean run must not report failure."""
    manifest = _write_manifest(
        tmp_path / "input",
        [_manifest_entry("AAAA1111"), _manifest_entry("BBBB2222")],
    )
    output_dir = tmp_path / "out" / "extracted"
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one([]))

    assert _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir)]) == 0


def test_an_entry_without_a_key_is_an_error_not_a_crash(tmp_path, monkeypatch):
    """A malformed manifest row is recorded and the run continues."""
    manifest = _write_manifest(
        tmp_path / "input", [{"pdf_path": "/nonexistent/invented/nokey.pdf"}]
    )
    output_dir = tmp_path / "out" / "extracted"
    calls: list[dict] = []
    monkeypatch.setattr(extract_corpus, "extract_one", _stub_extract_one(calls))

    code = _run_main(monkeypatch, ["--manifest", str(manifest),
                                   "--output-dir", str(output_dir)])

    assert code == 1
    assert calls == []


# ---------------------------------------------------------------------------
# Body / references split — the five detectors, in order, plus the fallback
# ---------------------------------------------------------------------------

def test_the_strict_heading_detector_fires_first():
    """An explicit ``## References`` heading is the cleanest split.

    The mutation this kills: deleting the strict pattern, which would leave
    the looser detectors to guess at a structure that is right there.
    """
    markdown = _INVENTED_BODY + "\n## References\n\nAardvark, Q. (2011). A title.\n"

    body, references, method = extract_corpus.split_body_references(markdown)

    assert method == "strict-heading"
    assert "## References" not in body
    assert references.startswith("## References")


def test_the_loose_heading_detector_catches_a_qualified_heading():
    """"References and further reading" is still a references heading.

    The mutation this kills: removing the loose fallback, under which such a
    paper's whole bibliography would be counted as body prose.
    """
    markdown = _INVENTED_BODY + "\n## References and further reading\n\nAardvark, Q. (2011).\n"

    body, references, method = extract_corpus.split_body_references(markdown)

    assert method == "loose-heading"
    assert "further reading" not in body
    assert references.startswith("## References and further reading")


def test_the_paragraph_prefix_detector_catches_an_unpromoted_heading():
    """"References Aardvark, Q. …" — the heading fused to the first entry.

    The mutation this kills: dropping the paragraph-prefix detector, which
    handles the case where the upstream section detector failed to promote
    the heading to its own line.
    """
    markdown = _INVENTED_BODY + "\nReferences Aardvark, Q. (2011). A title.\n"

    body, references, method = extract_corpus.split_body_references(markdown)

    assert method == "paragraph-prefix"
    assert "Aardvark" not in body
    assert references.startswith("References Aardvark")


def test_the_paragraph_prefix_detector_ignores_ordinary_prose():
    """"References to earlier work…" is prose, not a bibliography.

    The mutation this kills: widening the lookahead so the detector fires on
    any capitalised word after "References", which would amputate the body
    at a sentence.
    """
    markdown = (
        "## Introduction\n\nReferences IN this section are indicative only.\n"
        "The invented survey ran for three seasons.\n"
    )

    _, references, method = extract_corpus.split_body_references(markdown)

    assert method == "no-references-heading-found"
    assert references == ""


def test_the_bracketed_numbered_detector_catches_a_headingless_list():
    """A ``[1] … [2] …`` list with no heading at all is still references.

    The mutation this kills: requiring only ``[1]``, which would fire on an
    in-text citation such as "as shown in [1]".
    """
    markdown = (
        _INVENTED_BODY
        + "\n[1] Aardvark, Q. An invented title (2011)\n"
        + "[2] Beetle, R. Another invented title (2012)\n"
    )

    body, references, method = extract_corpus.split_body_references(markdown)

    assert method == "bracketed-numbered"
    assert "[1]" not in body
    assert references.startswith("[1] Aardvark")


def test_a_single_bracketed_citation_in_prose_is_not_a_reference_list():
    """One ``[1]`` with no ``[2]`` after it must not trigger the detector."""
    markdown = "## Introduction\n\nAs the invented method [1] shows, the survey held.\n"

    _, _, method = extract_corpus.split_body_references(markdown)

    assert method == "no-references-heading-found"


def test_the_end_marker_density_detector_is_the_last_resort():
    """An end-of-body marker plus a dense author-year run splits the paper.

    The mutation this kills: dropping the ``>= 8`` density requirement, which
    would let in-body citation clusters masquerade as a bibliography.
    """
    markdown = (
        _INVENTED_BODY
        + "\n## Funding\n\nSupported by an invented grant.\n\n"
        + _INVENTED_REFERENCE_TAIL
        + "\n"
    )

    body, references, method = extract_corpus.split_body_references(markdown)

    assert method == "end-marker-author-year-density"
    assert "## Funding" in body, "the marker itself belongs to the body"
    assert references.startswith("Aardvark, Q. An invented entry title (2000)")


def test_a_thin_author_year_tail_does_not_trigger_the_density_detector():
    """Fewer than eight entries after the marker is not a bibliography.

    The mutation this kills: lowering the density threshold to a value a
    normal acknowledgements paragraph can reach.
    """
    thin = "\n".join(_INVENTED_REFERENCE_TAIL.split("\n")[:7])
    markdown = _INVENTED_BODY + "\n## Funding\n\nSupported by a grant.\n\n" + thin + "\n"

    _, references, method = extract_corpus.split_body_references(markdown)

    assert method == "no-references-heading-found"
    assert references == ""


def test_the_fallback_keeps_the_whole_document_as_body():
    """With no detector firing, nothing is thrown away.

    The mutation this kills: returning an empty body when no split is found,
    which would silently zero out a paper's metrics.
    """
    markdown = "## Introduction\n\nThe invented survey ran for three seasons.\n"

    body, references, method = extract_corpus.split_body_references(markdown)

    assert method == "no-references-heading-found"
    assert body == markdown.strip()
    assert references == ""


def test_the_last_references_heading_wins_not_the_first():
    """Papers mentioning references early must still split at the real section.

    The mutation this kills: using ``matches[0]`` instead of ``matches[-1]``,
    which would cut the body at the first mention and discard most of it.
    """
    markdown = (
        "## References\n\nSee the appendix.\n\n"
        "## Discussion\n\nThe invented survey held up.\n\n"
        "## References\n\nAardvark, Q. (2011). A title.\n"
    )

    body, references, method = extract_corpus.split_body_references(markdown)

    assert method == "strict-heading"
    assert "## Discussion" in body
    assert references.count("## References") == 1


# ---------------------------------------------------------------------------
# strip_running_headers — the occurrence and length thresholds
# ---------------------------------------------------------------------------

def _document_with_repeats(line: str, times: int) -> str:
    """A synthetic document in which ``line`` recurs ``times`` times."""
    parts = []
    for index in range(times):
        parts.append(line)
        parts.append(f"Invented paragraph number {index} of the running text.")
    return "\n".join(parts) + "\n"


def test_a_line_repeated_exactly_min_occurrences_is_stripped():
    """The threshold is inclusive: four repeats is boilerplate.

    The mutation this kills: changing ``c >= min_occurrences`` to ``c >``,
    which would leave every four-page paper's running header in the body.
    """
    header = "Journal of Invented Studies"
    markdown = _document_with_repeats(header, 4)

    cleaned, stripped = extract_corpus.strip_running_headers(markdown)

    assert stripped == 4
    assert header not in cleaned


def test_a_line_one_short_of_the_threshold_survives():
    """Three repeats is not yet boilerplate, so the text is returned intact.

    The mutation this kills: changing the comparison to ``>=`` on a
    decremented threshold, which would start eating genuine repeated prose.
    """
    header = "Journal of Invented Studies"
    markdown = _document_with_repeats(header, 3)

    cleaned, stripped = extract_corpus.strip_running_headers(markdown)

    assert stripped == 0
    assert cleaned == markdown


def test_a_line_of_exactly_min_chars_is_long_enough_to_strip():
    """Fifteen characters is inclusive on the length threshold too."""
    header = "Running Head AB"
    assert len(header) == 15

    _, stripped = extract_corpus.strip_running_headers(_document_with_repeats(header, 4))

    assert stripped == 4


def test_a_line_one_character_too_short_is_kept():
    """Short repeated lines are section headings, not boilerplate.

    The mutation this kills: dropping the ``len(key) >= min_chars`` guard,
    which would delete every legitimately repeated short heading.
    """
    header = "Running Head A"
    assert len(header) == 14

    cleaned, stripped = extract_corpus.strip_running_headers(
        _document_with_repeats(header, 4)
    )

    assert stripped == 0
    assert header in cleaned


def test_a_hash_promoted_running_header_is_stripped_too():
    """The comparison normalises away heading markers before counting.

    The mutation this kills: dropping the ``lstrip("#")`` in ``normalise``,
    under which an H2-promoted running header would survive.
    """
    header = "Journal of Invented Studies"
    markdown = _document_with_repeats(f"## {header}", 4)

    cleaned, stripped = extract_corpus.strip_running_headers(markdown)

    assert stripped == 4
    assert header not in cleaned


# ---------------------------------------------------------------------------
# apply_manifest_overrides
# ---------------------------------------------------------------------------

def test_an_override_replaces_the_manifest_field(monkeypatch):
    """A per-key correction wins over what the manifest said.

    The mutation this kills: reversing the merge order to
    ``{**PER_KEY_MANIFEST_OVERRIDES[key], **entry}``, under which the
    manifest's wrong value would win and the override would do nothing.
    """
    monkeypatch.setitem(
        extract_corpus.PER_KEY_MANIFEST_OVERRIDES, "AAAA1111", {"has_references": False}
    )
    entry = _manifest_entry("AAAA1111", has_references=True)

    merged = extract_corpus.apply_manifest_overrides(entry)

    assert merged["has_references"] is False
    assert merged["title"] == entry["title"], "unrelated fields are carried through"


def test_an_override_does_not_mutate_the_caller_s_entry(monkeypatch):
    """The manifest loaded from disk stays the record of what Zotero said."""
    monkeypatch.setitem(
        extract_corpus.PER_KEY_MANIFEST_OVERRIDES, "AAAA1111", {"has_references": False}
    )
    entry = _manifest_entry("AAAA1111", has_references=True)

    extract_corpus.apply_manifest_overrides(entry)

    assert entry["has_references"] is True


def test_an_unlisted_key_passes_through_untouched():
    """Keys with no override are returned as they arrived."""
    entry = _manifest_entry("ZZZZ9999")

    assert extract_corpus.apply_manifest_overrides(entry) == entry


# ---------------------------------------------------------------------------
# apply_chapter_slice — the fail-open guard
# ---------------------------------------------------------------------------

def _install_slice_rule(monkeypatch) -> None:
    """Register a synthetic chapter-slice rule for key ``AAAA1111``."""
    monkeypatch.setitem(
        extract_corpus.CHAPTER_SLICE_RULES,
        "AAAA1111",
        (
            re.compile(r"^##\s+An Invented Chapter.*$", re.MULTILINE),
            re.compile(r"^##\s+Invented Next Author.*$", re.MULTILINE),
        ),
    )


def test_the_chapter_slice_uses_the_last_start_match_not_the_table_of_contents(
        monkeypatch):
    """The first occurrence of a chapter title is its TOC entry.

    The mutation this kills: using ``starts[0]``, which would keep the whole
    volume from the table of contents onwards.
    """
    _install_slice_rule(monkeypatch)
    markdown = (
        "## An Invented Chapter\n\n(table of contents entry)\n\n"
        "## An Invented Chapter\n\nThe chapter body proper.\n\n"
        "## Invented Next Author\n\nThe following chapter.\n"
    )

    sliced, method = extract_corpus.apply_chapter_slice("AAAA1111", markdown)

    assert method == "chapter-slice-applied"
    assert "The chapter body proper." in sliced
    assert "table of contents entry" not in sliced
    assert "The following chapter." not in sliced


def test_a_missing_slice_end_fails_open_to_the_full_document(monkeypatch):
    """Without an end boundary the slice returns everything, and says so.

    The mutation this kills: truncating to ``markdown[start:]``, which would
    silently bundle the next chapter and the volume bibliography into the
    body.
    """
    _install_slice_rule(monkeypatch)
    markdown = "## An Invented Chapter\n\nThe chapter body proper, with no end marker.\n"

    sliced, method = extract_corpus.apply_chapter_slice("AAAA1111", markdown)

    assert method == "chapter-slice-end-not-found"
    assert sliced == markdown


def test_a_key_with_no_rule_is_returned_untouched():
    """Most papers have no slice rule and must not be altered."""
    markdown = _INVENTED_BODY

    assert extract_corpus.apply_chapter_slice("ZZZZ9999", markdown) == (markdown, "none")


# ---------------------------------------------------------------------------
# compute_qa_flags — every flag at its threshold
# ---------------------------------------------------------------------------

def _words(count: int) -> str:
    """A body of exactly ``count`` countable words, with no digits in them."""
    return " ".join(["alpha"] * count)


def _qa(body: str, references: str, split_method: str = "strict-heading",
        *, sections: int = 5, n_words: int = 100, has_references: bool = True) -> dict:
    """Run ``compute_qa_flags`` over synthetic inputs."""
    return extract_corpus.compute_qa_flags(
        body,
        references,
        split_method,
        {"pages": 10, "sections_detected": sections, "tables_found": 0},
        {"key": "AAAA1111", "n_words": n_words, "has_references": has_references},
    )


def test_references_split_failed_fires_when_references_were_expected():
    """A failed split on a paper that has references is a real problem.

    The mutation this kills: dropping the ``split_method`` test, which would
    stop reporting the failure the whole detector chain exists to avoid.
    """
    flags = _qa(_words(100), "", "no-references-heading-found")["flags"]

    assert "references_split_failed" in flags


def test_expects_refs_false_suppresses_the_split_failure_flag():
    """A chapter whose bibliography lives elsewhere must not be flagged.

    The mutation this kills: removing the ``expects_refs`` guard, which
    reinstates a false positive on every paper with no references section of
    its own.
    """
    flags = _qa(
        _words(100), "", "no-references-heading-found", has_references=False
    )["flags"]

    assert "references_split_failed" not in flags
    assert "zero_reference_words" not in flags
    assert flags == []


def test_zero_reference_words_fires_when_references_were_expected():
    """An empty references file on a paper that should have one is flagged."""
    flags = _qa(_words(100), "", "strict-heading")["flags"]

    assert "zero_reference_words" in flags


def test_zero_body_words_is_always_flagged():
    """An empty body is a failure whatever the manifest said.

    The mutation this kills: putting the body check behind ``expects_refs``
    along with the references checks.
    """
    flags = _qa("", _words(1), n_words=1, has_references=True)["flags"]

    assert "zero_body_words" in flags


def test_the_word_count_delta_at_exactly_25_percent_is_not_flagged():
    """The delta threshold is strict: 25% is inside tolerance.

    The mutation this kills: changing ``abs(delta_pct) > 25`` to ``>=``,
    which would flag a paper sitting exactly on the agreed boundary.
    """
    qa = _qa(_words(120), _words(5), n_words=100)

    assert qa["word_count_delta_pct"] == 25.0
    assert not [f for f in qa["flags"] if f.startswith("word_count_delta")]


def test_the_word_count_delta_one_point_past_the_threshold_is_flagged():
    """One percentage point further out does fire, and names the delta."""
    qa = _qa(_words(121), _words(5), n_words=100)

    assert qa["word_count_delta_pct"] == 26.0
    assert "word_count_delta_+26pct" in qa["flags"]


def test_a_large_negative_delta_is_flagged_too():
    """Under-extraction matters as much as over-extraction.

    The mutation this kills: dropping the ``abs()``, which would let a paper
    that lost half its text through unflagged.
    """
    qa = _qa(_words(40), _words(5), n_words=100)

    assert "word_count_delta_-55pct" in qa["flags"]


def test_a_manifest_with_no_word_count_does_not_divide_by_zero():
    """A missing ``n_words`` yields a zero delta rather than an exception."""
    qa = _qa(_words(100), _words(5), n_words=0)

    assert qa["word_count_delta_pct"] == 0.0


def test_few_sections_detected_fires_below_three_but_not_at_three():
    """The section threshold is ``< 3``, inclusive of three as acceptable.

    The mutation this kills: changing ``< 3`` to ``<= 3``, which would flag
    every three-section paper for review.
    """
    at_threshold = _qa(_words(100), _words(5), sections=3)["flags"]
    below_threshold = _qa(_words(100), _words(5), sections=2)["flags"]

    assert "few_sections_detected" not in at_threshold
    assert "few_sections_detected" in below_threshold


def test_an_unpromoted_abstract_is_flagged():
    """"Abstract" in the opening text without an ``## Abstract`` heading.

    The mutation this kills: dropping the ``"## Abstract" not in body_md``
    half of the test, which would flag every paper whose abstract WAS
    promoted correctly.
    """
    unpromoted = "Abstract\n\n" + _words(100)
    promoted = "## Abstract\n\n" + _words(100)

    assert "abstract_present_but_not_promoted" in _qa(unpromoted, _words(5))["flags"]
    assert "abstract_present_but_not_promoted" not in _qa(promoted, _words(5))["flags"]


def test_needs_review_mirrors_the_flag_list():
    """``needs_review`` is exactly "did anything fire".

    The mutation this kills: hard-coding ``needs_review`` to False, which
    would hide every flag from the downstream QA sweep.
    """
    clean = _qa(_words(100), _words(5))
    dirty = _qa(_words(100), _words(5), sections=1)

    assert clean["flags"] == [] and clean["needs_review"] is False
    assert dirty["flags"] and dirty["needs_review"] is True


def test_the_word_counter_counts_non_ascii_names_as_words():
    """The corpus is archaeological; diacritics and Greek must count.

    The mutation this kills: replacing the Unicode-aware pattern with
    ``\\w+`` restricted to ASCII, which would under-count every paper citing
    a non-English name and skew the delta flag.
    """
    qa = _qa("Müller Sobotková Çatalhöyük ἀρχαῖος", "", n_words=4,
             has_references=False)

    assert qa["body_words"] == 4
