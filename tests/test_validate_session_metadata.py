"""
Tests for ``scripts/validate-session-metadata.py`` — the cheap defect gate.

537 lines, zero tests before 2026-09-08: ``check_schema`` could be disabled
outright and the full suite stayed green (lens B finding 9). This is the
script whose whole justification is that it catches, for nothing, the three
defect classes that make a session unfindable — so a silently disabled check
is worse than no check, because the report still says "0 errors".

One record per defect class, the ``--fail-on`` exit semantics, the
"manifest absent means skipped, never passed" contract, and the AR22
containment of the manifest-derived repository join.

Every metadata record, project name, and session id here is invented.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _load():
    """Import the hyphenated script by path.

    Registered in ``sys.modules`` before execution because the module defines
    a ``@dataclass``, and dataclasses resolve their annotations through
    ``sys.modules[cls.__module__]``.
    """
    name = "validate_session_metadata_under_test"
    spec = importlib.util.spec_from_file_location(
        name, str(SCRIPTS_DIR / "validate-session-metadata.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validator = _load()

SID = "cccccccc-6666-4666-8666-cccccccccccc"


def _record(**overrides) -> dict:
    """A well-formed metadata record; overrides introduce one defect."""
    record = {
        "title": "Terrace survey grid",
        "purpose": "Decide how the survey grid meets the terrace edge.",
        "tags": ["survey-design", "lantern-survey", "terrace"],
        "three_ps": {
            "prompt_summary": "Asked how to lay the grid on a terraced slope.",
            "process_summary": "Compared contour-following and downslope grids.",
            "provenance_summary": "Follows the 2026-02 reconnaissance visit.",
        },
    }
    record.update(overrides)
    return record


def _responses_dir(tmp_path: Path, records: dict[str, dict]) -> Path:
    """Write one arm directory holding the given ``session_id -> record``."""
    arm = tmp_path / "responses" / "luna"
    arm.mkdir(parents=True)
    for sid, record in records.items():
        (arm / f"{sid}.json").write_text(json.dumps(record), encoding="utf-8")
    return tmp_path / "responses"


def _manifest(tmp_path: Path, project: str = "lantern-survey") -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "sessions": [{"session_id": SID, "project": project}]
    }), encoding="utf-8")
    return path


class TestDefectClasses:
    """One record per class of defect this script exists to catch.

    Every case here goes through ``validate_record``, the function the
    command actually calls, rather than through the individual check. Calling
    the checks directly left the orchestration untested: deleting
    ``findings += check_field_swap(...)`` — or check_commits, or check_paths
    — from validate_record left all 25 tests green while the corresponding
    defect stopped being reported at all (round 4c-2, finding 20).
    """

    def _checks(self, findings) -> set[str]:
        """The check names that fired, as reported by validate_record."""
        return {finding.check for finding in findings}

    def test_a_clean_record_produces_no_errors(self) -> None:
        """The positive control: the checks must not fire on good metadata."""
        findings = validator.validate_record("luna", SID, _record(), None)

        assert [f for f in findings if f.severity == "error"] == []

    def test_a_missing_required_field_is_an_error(self) -> None:
        record = _record()
        del record["tags"]

        findings = validator.validate_record("luna", SID, record, None)

        errors = [f for f in findings if f.severity == "error"]
        assert "schema" in self._checks(errors)
        assert any("tags" in f.message for f in errors)

    def test_an_empty_provenance_summary_is_an_error(self) -> None:
        """The observed field-swap defect, caught from the emptiness side."""
        record = _record()
        record["three_ps"]["provenance_summary"] = "   "

        findings = validator.validate_record("luna", SID, record, None)

        assert any(
            "three_ps.provenance_summary" in f.message for f in findings
        )

    def test_provenance_prose_misfiled_into_process_is_an_error(self) -> None:
        record = _record()
        record["three_ps"]["provenance_summary"] = ""
        record["three_ps"]["process_summary"] = (
            "Continues the 2026-02 reconnaissance work on the lower terrace."
        )

        findings = validator.validate_record("luna", SID, record, None)

        swaps = [f for f in findings if f.check == "field-swap"]
        assert swaps, (
            "check_field_swap is not reached from validate_record; the "
            "field-swap defect class is not reported at all"
        )
        assert swaps[0].severity == "error"

    def test_a_field_swap_is_not_reported_when_provenance_is_populated(
        self
    ) -> None:
        """The check is deliberately conservative: no sibling gap, no finding."""
        record = _record()
        record["three_ps"]["process_summary"] = (
            "Continues the comparison started earlier in the session."
        )

        findings = validator.validate_record("luna", SID, record, None)

        assert "field-swap" not in self._checks(findings)

    def test_tags_must_be_a_list(self) -> None:
        findings = validator.validate_record(
            "luna", SID, _record(tags="survey"), None
        )

        assert any("tags must be a list" in f.message for f in findings)

    def test_a_cited_commit_hash_is_reached_from_validate_record(self) -> None:
        """check_commits must be wired in, not merely importable."""
        record = _record()
        record["three_ps"]["process_summary"] = (
            "Committed the grid change as 4f2a9c1e8b3d5a7f6c0e2d4b8a1f3c5e7d9b0a2c."
        )

        findings = validator.validate_record("luna", SID, record, None)

        commits = [f for f in findings if f.check == "commit"]
        assert commits, (
            "check_commits is not reached from validate_record; a cited "
            "commit hash is never verified"
        )
        # No manifest, so no repo: unverifiable, reported as a warning.
        assert commits[0].severity == "warning"

    def test_a_cited_path_is_reached_from_validate_record(self) -> None:
        """check_paths must be wired in too."""
        record = _record()
        record["three_ps"]["process_summary"] = (
            "Wrote /home/tester/Workshop/no-such-file-anywhere-xyz.md."
        )

        findings = validator.validate_record("luna", SID, record, None)

        paths = [f for f in findings if f.check == "path"]
        assert paths, (
            "check_paths is not reached from validate_record; a confabulated "
            "file path is never reported"
        )
        assert paths[0].severity == "warning"

    def test_every_check_is_reachable_from_the_orchestrator(self) -> None:
        """One record carrying every defect class at once.

        Deleting any single `findings += ...` line from validate_record must
        break this, whichever line it is.
        """
        record = _record()
        del record["title"]
        record["three_ps"]["provenance_summary"] = ""
        record["three_ps"]["process_summary"] = (
            "Continues the earlier survey; commit "
            "4f2a9c1e8b3d5a7f6c0e2d4b8a1f3c5e7d9b0a2c wrote "
            "/home/tester/Workshop/no-such-file-anywhere-xyz.md."
        )
        record["tags"] = ["markdown", "git", "python"]

        findings = validator.validate_record("luna", SID, record, None)

        fired = self._checks(findings)
        assert fired >= {"schema", "field-swap", "commit", "path"}, (
            f"checks that fired: {fired}"
        )
        assert any(check.startswith("tag-") for check in fired), (
            f"check_tags is not reached from validate_record: {fired}"
        )


class TestExitSemantics:
    """``--fail-on`` is what lets this gate a pipeline."""

    def _run(self, monkeypatch, responses: Path, *args: str) -> int:
        monkeypatch.setattr(sys, "argv", [
            "validate-session-metadata.py",
            "--responses-dir", str(responses), *args,
        ])
        return validator.main()

    def test_a_clean_directory_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responses = _responses_dir(tmp_path, {SID: _record()})

        assert self._run(monkeypatch, responses) == 0

    def test_an_error_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = _record()
        del broken["purpose"]
        responses = _responses_dir(tmp_path, {SID: broken})

        assert self._run(monkeypatch, responses) == 1

    def test_a_warning_alone_exits_zero_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A generic tag is dead weight, not a defect."""
        responses = _responses_dir(
            tmp_path, {SID: _record(tags=["markdown", "git", "python"])}
        )

        assert self._run(monkeypatch, responses) == 0

    def test_fail_on_warning_raises_the_bar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responses = _responses_dir(
            tmp_path, {SID: _record(tags=["markdown", "git", "python"])}
        )

        assert self._run(
            monkeypatch, responses, "--fail-on", "warning"
        ) == 1

    def test_unparseable_json_is_an_error_not_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responses = _responses_dir(tmp_path, {})
        (responses / "luna" / f"{SID}.json").write_text("{oops", encoding="utf-8")

        assert self._run(monkeypatch, responses) == 1

    def test_the_report_is_written_when_asked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responses = _responses_dir(tmp_path, {SID: _record()})
        report = tmp_path / "report.json"

        self._run(monkeypatch, responses, "--report", str(report))

        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["per_arm"]["luna"]


