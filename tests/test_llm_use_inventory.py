"""
Tests for scripts/llm-use-inventory.py — the LLM-use disclosure report.

The report is written to be quoted in a paper's methods section, so its
honesty rules are load-bearing: a heuristic session type must be marked
"(proposed — confirm)", the archive's notional token cost must be omitted
because a flat-rate subscription makes it fiction, and wall-clock duration
must carry the caveat that it is not human effort. None of that was tested
(lens B, tranche 5, ET18), and ``--project`` was joined to the archive root
unsanitised (lens A, E21).

Every session, label, and identifier below is invented; no real archive is
read.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "llm-use-inventory.py"
)


@pytest.fixture(scope="module")
def inventory() -> Any:
    """Load the hyphen-named script by path and return the module."""
    spec = importlib.util.spec_from_file_location("llm_use_inventory", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: the script defines a @dataclass, and
    # dataclasses resolves ClassVar annotations through
    # ``sys.modules[cls.__module__]``, which does not exist yet otherwise.
    sys.modules["llm_use_inventory"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    """A synthetic archive root holding one project with two sessions."""
    root = tmp_path / "cc-archives"
    project = root / "terrace-survey"
    for index, (stamp, slug, minutes) in enumerate(
        [
            ("20310204-101500", "statistical-analysis-of-sherd-counts", 930),
            ("20310205-090000", "draft-the-methods-section", 45),
        ]
    ):
        session_dir = project / f"{stamp}_{slug}"
        session_dir.mkdir(parents=True)
        (session_dir / "session.meta.json").write_text(
            json.dumps(
                {
                    "session": {
                        "id": f"session_synthetic_{index}",
                        "started_at": "2031-02-0{}T09:00:00Z".format(
                            index + 4
                        ),
                        "duration_minutes": minutes,
                    },
                    "model": {"model_id": "synthetic-model-1"},
                    "statistics": {
                        "turns": 12 + index,
                        "tool_calls": {"total": 40 + index},
                        "tokens": {"output": 250_000},
                        "subagents_summary": {
                            "count": 2,
                            "by_type": {"general-purpose": 2},
                        },
                    },
                    "thinking_blocks": {"count": 7},
                    "tags": ["analysis"],
                }
            ),
            encoding="utf-8",
        )
    # A sibling directory OUTSIDE the intended project, to be escaped to.
    (root / "other-project").mkdir(parents=True)
    return root


def _run(
    inventory: Any, monkeypatch: pytest.MonkeyPatch, *argv: str
) -> tuple[int, str]:
    """Run ``main()`` and return its status plus whatever it wrote."""
    monkeypatch.setattr(sys, "argv", ["llm-use-inventory.py", *argv])
    out_index = argv.index("--out") + 1 if "--out" in argv else None
    status = inventory.main()
    written = (
        Path(argv[out_index]).read_text(encoding="utf-8")
        if out_index is not None
        else ""
    )
    return status, written


class TestHonestyRules:
    """What the report may and may not claim."""

    def test_auto_proposed_types_are_flagged(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With no --types-map, the split is marked as unconfirmed."""
        out = tmp_path / "report.md"
        status, report = _run(
            inventory, monkeypatch,
            "--project", "terrace-survey",
            "--archive-root", str(archive),
            "--generated", "2031-02-06",
            "--out", str(out),
        )
        assert status == 0
        assert "auto-proposed — confirm before use" in report
        assert "confirm or override" in report

    def test_an_override_removes_the_flag(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A confirmed type must not still be labelled a guess."""
        types_map = tmp_path / "types.json"
        directories = sorted(
            p.name for p in (archive / "terrace-survey").iterdir()
        )
        types_map.write_text(
            json.dumps({d: "analysis" for d in directories}),
            encoding="utf-8",
        )
        out = tmp_path / "report.md"
        _, report = _run(
            inventory, monkeypatch,
            "--project", "terrace-survey",
            "--archive-root", str(archive),
            "--types-map", str(types_map),
            "--generated", "2031-02-06",
            "--out", str(out),
        )
        assert "auto-proposed — confirm before use" not in report

    def test_token_cost_is_omitted(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A notional list price is not expenditure and must not appear."""
        out = tmp_path / "report.md"
        _, report = _run(
            inventory, monkeypatch,
            "--project", "terrace-survey",
            "--archive-root", str(archive),
            "--generated", "2031-02-06",
            "--out", str(out),
        )
        # Collapse the report's line wrapping before matching, so the
        # assertion pins the claim rather than the column at which it broke.
        flat = " ".join(report.split())
        assert "not actual expenditure" in flat
        assert "omitted here by design" in flat
        assert "$" not in report, "a currency figure reached the report"

    def test_duration_carries_its_caveat(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Wall-clock hours must never read as hours of human effort."""
        out = tmp_path / "report.md"
        _, report = _run(
            inventory, monkeypatch,
            "--project", "terrace-survey",
            "--archive-root", str(archive),
            "--generated", "2031-02-06",
            "--out", str(out),
        )
        assert "not human effort" in report
        assert "Actual human time lives in the personal time-log" in report

    def test_thinking_traces_are_excluded_from_output_tokens(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The output-token figure must say what it leaves out."""
        out = tmp_path / "report.md"
        _, report = _run(
            inventory, monkeypatch,
            "--project", "terrace-survey",
            "--archive-root", str(archive),
            "--generated", "2031-02-06",
            "--out", str(out),
        )
        assert "tracked separately" in report
        assert "14 thinking blocks" in report


class TestProjectIsContainedToTheArchive:
    """E21 — --project names one directory inside the archive root."""

    def test_a_parent_relative_project_is_refused(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``../`` must not walk out of the archive root."""
        with pytest.raises(SystemExit) as excinfo:
            _run(
                inventory, monkeypatch,
                "--project", "../cc-archives/other-project",
                "--archive-root", str(archive / "terrace-survey"),
                "--generated", "2031-02-06",
            )
        assert excinfo.value.code == 2

    def test_an_absolute_project_is_refused(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An absolute --project would ignore the root entirely."""
        with pytest.raises(SystemExit) as excinfo:
            _run(
                inventory, monkeypatch,
                "--project", str(tmp_path),
                "--archive-root", str(archive),
                "--generated", "2031-02-06",
            )
        assert excinfo.value.code == 2

    def test_a_normal_project_still_works(
        self, inventory: Any, archive: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The legitimate case is unaffected."""
        out = tmp_path / "report.md"
        status, report = _run(
            inventory, monkeypatch,
            "--project", "terrace-survey",
            "--archive-root", str(archive),
            "--generated", "2031-02-06",
            "--out", str(out),
        )
        assert status == 0
        assert "terrace-survey" in report


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
