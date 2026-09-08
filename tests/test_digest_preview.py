"""
Smoke tests for ``scripts/digest-preview.py`` — the Vector 2 dry-run harness.

Lens B (RT17): the module had no coverage at all, and it wrote to the live
``data/logs/digest.log`` by default, so a dry run was indistinguishable
from a real session digest in the very log the Vector 2 measurements are
read from.

These tests drive ``main()`` over a synthetic corpus — the hook's own
loader is replaced, so nothing here reads the operator's memories — and
pin the two things that matter: the harness still runs end to end, and its
demonstration line lands in its own file, marked as a preview.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(SCRIPTS_DIR))


def _load(name: str, path: Path):
    """Import a hyphenated module by file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


digest_preview = _load("digest_preview", SCRIPTS_DIR / "digest-preview.py")


def _corpus() -> list[dict[str, Any]]:
    """A small synthetic corpus spanning the buckets the harness exercises."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    def _stamp(days: float) -> str:
        return (now - timedelta(days=days)).isoformat()

    return [
        {
            "id": "2026-05-01-aaaa1111",
            "category": "decision",
            "content": "Standardise the survey grid on 20 m squares.",
            "summary": "20 m survey grid",
            "verified": "true",
            "research_tags": ["survey", "methodology"],
            "source_context": "field planning",
            "created_at": _stamp(1),
            "project": "-home-shawn-Code-fieldwork",
        },
        {
            "id": "2026-04-02-bbbb2222",
            "category": "constraint",
            "content": "Permits forbid excavation inside the reserve boundary.",
            "summary": "No excavation in the reserve",
            "verified": "pending",
            "research_tags": ["permits"],
            "source_context": "permit correspondence",
            "created_at": _stamp(40),
            "project": "-home-shawn-Code-fieldwork",
        },
        {
            "id": "2026-03-11-cccc3333",
            "category": "gotcha",
            "content": "The total station drifts after a battery swap.",
            "summary": "Total station drift",
            "research_tags": ["survey"],
            "source_context": "equipment log",
            "created_at": _stamp(20),
            "project": "-home-shawn-Code-fieldwork",
        },
    ]


@pytest.fixture()
def _synthetic_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the harness the real hook, but a synthetic corpus to read."""
    hook = _load("session_start_retrieval", HOOKS_DIR / "session-start-retrieval.py")
    monkeypatch.setattr(hook, "load_all_memories", _corpus)
    monkeypatch.setattr(digest_preview, "_load_hook", lambda: hook)


class TestMainSmoke:
    """The harness runs, reports, and touches nothing it should not."""

    def test_reports_before_and_after(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str], _synthetic_hook: None,
    ) -> None:
        """A plain run produces the before/after comparison it exists for."""
        monkeypatch.setenv("PA_DIGEST_PREVIEW_LOG", str(tmp_path / "preview.log"))
        monkeypatch.setattr(
            sys, "argv", ["digest-preview.py", "--cwd", "/home/shawn/Code/fieldwork"],
        )
        digest_preview.main()
        out = capsys.readouterr().out
        assert "BEFORE recall dump" in out
        assert "AFTER  digest" in out

    def test_demonstration_line_is_marked_as_a_preview(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        _synthetic_hook: None,
    ) -> None:
        """Kills: writing an unmarked line, or writing to the live digest.log."""
        target = tmp_path / "preview.log"
        monkeypatch.setenv("PA_DIGEST_PREVIEW_LOG", str(target))
        monkeypatch.setattr(sys, "argv", ["digest-preview.py"])
        digest_preview.main()
        line = target.read_text(encoding="utf-8").rstrip("\n")
        assert line.endswith("\tpreview=true")
        assert "bytes=" in line  # still the digest.log format, as intended

    def test_no_log_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        _synthetic_hook: None,
    ) -> None:
        """``--no-log`` is the documented opt-out."""
        target = tmp_path / "preview.log"
        monkeypatch.setenv("PA_DIGEST_PREVIEW_LOG", str(target))
        monkeypatch.setattr(sys, "argv", ["digest-preview.py", "--no-log"])
        digest_preview.main()
        assert not target.exists()

    def test_unpinned_run_under_pytest_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        _synthetic_hook: None,
    ) -> None:
        """Audit R17: the operator's logs are not the suite's scratch space."""
        monkeypatch.delenv("PA_DIGEST_PREVIEW_LOG", raising=False)
        monkeypatch.setattr(
            digest_preview, "SHIPPED_LOG_PATH", tmp_path / "logs" / "preview.log",
        )
        monkeypatch.setattr(sys, "argv", ["digest-preview.py"])
        digest_preview.main()
        assert not (tmp_path / "logs").exists()

    def test_hub_mode_sees_all_projects(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str], _synthetic_hook: None,
    ) -> None:
        """The PA hub maps to current_project=None, as the live hook does."""
        monkeypatch.setenv("PA_DIGEST_PREVIEW_LOG", str(tmp_path / "preview.log"))
        monkeypatch.setattr(sys, "argv", ["digest-preview.py"])
        digest_preview.main()
        assert "PA hub (all projects)" in capsys.readouterr().out
