"""
Import-side-effect tests for ``scripts/_bulk_rewrite_guard.py``.

Audit S22 (2026-09-08): the module opened a ``logging.FileHandler`` on
``<repo>/logs/bulk-rewrite-guard.log`` at IMPORT time, and ``mkdir``-ed
that directory first. ``logs`` is a symlink into the private ``data``
submodule, so simply importing the module — which the suite does, directly
and through every bulk-rewrite script that depends on it — wrote into the
operator's live state. Tests must never reach real state, and an import
must never have a side effect.

The module is exercised through a COPY placed in a temporary repository
layout, because its paths derive from ``__file__`` rather than from
``HOME``: ``PA_ROOT = Path(__file__).resolve().parent.parent``. Copying it
is therefore the only way to give the assertions a log path that is safe
to watch. ``HOME`` is pinned as well so nothing else in the child process
can reach the real tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
GUARD_SOURCE = PROJECT_ROOT / "scripts" / "_bulk_rewrite_guard.py"


def _staged_copy(
    tmp_path: Path,
    *,
    warning_only: bool = False,
    dangling_logs: bool = False,
) -> tuple[Path, Path, Path, Path]:
    """Copy the guard into ``tmp_path`` as ``<repo>/scripts/<module>.py``.

    Returns ``(scripts_dir, data_dir, expected_log_dir, expected_log_file)``.
    The log directory is deliberately NOT created: its appearance is one of
    the things the tests assert against.

    ``data/`` is created as a plain directory, never a git repository, so
    every ``git`` call the guard makes fails locally and instantly ("not a
    git repository") — no network, no remote, no real submodule.
    ``warning_only`` writes the rollback config so the guard logs its verdict
    and returns instead of calling ``sys.exit(2)``. ``dangling_logs``
    reproduces a fresh clone, where ``logs`` points into an uninitialised
    submodule and resolves to nothing.
    """
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(GUARD_SOURCE, scripts / GUARD_SOURCE.name)
    data = repo / "data"
    (data / "config").mkdir(parents=True)
    if warning_only:
        (data / "config" / "sync.json").write_text(
            json.dumps({"require_clean_origin_for_bulk": False}),
            encoding="utf-8",
        )
    log_dir = repo / "logs"
    if dangling_logs:
        log_dir.symlink_to(tmp_path / "uninitialised-submodule" / "logs")
    return scripts, data, log_dir, log_dir / "bulk-rewrite-guard.log"


def _run_child(
    program: str,
    scripts: Path,
    home: Path,
    *,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess:
    """Run *program* in a fresh interpreter and return the completed process."""
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home))
    result = subprocess.run(
        [sys.executable, "-c", program, str(scripts)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == expected_returncode, (
        f"exit {result.returncode}, expected {expected_returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result


def _report(result: subprocess.CompletedProcess) -> dict:
    """Parse the JSON report a child program prints as its last stdout line."""
    return json.loads(result.stdout.strip().splitlines()[-1])


# The guard's one public entry point, driven end to end. Tests that assert
# where the log lands must go through this rather than calling
# ``_configure_logging`` directly: it is the call an operator actually makes,
# and a fix that only works when the private helper is invoked by hand is not
# a fix (re-audit, 2026-09-08).
_ENSURE_PROGRAM = textwrap.dedent(
    """
    import importlib, json, sys
    sys.path.insert(0, sys.argv[1])
    guard = importlib.import_module("_bulk_rewrite_guard")
    guard.ensure_safe_to_rewrite("a synthetic bulk rewrite")
    print(json.dumps({"returned": True}))
    """
)

_ENSURE_UNDER_PYTEST = textwrap.dedent(
    """
    import importlib, json, sys, types
    sys.modules.setdefault("pytest", types.ModuleType("pytest"))
    sys.path.insert(0, sys.argv[1])
    guard = importlib.import_module("_bulk_rewrite_guard")
    guard.ensure_safe_to_rewrite("a synthetic bulk rewrite")
    print(json.dumps({"returned": True}))
    """
)


class TestImportSideEffects:
    """S22: importing the guard must create nothing."""

    def test_import_under_pytest_creates_no_log(self, tmp_path):
        """Kills hoisting the handler back to module scope.

        Restoring either import-time statement — the ``mkdir`` or the
        ``logging.FileHandler(LOG_FILE)`` — makes one of these assertions
        fail. Both are asserted, because the ``mkdir`` alone silently
        created a directory inside the private submodule even on the runs
        where pytest's root handler happened to render ``basicConfig``
        inert.
        """
        scripts, _data, log_dir, log_file = _staged_copy(tmp_path)
        program = textwrap.dedent(
            """
            import importlib, json, logging, sys, types
            # Stand in for pytest so the module takes its under-test branch.
            sys.modules.setdefault("pytest", types.ModuleType("pytest"))
            sys.path.insert(0, sys.argv[1])
            guard = importlib.import_module("_bulk_rewrite_guard")
            handlers = [
                getattr(h, "baseFilename", None)
                for h in logging.getLogger().handlers
            ]
            print(json.dumps({
                "log_file": str(guard.LOG_FILE),
                "file_handlers": [h for h in handlers if h],
            }))
            """
        )
        report = _report(_run_child(program, scripts, tmp_path / "home"))

        assert report["log_file"] == str(log_file)
        assert not log_file.exists(), (
            "importing the guard under pytest opened its log file"
        )
        assert not log_dir.exists(), (
            "importing the guard under pytest created the log directory"
        )
        assert report["file_handlers"] == [], (
            f"a file handler was installed at import: {report['file_handlers']}"
        )

    def test_import_outside_pytest_creates_no_log_either(self, tmp_path):
        """The same assertion without the pytest stand-in.

        The fix is laziness, not a pytest special case: a plain script that
        imports the guard and never calls it must not touch the log either.
        Kills moving ``_configure_logging()`` back to module scope.
        """
        scripts, _data, log_dir, log_file = _staged_copy(tmp_path)
        program = textwrap.dedent(
            """
            import importlib, json, sys
            sys.path.insert(0, sys.argv[1])
            guard = importlib.import_module("_bulk_rewrite_guard")
            print(json.dumps({"log_file": str(guard.LOG_FILE)}))
            """
        )
        report = _report(_run_child(program, scripts, tmp_path / "home"))

        assert report["log_file"] == str(log_file)
        assert not log_file.exists()
        assert not log_dir.exists()

    def test_the_handler_is_attached_on_first_use(self, tmp_path):
        """Kills deleting the file handler rather than deferring it.

        The guard's log is the audit trail for every bulk rewrite of the
        canonical store, so "never opened" is not an acceptable fix. Outside
        pytest, the first call to ``_configure_logging`` must create the
        directory and the file.
        """
        scripts, _data, log_dir, log_file = _staged_copy(tmp_path)
        program = textwrap.dedent(
            """
            import importlib, json, logging, sys
            sys.path.insert(0, sys.argv[1])
            guard = importlib.import_module("_bulk_rewrite_guard")
            created_at_import = guard.LOG_FILE.exists()
            guard._configure_logging()
            guard.logger.info("a synthetic guard invocation")
            handlers = [
                getattr(h, "baseFilename", None)
                for h in logging.getLogger().handlers
            ]
            print(json.dumps({
                "created_at_import": created_at_import,
                "file_handlers": [h for h in handlers if h],
            }))
            """
        )
        report = _report(_run_child(program, scripts, tmp_path / "home"))

        assert report["created_at_import"] is False
        assert log_dir.is_dir(), "the first guard call did not create logs/"
        assert log_file.exists(), "the first guard call did not open the log"
        assert report["file_handlers"] == [str(log_file)]
        assert "a synthetic guard invocation" in log_file.read_text(
            encoding="utf-8"
        )


class TestFreshCloneBehaviour:
    """What the guard does when ``logs`` resolves to nothing.

    Driven through ``ensure_safe_to_rewrite`` — the call an operator
    actually makes. The child runs offline: ``data/`` is a plain directory,
    so each ``git`` call fails locally with "not a git repository" and no
    remote is ever contacted.
    """

    def test_a_dangling_logs_symlink_aborts_instead_of_crashing(self, tmp_path):
        """Kills removing either OSError guard (re-audit, 2026-09-08).

        On a fresh clone ``logs`` points into an uninitialised ``data``
        submodule and resolves to nothing. ``mkdir(exist_ok=True)`` does NOT
        absorb that — the directory entry exists but is not a directory — so
        it raises ``FileExistsError``. Both places that ran it were
        unprotected until this round: the logging setup (fixed with S22) and
        ``_acquire_lock``, which killed every bulk-rewrite script with a
        traceback from inside the guard, in place of the guard's own refusal.

        Enforcing config here, so the correct outcome is a clean abort:
        exit 2, the guard's own message, and no traceback.
        """
        scripts, _data, log_dir, log_file = _staged_copy(
            tmp_path, dangling_logs=True
        )
        result = _run_child(
            _ENSURE_PROGRAM, scripts, tmp_path / "home", expected_returncode=2
        )

        assert "Traceback" not in result.stderr, (
            f"the guard crashed instead of refusing:\n{result.stderr}"
        )
        # The stderr fallback handler was installed, so the audit trail is
        # degraded rather than lost.
        assert "Could not open the sync lock" in result.stderr
        assert "guard failed — aborting" in result.stderr
        # And nothing was conjured at the dangling target.
        assert log_dir.is_symlink()
        assert not log_dir.exists(), "the dangling symlink was resolved"
        assert not log_file.exists()
