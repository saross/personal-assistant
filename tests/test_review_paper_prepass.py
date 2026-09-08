"""
Tests for scripts/review-paper-prepass.py — the mechanical pre-pass.

The script had no tests (lens B, tranche 5, ET18) even though it runs
external tools, reads arbitrary files named in manuscript comments, and
promises in its header that "each [check] degrades gracefully to a
``checks_skipped`` entry if its tool or input is missing". This file pins
that promise, and the containment fix for the guard-anchor reader (lens
A, E17): an anchor written in a .tex comment could name ``..``-relative
or absolute paths, and the resulting finding reported whether such a file
existed and how many lines it had.

Every manuscript, label, and path below is invented; nothing here runs a
build command or contacts a service.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "review-paper-prepass.py"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every socket connection for the life of each test."""

    def _refuse(*args: Any, **kwargs: Any):
        raise AssertionError("a test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(scope="module")
def prepass() -> Any:
    """Load the hyphen-named script by path and return the module."""
    spec = importlib.util.spec_from_file_location(
        "review_paper_prepass", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    """A minimal synthetic paper repository."""
    repo = tmp_path / "paper"
    repo.mkdir()
    (repo / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Terrace survey results follow.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    return repo


def _run(prepass: Any, monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict:
    """Run ``main()`` with ``argv`` and return the parsed JSON report."""
    out = Path(argv[argv.index("--json-out") + 1])
    monkeypatch.setattr(sys, "argv", ["review-paper-prepass.py", *argv])
    assert prepass.main() in (0, 1), "unexpected exit status"
    return json.loads(out.read_text(encoding="utf-8"))


class TestChecksDegradeWhenAToolIsAbsent:
    """The header's graceful-degradation promise, per check."""

    def test_spelling_skips_without_aspell(
        self, prepass: Any, paper: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A missing aspell is a recorded skip, not a crash or a silence."""
        monkeypatch.setattr(
            prepass.shutil, "which", lambda name: None
        )
        report = _run(
            prepass, monkeypatch,
            "--repo", str(paper), "--target", "main.tex",
            "--json-out", str(tmp_path / "report.json"),
        )
        skipped = {s["check"] for s in report["checks_skipped"]}
        assert "spelling" in skipped
        assert "spelling" not in report["checks_run"]

    def test_word_budget_skips_without_texcount(
        self, prepass: Any, paper: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Same for the word budget, whose tool is a different binary."""
        monkeypatch.setattr(prepass.shutil, "which", lambda name: None)
        report = _run(
            prepass, monkeypatch,
            "--repo", str(paper), "--target", "main.tex",
            "--word-budget", "8000",
            "--json-out", str(tmp_path / "report.json"),
        )
        skipped = {s["check"] for s in report["checks_skipped"]}
        assert "word-budget" in skipped

    def test_a_timeout_is_a_skip_not_a_traceback(
        self, prepass: Any, paper: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hung external tool degrades the check, not the run."""
        monkeypatch.setattr(prepass.shutil, "which", lambda name: "/bin/true")

        def _timeout(*args: Any, **kwargs: Any):
            raise subprocess.TimeoutExpired(cmd="aspell", timeout=1)

        monkeypatch.setattr(prepass.subprocess, "run", _timeout)
        report = _run(
            prepass, monkeypatch,
            "--repo", str(paper), "--target", "main.tex",
            "--json-out", str(tmp_path / "report.json"),
        )
        reasons = " ".join(s["reason"] for s in report["checks_skipped"])
        assert "timed out" in reasons

    def test_aux_labels_skip_without_an_aux_file(
        self, prepass: Any, paper: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The aux-label rule: no .aux supplied means a recorded skip."""
        monkeypatch.setattr(prepass.shutil, "which", lambda name: None)
        report = _run(
            prepass, monkeypatch,
            "--repo", str(paper), "--target", "main.tex",
            "--json-out", str(tmp_path / "report.json"),
        )
        skips = {s["check"]: s["reason"] for s in report["checks_skipped"]}
        assert "aux-labels" in skips
        assert "aux" in skips["aux-labels"]

    def test_a_named_but_absent_aux_is_reported_by_path(
        self, prepass: Any, paper: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Naming a .aux that is not there says which one."""
        monkeypatch.setattr(prepass.shutil, "which", lambda name: None)
        report = _run(
            prepass, monkeypatch,
            "--repo", str(paper), "--target", "main.tex",
            "--aux", "build/main.aux",
            "--json-out", str(tmp_path / "report.json"),
        )
        reasons = [
            s["reason"]
            for s in report["checks_skipped"]
            if s["check"] == "aux-labels"
        ]
        assert any("main.aux" in r for r in reasons), reasons


class TestGuardAnchorsAreContainedToTheRepo:
    """E17 — an anchor is a pointer into the repository, nothing wider."""

    def test_a_parent_relative_anchor_is_not_probed(
        self, prepass: Any, tmp_path: Path
    ) -> None:
        """``../outside.tex`` must not be resolved, even though it exists."""
        repo = tmp_path / "paper"
        repo.mkdir()
        outside = tmp_path / "outside.tex"
        outside.write_text("secret\n" * 40, encoding="utf-8")
        target = repo / "main.tex"
        target.write_text("% STANDING GUARD: see ../outside.tex:3\n", "utf-8")

        candidates = prepass._contained_candidates(
            "../outside.tex", repo, target
        )

        assert candidates == []

    def test_an_absolute_anchor_is_not_probed(
        self, prepass: Any, tmp_path: Path
    ) -> None:
        """An absolute path is refused outright."""
        repo = tmp_path / "paper"
        repo.mkdir()
        target = repo / "main.tex"
        target.write_text("% guard\n", encoding="utf-8")

        assert prepass._contained_candidates(
            "/etc/hostname", repo, target
        ) == []

    def test_an_in_repo_anchor_still_resolves(
        self, prepass: Any, tmp_path: Path
    ) -> None:
        """The legitimate case is unaffected."""
        repo = tmp_path / "paper"
        (repo / "sections").mkdir(parents=True)
        inner = repo / "sections" / "methods.tex"
        inner.write_text("one\ntwo\nthree\n", encoding="utf-8")
        target = repo / "main.tex"
        target.write_text("% guard\n", encoding="utf-8")

        candidates = prepass._contained_candidates(
            "sections/methods.tex", repo, target
        )

        assert inner.resolve() in candidates

    def test_an_escaping_anchor_reports_as_stale_not_as_a_probe(
        self, prepass: Any, tmp_path: Path
    ) -> None:
        """The finding must not disclose anything about the outside file."""
        repo = tmp_path / "paper"
        repo.mkdir()
        outside = tmp_path / "outside.tex"
        outside.write_text("x\n" * 99, encoding="utf-8")
        target = repo / "main.tex"
        raw = "% STANDING GUARD: ../outside.tex:98 is settled\n"
        target.write_text(raw, encoding="utf-8")

        found = prepass.check_guard_anchors(raw, "main.tex", repo, target)

        assert len(found) == 1
        assert "does not exist" in found[0]["detail"]
        assert "99" not in found[0]["detail"], (
            "the finding disclosed the outside file's length"
        )


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
