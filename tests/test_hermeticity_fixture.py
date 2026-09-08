"""
Tests for the suite's own hermeticity guard (``tests/conftest.py``).

Three separate times during the September 2026 audit a test wrote a real
gate, sidecar, or refusal-memory file under ``~/.cache``, putting a
fabricated infrastructure problem in front of Shawn at his next session
start. The guard that now asserts the property is itself a piece of
safety equipment, and safety equipment that has never been shown to fire
is decoration — so each way it can fire is exercised here, in a child
pytest run with ``HOME`` pinned to a throwaway directory.

Nothing here touches the operator's real ``~/.cache``: the child run's
``HOME`` is a tmp_path, so the guard under test watches the fake one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_CONFTEST = Path(__file__).resolve().parent / "conftest.py"

#: A conftest that re-exports only the fixture under test, so the child
#: run gets the real code without the rest of the suite's fixtures.
_CHILD_CONFTEST = '''
import importlib.util
import sys

spec = importlib.util.spec_from_file_location(
    "pa_conftest", r"{conftest}",
)
module = importlib.util.module_from_spec(spec)
sys.modules["pa_conftest"] = module
spec.loader.exec_module(module)

no_real_cache_writes = module.no_real_cache_writes
'''


def _run_probe(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Run one probe test under the real fixture, HOME pinned to tmp_path.

    ``body`` is the probe's function body; it runs against a fake home
    whose ``.cache`` already holds one watched file.
    """
    home = tmp_path / "home"
    cache = home / ".cache"
    cache.mkdir(parents=True)
    (cache / "postgres-sync-memories-gate").write_text("0\n", encoding="utf-8")

    work = tmp_path / "child"
    work.mkdir()
    (work / "conftest.py").write_text(
        _CHILD_CONFTEST.format(conftest=REPO_CONFTEST), encoding="utf-8",
    )
    (work / "test_probe.py").write_text(
        "import os\nfrom pathlib import Path\n\n\n"
        "def test_probe():\n" + body,
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         "-p", "no:cacheprovider", str(work)],
        capture_output=True, text=True, cwd=str(work),
        env={
            "HOME": str(home),
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )


def test_the_guard_catches_a_created_gate(tmp_path):
    """
    The original failure: a test wrote a real gate file. The mutation
    this kills: dropping the ``created`` arm of the assertion.
    """
    result = _run_probe(
        tmp_path,
        '    (Path(os.environ["HOME"]) / ".cache" / "memory-drift-gate")'
        '.write_text("1\\nboom\\n", encoding="utf-8")\n',
    )

    assert result.returncode != 0, result.stdout
    assert "created:" in result.stdout
    assert "memory-drift-gate" in result.stdout


def test_the_guard_catches_a_deleted_gate(tmp_path):
    """
    A test that pointed a script at the real gate and then tidied up
    after itself would remove a standing alarm — the same damage as
    writing one, in the other direction. The mutation this kills:
    dropping the ``deleted`` arm (eighth re-audit, M7).
    """
    result = _run_probe(
        tmp_path,
        '    (Path(os.environ["HOME"]) / ".cache" '
        '/ "postgres-sync-memories-gate").unlink()\n',
    )

    assert result.returncode != 0, result.stdout
    assert "deleted:" in result.stdout
    assert "postgres-sync-memories-gate" in result.stdout


def test_the_guard_catches_a_same_size_rewrite(tmp_path):
    """
    A rewrite within one clock tick leaves the mtime alone, and a script
    that restores timestamps (or a coarse filesystem) makes that the
    normal case rather than a rare one. The probe writes new content and
    puts the old mtime back, so only a snapshot that also records the
    SIZE can see it. The mutation this kills: snapshotting the mtime
    alone.
    """
    result = _run_probe(
        tmp_path,
        '    gate = Path(os.environ["HOME"]) / ".cache" '
        '/ "postgres-sync-memories-gate"\n'
        "    stamp = gate.stat().st_mtime_ns\n"
        '    gate.write_text("99\\n", encoding="utf-8")\n'
        "    os.utime(gate, ns=(stamp, stamp))\n",
    )

    assert result.returncode != 0, result.stdout
    assert "modified:" in result.stdout


def test_the_guard_catches_a_repointed_home(tmp_path):
    """
    Every check here resolves ``~`` at call time, so a test that leaves
    HOME somewhere else makes the guard watch the wrong directory for the
    rest of the run — vacuously green. The mutation this kills: dropping
    the HOME assertion.
    """
    result = _run_probe(
        tmp_path,
        '    os.environ["HOME"] = str(Path(os.environ["HOME"]) / "moved")\n',
    )

    assert result.returncode != 0, result.stdout
    assert "left HOME repointed" in result.stdout


def test_a_well_behaved_test_run_still_passes(tmp_path):
    """
    The guard must not fail every run: a probe that writes only inside
    its own tmp directory has to come back green, or the fixture is just
    a broken build.
    """
    result = _run_probe(
        tmp_path,
        "    import tempfile\n"
        "    with tempfile.TemporaryDirectory() as scratch:\n"
        '        (Path(scratch) / "postgres-sync-memories-gate")'
        '.write_text("0\\n", encoding="utf-8")\n',
    )

    assert result.returncode == 0, result.stdout


def test_every_watched_glob_actually_catches_something(tmp_path):
    """
    A glob list is only as good as its coverage, and a name dropped from
    it fails nothing — the guard just stops watching. One representative
    file per pattern, all written in a single child run, so removing any
    entry from ``_PIPELINE_CACHE_GLOBS`` leaves its file unreported.

    The mutation this kills: deleting any one glob — for instance
    ``index-session-content-*``, which covers the refusal memory that
    leaked into the real cache once already.
    """
    representatives = (
        "postgres-sync-memories-gate",
        "index-session-content-refusals.json",
        "daily-sync-gate",
        "daily-sync-last-run",
        "memory-drift-gate",
        "cc-archives-gate",
        "cc-archive-drift-gate",
        "syncthing-gate",
    )
    body = '    cache = Path(os.environ["HOME"]) / ".cache"\n'
    for name in representatives:
        if name == "postgres-sync-memories-gate":
            # Already present, so exercise the modified arm for this one.
            body += f'    (cache / "{name}").write_text("7\\n")\n'
        else:
            body += f'    (cache / "{name}").write_text("1\\n")\n'

    result = _run_probe(tmp_path, body)

    assert result.returncode != 0, result.stdout
    for name in representatives:
        assert name in result.stdout, (
            f"{name} is not covered by any watched glob"
        )
