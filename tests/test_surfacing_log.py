"""
Tests for scripts/surfacing_log.py — per-memory surfacing logger
(earned-utility value signal, item 16, Stage 1).

Covers the pure line formatter, rank assignment / id-less skipping, the
best-effort write contract (a logging failure must never raise), and the
CLI ``--ids`` path used by the ``/recall`` command. A round-trip parity
test (logger output parses cleanly via the aggregator's parser) lives in
``test_surfacing_stats.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# Underscore module name — importable directly once scripts/ is on the path.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import surfacing_log  # noqa: E402


FIXED_NOW = datetime(2026, 6, 6, 9, 15, 0, tzinfo=timezone.utc)


# ============================================================================
# format_surfacing_line — pure formatter
# ============================================================================


def test_format_line_shape() -> None:
    """A formatted line is tab-separated, five fields, newline-terminated."""
    line = surfacing_log.format_surfacing_line(
        "2026-06-06-abc123", "digest", 1, None, now=FIXED_NOW
    )
    assert line.endswith("\n")
    fields = line.rstrip("\n").split("\t")
    assert fields == [
        FIXED_NOW.isoformat(),
        "id=2026-06-06-abc123",
        "path=digest",
        "rank=1",
        "session=-",
    ]


def test_format_line_session_passthrough() -> None:
    """A provided session id is recorded; an empty one degrades to ``-``."""
    with_sess = surfacing_log.format_surfacing_line(
        "id1", "recall", 2, "sess-42", now=FIXED_NOW
    )
    assert "session=sess-42" in with_sess
    blank = surfacing_log.format_surfacing_line("id1", "recall", 2, "", now=FIXED_NOW)
    assert "session=-" in blank


def test_format_line_non_numeric_rank_degrades() -> None:
    """A non-numeric rank becomes ``-`` rather than raising."""
    line = surfacing_log.format_surfacing_line("id1", "fetch", "x", None, now=FIXED_NOW)
    assert "rank=-" in line


def test_format_line_sanitises_embedded_whitespace() -> None:
    """Embedded tabs/newlines in a field cannot forge a column."""
    line = surfacing_log.format_surfacing_line(
        "bad\tid\nhere", "digest", 1, None, now=FIXED_NOW
    )
    # Exactly five tab-separated fields survive the sanitisation.
    assert len(line.rstrip("\n").split("\t")) == 5
    assert "id=bad id here" in line


# ============================================================================
# iter_surfacing_lines — rank assignment + id-less skipping
# ============================================================================


def test_iter_ranks_are_one_based_in_order() -> None:
    """Entries are ranked 1, 2, 3 … in surfaced order."""
    mems = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    lines = surfacing_log.iter_surfacing_lines(mems, "digest", now=FIXED_NOW)
    ranks = [ln.split("\trank=")[1].split("\t")[0] for ln in lines]
    assert ranks == ["1", "2", "3"]


def test_iter_skips_id_less_without_consuming_rank() -> None:
    """An entry with no id is skipped and does not consume a rank slot."""
    mems = [{"id": "a"}, {"no_id": 1}, {"id": "c"}]
    lines = surfacing_log.iter_surfacing_lines(mems, "fetch", now=FIXED_NOW)
    assert len(lines) == 2
    ids = [ln.split("\tid=")[1].split("\t")[0] for ln in lines]
    ranks = [ln.split("\trank=")[1].split("\t")[0] for ln in lines]
    assert ids == ["a", "c"]
    assert ranks == ["1", "2"]  # contiguous — the skip did not leave a gap


def test_iter_empty_and_none() -> None:
    """Empty list and None both yield no lines."""
    assert surfacing_log.iter_surfacing_lines([], "digest", now=FIXED_NOW) == []
    assert surfacing_log.iter_surfacing_lines(None, "digest", now=FIXED_NOW) == []


def test_iter_ignores_non_dict_entries() -> None:
    """A stray non-dict entry is skipped, not crashed on."""
    mems = [{"id": "a"}, "not-a-dict", {"id": "b"}]
    lines = surfacing_log.iter_surfacing_lines(mems, "recall", now=FIXED_NOW)
    assert len(lines) == 2


# ============================================================================
# log_surfaced — best-effort writer
# ============================================================================


def test_log_surfaced_appends_and_counts(tmp_path: Path) -> None:
    """Writes one line per id and returns the count."""
    log = tmp_path / "surfaced.log"
    n = surfacing_log.log_surfaced(
        [{"id": "a"}, {"id": "b"}], "digest", log_path=log, now=FIXED_NOW
    )
    assert n == 2
    assert log.read_text(encoding="utf-8").count("\n") == 2


def test_log_surfaced_appends_not_overwrites(tmp_path: Path) -> None:
    """A second call appends rather than truncating."""
    log = tmp_path / "surfaced.log"
    surfacing_log.log_surfaced([{"id": "a"}], "digest", log_path=log, now=FIXED_NOW)
    surfacing_log.log_surfaced([{"id": "b"}], "fetch", log_path=log, now=FIXED_NOW)
    assert log.read_text(encoding="utf-8").count("\n") == 2


def test_log_surfaced_creates_parent_dir(tmp_path: Path) -> None:
    """A missing logs directory is created on first write."""
    log = tmp_path / "nested" / "dir" / "surfaced.log"
    n = surfacing_log.log_surfaced([{"id": "a"}], "recall", log_path=log, now=FIXED_NOW)
    assert n == 1
    assert log.exists()


def test_log_surfaced_empty_returns_zero(tmp_path: Path) -> None:
    """Empty / None input writes nothing and returns 0 (no file created)."""
    log = tmp_path / "surfaced.log"
    assert surfacing_log.log_surfaced([], "digest", log_path=log) == 0
    assert surfacing_log.log_surfaced(None, "digest", log_path=log) == 0
    assert not log.exists()


def test_log_surfaced_never_raises_on_unwritable(tmp_path: Path) -> None:
    """A write to an impossible path returns 0, never raises."""
    # A path whose 'parent' is an existing file cannot be a directory.
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    log = blocker / "surfaced.log"
    assert surfacing_log.log_surfaced([{"id": "a"}], "digest", log_path=log) == 0


# ============================================================================
# main — the /recall CLI path (--ids splitting)
# ============================================================================


def test_cli_ids_split_on_whitespace_and_commas(
    tmp_path: Path, monkeypatch
) -> None:
    """``--ids`` accepts whitespace and/or comma separators."""
    log = tmp_path / "surfaced.log"
    monkeypatch.setenv(surfacing_log.LOG_PATH_ENV, str(log))
    monkeypatch.setattr(
        sys, "argv", ["surfacing_log.py", "--path", "recall", "--ids", "a, b  c"]
    )
    surfacing_log.main()
    body = log.read_text(encoding="utf-8")
    assert body.count("\n") == 3
    assert "path=recall" in body
    for want in ("id=a", "id=b", "id=c"):
        assert want in body


def test_cli_empty_ids_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    """An empty ``--ids`` (zero-match recall) writes no lines."""
    log = tmp_path / "surfaced.log"
    monkeypatch.setenv(surfacing_log.LOG_PATH_ENV, str(log))
    monkeypatch.setattr(sys, "argv", ["surfacing_log.py", "--ids", ""])
    surfacing_log.main()
    assert not log.exists()


# ============================================================================
# Audit S22 — the shipped destination is lazy, and dormant under pytest
#
# ``SHIPPED_LOG_PATH`` derives from ``__file__``, not from ``HOME``, so the
# suite's own home cannot contain it: exercising the session-start retrieval
# hook appended rows to the operator's real ``logs/surfaced.log`` — inside
# the private ``data`` submodule, and inside the evidence base a future
# archival decision is meant to rest on. The module is exercised through a
# COPY in a temporary repository layout, because that is the only way to
# give these assertions a shipped path that is safe to watch.
# ============================================================================

MODULE_SOURCE = Path(__file__).resolve().parent.parent / "scripts" / "surfacing_log.py"


def _staged_copy(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Copy the logger into ``<tmp>/repo/scripts/`` for a child to import.

    Returns ``(scripts_dir, expected_log_dir, expected_log_file)``. Neither
    the log directory nor the file is created here: their appearance is
    exactly what these tests assert about.
    """
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(MODULE_SOURCE, scripts / MODULE_SOURCE.name)
    log_dir = repo / "logs"
    return scripts, log_dir, log_dir / "surfaced.log"


