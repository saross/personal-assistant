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
