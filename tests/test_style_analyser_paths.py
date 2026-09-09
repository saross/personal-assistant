"""
Path defaults in ``scripts/style-analyser/``.

Narrow by design: this module pins only where the phase scripts look for
their inputs and put their outputs. Their analysis logic is not audited here.

The defaults used to be RELATIVE — ``Path("data/style-corpus/…")`` — while the
documented invocation (``agents/corpus-style-analyser-v2.md``) gives each
script an absolute path and never changes directory first. Run from anywhere
but the repository root, the scripts either failed to find their input or
wrote their output into whatever tree the shell happened to be sitting in.

``phase5_evaluator`` cannot be imported here (it pulls in numpy and spaCy
from a different virtual environment), so every module is checked
statically and the importable ones are checked again at runtime.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STYLE_DIR = PROJECT_ROOT / "scripts" / "style-analyser"
STYLE_CORPUS = PROJECT_ROOT / "data" / "style-corpus"

#: module filename -> the path constants that must not be relative.
PATH_CONSTANTS: dict[str, tuple[str, ...]] = {
    "phase3_promotion.py": ("PHASE1", "OUT"),
    "phase4_exemplar_scorer.py": ("CORPUS", "OUT"),
    "phase3_guide_verifier.py": ("PHASE1_DEFAULT", "PHASE3_DEFAULT"),
    "phase5_evaluator.py": ("PHASE1_DEFAULT", "PHASE3_DEFAULT", "EXTRACTED_DEFAULT"),
}


@pytest.fixture(autouse=True)
def refuse_sockets(monkeypatch):
    """Fail loudly if any test in this module opens a socket."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a style-analyser path test opened a network socket; these "
            "scripts make no external calls at all."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _module_level_assignments(path: Path) -> dict[str, str]:
    """Map each module-level constant name to its assigned source text."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = ast.get_source_segment(source, node.value) or ""
    return found


@pytest.mark.parametrize(
    "filename,constants", sorted((name, names) for name, names in PATH_CONSTANTS.items())
)
def test_path_defaults_are_not_relative(filename, constants):
    """The finding: a bare relative Path made every default cwd-dependent."""
    assignments = _module_level_assignments(STYLE_DIR / filename)
    for constant in constants:
        assert constant in assignments, f"{filename} no longer defines {constant}"
        expression = assignments[constant]
        assert "PA_ROOT" in expression, (
            f"{filename}:{constant} is {expression!r}; it must be derived from "
            "the __file__-based PA_ROOT, not resolved against the working "
            "directory"
        )


def test_pa_root_resolves_to_the_repository_root():
    """PA_ROOT must climb exactly two levels out of scripts/style-analyser/."""
    assignments = _module_level_assignments(STYLE_DIR / "phase3_promotion.py")
    assert assignments["PA_ROOT"] == "Path(__file__).resolve().parents[2]"


@pytest.mark.parametrize(
    "filename",
    ["phase3_promotion.py", "phase4_exemplar_scorer.py", "phase3_guide_verifier.py"],
)
def test_importable_modules_expose_absolute_defaults(filename):
    """Runtime check on the modules whose dependencies are in this venv."""
    module_name = f"style_analyser_{filename[:-3]}"
    spec = importlib.util.spec_from_file_location(module_name, STYLE_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    for constant in PATH_CONSTANTS[filename]:
        value = getattr(module, constant)
        assert value.is_absolute()
        assert value.parent == STYLE_CORPUS


@pytest.mark.parametrize(
    "filename,flag",
    [
        ("phase3_promotion.py", "--phase1"),
        ("phase3_promotion.py", "--out"),
        ("phase4_exemplar_scorer.py", "--corpus"),
        ("phase4_exemplar_scorer.py", "--out"),
    ],
)
def test_the_new_defaults_are_overridable(filename, flag):
    """A default is only safe if the caller can replace it."""
    source = (STYLE_DIR / filename).read_text(encoding="utf-8")
    assert f'"{flag}"' in source


# ---------------------------------------------------------------------------
# The overrides must actually be used
# ---------------------------------------------------------------------------


def _load(filename: str):
    """Import one style-analyser module under a private name."""
    module_name = f"style_analyser_override_{filename[:-3]}"
    spec = importlib.util.spec_from_file_location(module_name, STYLE_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _phase1_fixture(path: Path) -> Path:
    """Write a minimal, invented Phase 1 results JSON.

    The payload carries the metric-definition stamp every phase 1 consumer
    now requires (audit round 4g-2, item 4): four metrics changed meaning
    under names that stayed the same, so a results file measured with the old
    definitions looks identical to one measured with the new, and a consumer
    comparing the two silently produces a number with no meaning.
    ``phase3_promotion`` therefore refuses an unstamped file with exit 2 —
    which is what these override tests were tripping over.

    The stamp comes from the same helper phase 1 itself writes, rather than a
    literal version number, so a future bump reaches this fixture without
    anybody having to remember it.
    """
    per_paper = [
        {
            "key": f"INVENTED{index}",
            "mattr_100": 0.70 + index / 100,
            "hapax_ratio": 0.40,
            "sentence_stats": {"mean": 21.4, "median": 20.0},
            "paragraph_stats": {"mean": 30.0, "median": 17.0},
            "regression": {
                "semicolon_per_1k": 6.5,
                "uk_us_counts": {"analyse": 3},
            },
        }
        for index in range(3)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "metric_schema": _load("style_support.py").metric_schema_stamp(),
            "per_paper": per_paper,
            "aggregate": {
                "regression": {
                    "semicolon_count": 40,
                    "uk_us_counts": {"analyse": 9, "analyze": 0},
                }
            },
        }),
        encoding="utf-8",
    )
    return path


def _corpus_fixture(root: Path) -> Path:
    """Write a minimal, invented extracted-corpus bundle."""
    paper = root / "INVENTED1"
    paper.mkdir(parents=True)
    (paper / "metadata.json").write_text(
        json.dumps({"zotero": {"date": "2021-05", "role": "first"}}),
        encoding="utf-8",
    )
    (paper / "body.md").write_text(
        "The Thornhollow terrace sequence was recorded in detail; the survey "
        "team walked the grid at twenty-metre intervals, and the ceramic "
        "scatter was bagged by collection unit for later analysis of the "
        "invented fabric groups.\n",
        encoding="utf-8",
    )
    return root


class TestPhase3PromotionOverrides:
    """``--phase1`` and ``--out`` must beat the module defaults."""

    def test_out_override_wins_and_the_default_is_untouched(self, tmp_path, monkeypatch, capsys):
        module = _load("phase3_promotion.py")
        sentinel = tmp_path / "default-must-not-be-written.json"
        monkeypatch.setattr(module, "OUT", sentinel)
        monkeypatch.setattr(module, "PHASE1", tmp_path / "default-phase1.json")
        chosen = tmp_path / "chosen-out.json"
        assert module.main([
            "--phase1", str(_phase1_fixture(tmp_path / "phase1.json")),
            "--out", str(chosen),
        ]) == 0
        capsys.readouterr()
        assert chosen.exists()
        assert not sentinel.exists()

    def test_phase1_override_is_the_path_that_is_read(self, tmp_path, monkeypatch, capsys):
        module = _load("phase3_promotion.py")
        monkeypatch.setattr(module, "PHASE1", _phase1_fixture(tmp_path / "default.json"))
        missing = tmp_path / "chosen-but-absent.json"
        assert module.main(["--phase1", str(missing)]) == 2
        assert str(missing) in capsys.readouterr().err

    def test_the_written_file_records_the_input_it_used(self, tmp_path, monkeypatch, capsys):
        module = _load("phase3_promotion.py")
        monkeypatch.setattr(module, "OUT", tmp_path / "unused.json")
        phase1 = _phase1_fixture(tmp_path / "phase1.json")
        out = tmp_path / "out.json"
        assert module.main(["--phase1", str(phase1), "--out", str(out)]) == 0
        capsys.readouterr()
        assert json.loads(out.read_text())["phase1_input"] == str(phase1)


class TestPhase4ScorerOverrides:
    """``--corpus`` and ``--out`` must beat the module defaults."""

    def test_out_override_wins_and_the_default_is_untouched(self, tmp_path, monkeypatch, capsys):
        module = _load("phase4_exemplar_scorer.py")
        sentinel = tmp_path / "default-must-not-be-written.json"
        monkeypatch.setattr(module, "OUT", sentinel)
        monkeypatch.setattr(module, "CORPUS", tmp_path / "default-corpus")
        chosen = tmp_path / "chosen-candidates.json"
        assert module.main([
            "--corpus", str(_corpus_fixture(tmp_path / "extracted")),
            "--out", str(chosen),
        ]) == 0
        capsys.readouterr()
        assert chosen.exists()
        assert not sentinel.exists()

    def test_corpus_override_is_the_directory_that_is_read(self, tmp_path, monkeypatch, capsys):
        module = _load("phase4_exemplar_scorer.py")
        monkeypatch.setattr(module, "CORPUS", _corpus_fixture(tmp_path / "default-corpus"))
        missing = tmp_path / "chosen-but-absent"
        assert module.main(["--corpus", str(missing)]) == 2
        assert str(missing) in capsys.readouterr().err

    def test_metadata_is_read_from_the_overridden_corpus(self, tmp_path, monkeypatch, capsys):
        """load_meta reaches the corpus through a module global, not the arg."""
        module = _load("phase4_exemplar_scorer.py")
        monkeypatch.setattr(module, "CORPUS", tmp_path / "default-corpus")
        monkeypatch.setattr(module, "OUT", tmp_path / "unused.json")
        out = tmp_path / "candidates.json"
        assert module.main([
            "--corpus", str(_corpus_fixture(tmp_path / "extracted")),
            "--out", str(out),
        ]) == 0
        capsys.readouterr()
        papers = json.loads(out.read_text())["per_paper"]
        assert [paper["role"] for paper in papers] == ["first"]