def _run_child(program: str, scripts: Path, home: Path) -> dict:
    """Run *program* in a fresh interpreter; return its JSON last line.

    ``HOME`` is pinned to a directory inside the test's own tmp tree and
    ``PA_SURFACED_LOG`` is cleared, so the child resolves the destination
    the way production does and can reach nothing of the operator's.
    """
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home))
    env.pop("PA_SURFACED_LOG", None)
    result = subprocess.run(
        [sys.executable, "-c", program, str(scripts)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


#: Stand in for pytest so the child takes the under-test branch.
_PYTEST_STUB = (
    'import sys, types\n'
    'sys.modules.setdefault("pytest", types.ModuleType("pytest"))\n'
)

#: Surface two memories through the module's public entry point, exactly as
#: the retrieval hook and ``fetch-memories.py`` do — no ``log_path``.
_SURFACE = textwrap.dedent(
    """
    import importlib, json, sys
    sys.path.insert(0, sys.argv[1])
    mod = importlib.import_module("surfacing_log")
    written = mod.log_surfaced([{"id": "a"}, {"id": "b"}], "digest")
    print(json.dumps({
        "written": written,
        "default": str(mod.default_log_path()),
        "shipped": str(mod.SHIPPED_LOG_PATH),
    }))
    """
)


def test_import_alone_creates_nothing(tmp_path: Path) -> None:
    """Importing the module must not create the log, or its directory.

    Kills hoisting the destination back to an import-time constant that
    opens or mkdirs anything, and any `mkdir` moved above the resolution.
    """
    scripts, log_dir, log_file = _staged_copy(tmp_path)
    program = textwrap.dedent(
        """
        import importlib, json, sys
        sys.path.insert(0, sys.argv[1])
        mod = importlib.import_module("surfacing_log")
        print(json.dumps({"shipped": str(mod.SHIPPED_LOG_PATH)}))
        """
    )
    report = _run_child(_PYTEST_STUB + program, scripts, tmp_path / "home")

    assert report["shipped"] == str(log_file)
    assert not log_file.exists(), "importing the logger opened its log file"
    assert not log_dir.exists(), "importing the logger created logs/"


def test_an_unpinned_call_under_pytest_writes_nothing(tmp_path: Path) -> None:
    """S22: the hook's own call, under pytest, must reach no file.

    The mutation this kills: ``target = log_path or SHIPPED_LOG_PATH`` in
    :func:`surfacing_log.log_surfaced` — the line as it stood, which wrote
    a live-looking row into the operator's private ``data`` submodule
    every time a test exercised the retrieval hook.
    """
    scripts, log_dir, log_file = _staged_copy(tmp_path)
    report = _run_child(_PYTEST_STUB + _SURFACE, scripts, tmp_path / "home")

    assert report["default"] == "None"
    assert report["written"] == 0
    assert not log_file.exists(), "an unpinned call under pytest wrote the log"
    assert not log_dir.exists(), "an unpinned call under pytest created logs/"


def test_the_production_path_still_writes(tmp_path: Path) -> None:
    """Laziness must not cost the instrumentation its production write.

    No pytest in ``sys.modules``, nothing pinned: the same unpinned call
    the hook makes lands two lines in ``<repo>/logs/surfaced.log``. Kills
    a "fix" that simply stops writing.
    """
    scripts, _log_dir, log_file = _staged_copy(tmp_path)
    report = _run_child(_SURFACE, scripts, tmp_path / "home")

    assert report["default"] == str(log_file)
    assert report["written"] == 2
    body = log_file.read_text(encoding="utf-8")
    assert body.count("\n") == 2
    assert "id=a" in body and "id=b" in body


def test_the_environment_override_wins_under_pytest(tmp_path: Path) -> None:
    """A test that pins the destination gets the writer, in full."""
    scripts, _log_dir, shipped = _staged_copy(tmp_path)
    pinned = tmp_path / "pinned" / "surfaced.log"
    program = textwrap.dedent(
        """
        import importlib, json, os, sys
        os.environ["PA_SURFACED_LOG"] = sys.argv[2]
        sys.path.insert(0, sys.argv[1])
        mod = importlib.import_module("surfacing_log")
        written = mod.log_surfaced([{"id": "a"}], "recall")
        print(json.dumps({"written": written}))
        """
    )
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home))
    env.pop("PA_SURFACED_LOG", None)
    result = subprocess.run(
        [sys.executable, "-c", _PYTEST_STUB + program, str(scripts), str(pinned)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    assert json.loads(result.stdout.strip().splitlines()[-1])["written"] == 1
    assert "id=a" in pinned.read_text(encoding="utf-8")
    assert not shipped.exists(), "the pinned run also wrote the shipped path"


def test_in_this_suite_the_default_is_dormant() -> None:
    """The property the whole suite depends on, asserted in process.

    Every unpinned ``log_surfaced`` call made by any test — the retrieval
    hook's digest, ``fetch-memories.py`` — resolves to nothing while
    pytest is imported. Pure: it opens no file to prove it.
    """
    assert "pytest" in sys.modules
    assert os.environ.get(surfacing_log.LOG_PATH_ENV) in (None, "")
    assert surfacing_log.default_log_path() is None
    assert surfacing_log.log_surfaced([{"id": "a"}], "digest") == 0
