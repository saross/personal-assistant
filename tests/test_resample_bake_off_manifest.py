"""
Tests for ``scripts/resample-bake-off-manifest.py``.

The re-sampler used to be un-runnable in a test: its manifest path was a
module constant pointing straight at the canonical file in the private data
submodule, and ``main()`` wrote it unconditionally. The tests below drive the
real entry point against a synthetic candidate tree built under ``tmp_path``,
with both pool roots redirected by the new ``--archive-root`` /
``--live-root`` arguments — so the only file the suite can touch is the one
it asked for.

The script makes no network calls at all; the autouse socket guard is here so
that stays true if an adapter is ever added.

Every transcript, project name, and session id is invented — see
``tests/fixtures``.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SCRIPT = PROJECT_ROOT / "scripts" / "resample-bake-off-manifest.py"

sys.path.insert(0, str(TESTS_DIR))
from fixtures import bake_off as fx  # noqa: E402

_spec = importlib.util.spec_from_file_location("resample_bake_off_manifest", SCRIPT)
assert _spec is not None and _spec.loader is not None
resample = importlib.util.module_from_spec(_spec)
# Registered before execution: the module defines ``@dataclass`` types, and
# ``dataclasses`` resolves the defining module out of ``sys.modules``.
sys.modules[_spec.name] = resample
_spec.loader.exec_module(resample)

FROZEN_CLOCK = datetime.datetime(2026, 1, 6, 8, 30, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def refuse_sockets(monkeypatch):
    """Fail loudly if any test in this module opens a socket."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a re-sampler test opened a network socket; this script has no "
            "business talking to anything."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ---------------------------------------------------------------------------
# Synthetic candidate tree
# ---------------------------------------------------------------------------