class TestManifestAbsenceIsSkippedNotPassed:
    """A check that cannot run must never be reported as having passed."""

    def test_no_manifest_yields_no_ground_truth(self) -> None:
        assert validator.load_truth(None) == {}

    def test_the_absence_is_announced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        responses = _responses_dir(tmp_path, {SID: _record()})
        monkeypatch.setattr(sys, "argv", [
            "validate-session-metadata.py", "--responses-dir", str(responses),
        ])

        validator.main()

        assert "reported as skipped, not passed" in capsys.readouterr().out

    def test_a_manifest_supplies_the_project_tag_check(
        self, tmp_path: Path
    ) -> None:
        truth = validator.load_truth(_manifest(tmp_path))

        assert truth[SID].project == "lantern-survey"


class TestManifestDerivedPathsAreContained:
    """AR22 — a manifest value must not steer a filesystem join.

    The project name is read out of a manifest, joined onto Path.home(), and
    handed to ``git -C``. A name like ``../../etc`` sent both somewhere else
    entirely.
    """

    @pytest.mark.parametrize("project", [
        "../../etc", "/etc", "..", ".", "sub/dir", ".hidden", "", None,
    ])
    def test_an_unsafe_project_name_yields_no_candidate_repository(
        self, project
    ) -> None:
        assert validator._candidate_repos(project) == []

    def test_a_plain_project_name_still_resolves(self) -> None:
        candidates = validator._candidate_repos("lantern-survey")

        assert [path.name for path in candidates] == [
            "lantern-survey", "lantern-survey"
        ]
        assert all(path.is_absolute() for path in candidates)

    def test_a_traversing_manifest_leaves_hashes_unverifiable(
        self, tmp_path: Path
    ) -> None:
        """Unverifiable is the safe answer; checking the wrong repo is not."""
        truth = validator.load_truth(_manifest(tmp_path, project="../../etc"))

        assert truth[SID].repo_path is None