def write_archive_session(
    root: Path,
    project: str,
    stamp: str,
    *,
    session_id: str,
    three_ps_populated: bool = False,
    n_records: int = 20,
    repeats: int = 3,
    started_at: str = "2026-01-04T08:00:00+00:00",
) -> Path:
    """Create ``<root>/cc-archives/<project>/<stamp>/`` with meta + transcript."""
    session_dir = root / "cc-archives" / project / stamp
    transcript = fx.write_session_transcript(
        session_dir / "session.jsonl", n_records=n_records, repeats=repeats
    )
    meta = {
        "session": {"id": session_id, "started_at": started_at},
        "project": {"name": project},
        "three_ps": {
            "prompt_summary": "Recorded earlier." if three_ps_populated else ""
        },
    }
    (session_dir / "session.meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return transcript


def write_live_session(
    root: Path,
    project_dir: str,
    session_id: str,
    *,
    n_records: int = 20,
    repeats: int = 3,
) -> Path:
    """Create ``<root>/.claude/projects/<project_dir>/<session_id>.jsonl``."""
    return fx.write_session_transcript(
        root / ".claude" / "projects" / project_dir / f"{session_id}.jsonl",
        n_records=n_records,
        repeats=repeats,
    )


def write_subagent_session(
    root: Path,
    project_dir: str,
    session_id: str,
    agent_name: str,
    *,
    n_records: int = 20,
    repeats: int = 3,
) -> Path:
    """Create a sub-agent transcript one level below a live session dir."""
    return fx.write_session_transcript(
        root / ".claude" / "projects" / project_dir / session_id / "subagents"
        / f"{agent_name}.jsonl",
        n_records=n_records,
        repeats=repeats,
    )


def tree_snapshot(root: Path) -> dict[str, int]:
    """Map every file under ``root`` to its size, for before/after comparison."""
    return {
        str(path.relative_to(root)): path.stat().st_size
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def pool(tmp_path):
    """Build a small synthetic pool: two archived sessions and one live one."""
    root = tmp_path / "home"
    write_archive_session(
        root, "thornhollow-survey", "2026-01-04T08-00-00",
        session_id="11111111-aaaa-bbbb-cccc-000000000001",
    )
    write_archive_session(
        root, "middle-vale-synthesis", "2026-01-05T09-00-00",
        session_id="22222222-aaaa-bbbb-cccc-000000000002",
        three_ps_populated=True,
    )
    write_live_session(
        root, "-home-shawn-Code-thornhollow-survey",
        "33333333-aaaa-bbbb-cccc-000000000003",
    )
    return root


def run_main(pool_root: Path, *args: str) -> int:
    """Invoke the entry point with both pool roots pinned to the tmp tree."""
    return resample.main([
        "--archive-root", str(pool_root),
        "--live-root", str(pool_root),
        *args,
    ])


# ---------------------------------------------------------------------------
# Paths and the write gate
# ---------------------------------------------------------------------------


class TestPathDefaults:
    """Nothing resolves to the operator's checkout by hardcoded string."""

    def test_pa_dir_is_file_derived(self):
        """The finding: PA_DIR was a hardcoded absolute path."""
        assert resample.PA_DIR == PROJECT_ROOT

    def test_globs_are_rooted_at_the_given_root(self, tmp_path):
        """Both pools follow --archive-root / --live-root, not $HOME."""
        for pattern in resample.archive_globs(tmp_path):
            assert pattern.startswith(str(tmp_path))
        for pattern in resample.live_globs(tmp_path):
            assert pattern.startswith(str(tmp_path))

    def test_no_module_constant_names_the_canonical_manifest(self):
        """A module-level output path is what made every run destructive."""
        assert not hasattr(resample, "MANIFEST_PATH")


class TestEntryPointWriteGate:
    """``--out`` is mandatory, refuses to clobber, and writes atomically."""

    def test_missing_out_exits_2_and_writes_nothing(self, pool, tmp_path):
        before = tree_snapshot(pool)
        assert run_main(pool) == 2
        assert tree_snapshot(pool) == before

    def test_dry_run_writes_nothing_anywhere(self, pool, tmp_path):
        """The plan is printed; not one byte lands on disk."""
        out = tmp_path / "would-be-manifest.json"
        before = tree_snapshot(pool)
        assert run_main(pool, "--dry-run", "--out", str(out)) == 0
        assert not out.exists()
        assert tree_snapshot(pool) == before

    def test_happy_path_writes_the_requested_file_only(self, pool, tmp_path):
        out = tmp_path / "manifests" / "sample-manifest.json"
        before = tree_snapshot(pool)
        assert run_main(pool, "--out", str(out)) == 0
        assert out.exists()
        assert tree_snapshot(pool) == before  # the pool itself is untouched
        manifest = json.loads(out.read_text(encoding="utf-8"))
        assert manifest["sessions"]
        assert manifest["rng_seed"] == 42

    def test_seed_is_recorded_from_the_flag(self, pool, tmp_path):
        out = tmp_path / "manifest.json"
        assert run_main(pool, "--out", str(out), "--seed", "7") == 0
        manifest = json.loads(out.read_text(encoding="utf-8"))
        assert manifest["rng_seed"] == 7
        assert "random.seed(7)" in manifest["notes"]

    def test_existing_manifest_is_not_overwritten(self, pool, tmp_path):
        """The finding: any invocation replaced the canonical manifest."""
        out = tmp_path / "manifest.json"
        out.write_text('{"sessions": ["do not lose me"]}\n', encoding="utf-8")
        assert run_main(pool, "--out", str(out)) == 2
        assert json.loads(out.read_text(encoding="utf-8")) == {
            "sessions": ["do not lose me"]
        }

    def test_force_replaces_an_existing_manifest(self, pool, tmp_path):
        out = tmp_path / "manifest.json"
        out.write_text('{"sessions": ["stale"]}\n', encoding="utf-8")
        assert run_main(pool, "--out", str(out), "--force") == 0
        manifest = json.loads(out.read_text(encoding="utf-8"))
        assert manifest["sessions"] != ["stale"]

    def test_writer_leaves_no_temp_file_behind(self, pool, tmp_path):
        out_dir = tmp_path / "manifests"
        assert run_main(pool, "--out", str(out_dir / "manifest.json")) == 0
        assert [p.name for p in out_dir.iterdir()] == ["manifest.json"]


class TestWriteJsonAtomic:
    """The replacement is a rename, so a reader never sees a half-file."""

    def test_failure_leaves_the_previous_file_intact(self, tmp_path):
        target = tmp_path / "manifest.json"
        target.write_text('{"keep": true}\n', encoding="utf-8")

        class Unserialisable:
            """json.dumps raises on this, part-way through the write."""

        with pytest.raises(TypeError):
            resample.write_json_atomic(target, {"boom": Unserialisable()})
        assert json.loads(target.read_text(encoding="utf-8")) == {"keep": True}
        assert list(tmp_path.iterdir()) == [target]


class TestDeduplication:
    """A session resident in both pools must enter as the archived copy."""

    def test_archive_copy_wins_over_live_copy(self):
        """The finding: the sort key ranked '.claude' before 'cc-archives'."""
        session_id = "44444444-aaaa-bbbb-cccc-000000000004"
        live = resample.Candidate(
            source="live",
            transcript_path=f"/home/invented/.claude/projects/p/{session_id}.jsonl",
            meta_path=None,
            project="p",
            session_id=session_id,
            started_at=None,
        )
        archived = resample.Candidate(
            source="archive",
            transcript_path="/home/invented/cc-archives/p/2026-01-04/session.jsonl",
            meta_path="/home/invented/cc-archives/p/2026-01-04/session.meta.json",
            project="thornhollow-survey",
            session_id=session_id,
            started_at="2026-01-04T08:00:00+00:00",
        )
        unique, removed = resample.deduplicate_candidates([live, archived])
        assert removed == 1
        assert [c.source for c in unique] == ["archive"]
        assert unique[0].meta_path is not None

    def test_dual_resident_session_keeps_its_three_ps_state(self, tmp_path):
        """End to end: the surviving row carries meta, not 'unknown'."""
        root = tmp_path / "home"
        session_id = "55555555-aaaa-bbbb-cccc-000000000005"
        write_archive_session(
            root, "thornhollow-survey", "2026-01-07T10-00-00",
            session_id=session_id, three_ps_populated=True,
        )
        write_live_session(
            root, "-home-shawn-Code-thornhollow-survey", session_id,
        )
        out = tmp_path / "manifest.json"
        assert run_main(root, "--out", str(out)) == 0
        rows = json.loads(out.read_text(encoding="utf-8"))["sessions"]
        row = next(r for r in rows if r["session_id"] == session_id)
        assert row["source"] == "archive"
        assert row["meta_path"] is not None
        assert row["current_three_ps_state"] == "populated"
        assert row["started_at"] == "2026-01-04T08:00:00+00:00"

    def test_subagent_copy_loses_to_a_live_copy(self, tmp_path):
        """Preference order is archive, then live, then sub-agent."""
        session_id = "66666666-aaaa-bbbb-cccc-000000000006"
        live = resample.Candidate(
            source="live", transcript_path="/z/live.jsonl", meta_path=None,
            project="p", session_id=session_id, started_at=None,
        )
        subagent = resample.Candidate(
            source="subagent", transcript_path="/a/sub.jsonl", meta_path=None,
            project="p", session_id=session_id, started_at=None,
        )
        unique, removed = resample.deduplicate_candidates([subagent, live])
        assert removed == 1
        assert [c.source for c in unique] == ["live"]


class TestReproducibility:
    """Same seed, same pool, same --as-of: the same bytes."""

    def test_two_runs_are_byte_identical(self, pool, tmp_path):
        """The finding: generated_at read the clock, so nothing reproduced."""
        first = tmp_path / "first.json"
        second = tmp_path / "second.json"
        as_of = FROZEN_CLOCK.isoformat()
        assert run_main(pool, "--out", str(first), "--as-of", as_of) == 0
        assert run_main(pool, "--out", str(second), "--as-of", as_of) == 0
        assert first.read_bytes() == second.read_bytes()

    def test_as_of_reaches_generated_at_and_the_notes(self, pool, tmp_path):
        out = tmp_path / "manifest.json"
        assert run_main(pool, "--out", str(out), "--as-of", "2026-01-06") == 0
        manifest = json.loads(out.read_text(encoding="utf-8"))
        assert manifest["generated_at"].startswith("2026-01-06T00:00:00")
        assert "Re-sampled 2026-01-06" in manifest["notes"]

    def test_a_different_seed_can_change_the_selection(self, tmp_path):
        """If the seed did nothing, byte-identity above would be vacuous."""
        root = tmp_path / "home"
        for index in range(6):
            write_archive_session(
                root, "thornhollow-survey", f"2026-01-1{index}T08-00-00",
                session_id=f"aaaaaaaa-0000-0000-0000-00000000000{index}",
            )
        selections = set()
        for seed in ("1", "2", "3", "4", "5"):
            out = tmp_path / f"manifest-{seed}.json"
            assert run_main(
                root, "--out", str(out), "--seed", seed,
                "--as-of", FROZEN_CLOCK.isoformat(),
            ) == 0
            rows = json.loads(out.read_text(encoding="utf-8"))["sessions"]
            selections.add(tuple(row["session_id"] for row in rows))
        assert len(selections) > 1

    def test_a_bad_as_of_is_rejected(self, pool, tmp_path):
        with pytest.raises(SystemExit) as excinfo:
            run_main(pool, "--out", str(tmp_path / "m.json"), "--as-of", "not-a-date")
        assert excinfo.value.code == 2


class TestShortfallReporting:
    """A bin that cannot be filled must say so."""

    def test_under_filled_bin_names_the_bin_and_the_counts(
        self, tmp_path, capsys
    ):
        """The finding: only a completely empty bin warned."""
        root = tmp_path / "home"
        write_archive_session(
            root, "thornhollow-survey", "2026-01-04T08-00-00",
            session_id="dddddddd-0000-0000-0000-000000000001",
        )
        out = tmp_path / "manifest.json"
        assert run_main(root, "--out", str(out)) == 0
        printed = capsys.readouterr().out
        target = resample.TARGET_COUNTS["short"]
        assert f"SHORTFALL: bin short filled 1 of {target}" in printed
        assert "1 candidate(s) in the pool)" in printed

    def test_empty_bin_reports_zero_of_target(self, tmp_path, capsys):
        root = tmp_path / "home"
        write_archive_session(
            root, "thornhollow-survey", "2026-01-04T08-00-00",
            session_id="dddddddd-0000-0000-0000-000000000002",
        )
        assert run_main(root, "--out", str(tmp_path / "manifest.json")) == 0
        printed = capsys.readouterr().out
        assert (
            f"SHORTFALL: bin long filled 0 of {resample.TARGET_COUNTS['long']}"
            in printed
        )

    def test_a_filled_bin_reports_no_shortfall(self, tmp_path, capsys):
        root = tmp_path / "home"
        for index in range(resample.TARGET_COUNTS["short"]):
            write_archive_session(
                root, "thornhollow-survey", f"2026-01-2{index}T08-00-00",
                session_id=f"eeeeeeee-0000-0000-0000-00000000000{index}",
            )
        assert run_main(root, "--out", str(tmp_path / "manifest.json")) == 0
        assert "SHORTFALL: bin short" not in capsys.readouterr().out
