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

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import INTEGRATION_MARKER

REPO_CONFTEST = Path(__file__).resolve().parent / "conftest.py"

#: A conftest that re-exports only the fixture under test, so the child
#: run gets the real code without the rest of the suite's fixtures.
#:
#: Importing it also repoints the child's HOME at a temporary directory
#: of its own, exactly as the real suite does, so the watched file has to
#: be seeded AFTERWARDS — and before the guard takes its first snapshot,
#: which is why it happens here at conftest import time rather than in
#: the probe.
_CHILD_CONFTEST = '''
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "pa_conftest", r"{conftest}",
)
module = importlib.util.module_from_spec(spec)
sys.modules["pa_conftest"] = module
spec.loader.exec_module(module)

no_real_cache_writes = module.no_real_cache_writes

cache = Path(os.environ["HOME"]) / ".cache"
cache.mkdir(parents=True, exist_ok=True)
(cache / "postgres-sync-memories-gate").write_text("0\\n", encoding="utf-8")
'''


def _run_probe(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Run one probe test under the real fixture, in a child pytest run.

    ``body`` is the probe's function body. The child's conftest repoints
    HOME the way the real suite does and seeds one watched file there, so
    the probe writes to ``os.environ["HOME"]`` and never goes near the
    operator's home — nor this process's.
    """
    home = tmp_path / "home"
    home.mkdir(parents=True)

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

    The mutations this kills: deleting any one glob — for instance
    ``index-session-content-*``, which covers the refusal memory that
    leaked into the real cache once already — and narrowing
    ``postgres-sync-*`` to ``postgres-sync-*-gate``, which quietly stops
    watching the sidecars where the gates' state actually lives.
    """
    representatives = (
        "postgres-sync-memories-gate",
        # The sidecar is a separate file with a separate name, and the
        # gate's own state lives in it: a glob narrowed to "*-gate" stops
        # watching it while still looking watchful (ninth re-audit, low).
        "postgres-sync-sessions-gate.state.json",
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


# ---------------------------------------------------------------------------
# Ninth re-audit, finding M5 — the guard measured a directory other
# processes write, and could only ever catch a leak after the damage
# ---------------------------------------------------------------------------


def test_the_suite_runs_in_a_home_of_its_own():
    """
    Watching the operator's home made the guard wrong both ways: after
    merge, cron rewrites the memories gate every five minutes, so a full
    run would fail at random and blame the suite for it; and a leak could
    only be noticed once the real file had already been damaged.

    The mutation this kills: removing the import-time repoint in
    conftest.py — every gate constant then resolves to the operator's
    ~/.cache again.
    """
    import conftest

    home = Path(os.environ["HOME"])

    assert conftest.REAL_HOME is None or home != Path(conftest.REAL_HOME), (
        "the suite is running in the operator's home"
    )
    assert home == Path.home(), "Path.home() disagrees with $HOME"
    assert home.is_dir()
    assert (home / ".cache").is_dir()


def test_the_suite_home_carries_a_git_identity():
    """
    Several tests build throwaway repositories and commit in them, which
    needs a user.email from somewhere. Borrowing the operator's would put
    their name on test commits; having none makes git refuse outright.
    """
    config = (Path(os.environ["HOME"]) / ".gitconfig").read_text(
        encoding="utf-8",
    )
    assert "email = " in config
    assert "name = " in config


def test_the_gate_constants_resolve_inside_the_suite_home():
    """
    The property the repoint exists for: a script's module-level gate
    paths are baked from ``Path.home()`` when it is imported, so the
    repoint has to happen before any of that — which is why it is at
    conftest import time and not in a fixture. The mutation this kills:
    moving it into a fixture, however early.
    """
    import sys

    sys.path.insert(
        0, str(Path(__file__).resolve().parent.parent / "scripts"),
    )
    import _sync_gate

    home = Path(os.environ["HOME"])
    for gate in _sync_gate.ALL_GATES:
        assert home in gate.parents, (
            f"{gate} was resolved against a different home — the repoint "
            f"came too late to matter"
        )


def test_the_watched_directory_is_the_suite_home():
    """
    The guard has to measure the directory the suite can actually write,
    or it is watching one thing and protecting another.
    """
    import conftest

    snapshot_root = Path.home() / ".cache"
    assert snapshot_root == Path(os.environ["HOME"]) / ".cache"
    # And the guard reads it at call time, so it follows the repoint.
    probe = snapshot_root / "postgres-sync-hermeticity-probe"
    probe.write_text("0\n", encoding="utf-8")
    try:
        assert str(probe) in conftest._pipeline_cache_snapshot()
    finally:
        probe.unlink()


# ---------------------------------------------------------------------------
# Tenth re-audit, finding M5 — a suite that reaches a live resource is not
# a suite, it is a probe of whether a service happens to be up
# ---------------------------------------------------------------------------


def _live_resource_calls(source: str) -> list[str]:
    """Test functions that open a real connection without the marker.

    Looks for a CALL to ``connect`` on something named psycopg2 — the
    mocked uses pass the name as a string to ``patch`` and so are not
    calls at all — and requires the enclosing test, or its class, to
    carry ``@pytest.mark.<INTEGRATION_MARKER>``.

    The marker is matched STRUCTURALLY, against the constant ``pytest.ini``
    is checked against, not by looking for the word anywhere in the
    decorator's source: a substring test excused
    ``@pytest.mark.skipif(reason="integration coming later")`` — a
    decorator that grants no deselection at all — and would have gone on
    excusing it after a rename (eleventh re-audit follow-up L1).
    """
    import ast

    def marked(node) -> bool:
        for decorator in getattr(node, "decorator_list", []):
            # ``@pytest.mark.integration`` and its called form
            # ``@pytest.mark.integration(...)`` both count; nothing else does.
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(target, ast.Attribute)
                and target.attr == INTEGRATION_MARKER
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "mark"
            ):
                return True
        return False

    offenders: list[str] = []
    tree = ast.parse(source)
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.Module, ast.ClassDef)):
            continue
        for node in getattr(parent, "body", []):
            if not (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            ):
                continue
            if marked(node) or (
                isinstance(parent, ast.ClassDef) and marked(parent)
            ):
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "connect"
                    and "psycopg2" in ast.unparse(func.value)
                ):
                    offenders.append(f"{node.name}:{call.lineno}")
    return offenders


def test_no_test_opens_a_real_database_without_the_marker():
    """
    ``pytest.ini`` deselects ``integration``, so a live-resource test
    must carry that marker or it runs on every plain ``pytest``. One did:
    it connected to the operator's ``claude_memories`` on every run, and
    a test with credentials in reach can do more than read.

    The mutation this kills: removing the marker from
    ``test_live_pg_assertion_passes``.
    """
    tests_dir = Path(__file__).resolve().parent
    offenders: dict[str, list[str]] = {}
    for module in sorted(tests_dir.glob("test_*.py")):
        found = _live_resource_calls(module.read_text(encoding="utf-8"))
        if found:
            offenders[module.name] = found
    assert not offenders, (
        f"these tests open a real database on a plain run: {offenders}"
    )


def test_the_guard_would_see_an_unmarked_connection():
    """The guard itself, against a fixture of the shape it is looking for."""
    unmarked = (
        "import psycopg2\n"
        "def test_thing():\n"
        "    conn = psycopg2.connect(dbname='claude_memories')\n"
    )
    assert _live_resource_calls(unmarked)

    on_the_function = (
        "import psycopg2\n"
        "@pytest.mark.integration\n"
        "def test_thing():\n"
        "    conn = psycopg2.connect(dbname='claude_memories')\n"
    )
    assert _live_resource_calls(on_the_function) == []

    on_the_class = (
        "import psycopg2\n"
        "@pytest.mark.integration\n"
        "class TestThing:\n"
        "    def test_thing(self):\n"
        "        conn = psycopg2.connect(dbname='claude_memories')\n"
    )
    assert _live_resource_calls(on_the_class) == []

    patched = (
        "def test_thing():\n"
        "    with patch('psycopg2.connect', side_effect=Boom):\n"
        "        pass\n"
    )
    assert _live_resource_calls(patched) == []

    # The marker name under some other attribute is not the marker
    # (re-audit L3: `@helpers.integration` deselects nothing).
    other_owner = (
        "import psycopg2\n"
        "@helpers.integration\n"
        "def test_thing():\n"
        "    conn = psycopg2.connect(dbname='claude_memories')\n"
    )
    assert _live_resource_calls(other_owner)

    # A decorator that merely mentions the word grants no deselection, so
    # it must not excuse the connection either (follow-up L1).
    merely_mentions = (
        "import psycopg2\n"
        '@pytest.mark.skipif(False, reason="integration coming later")\n'
        "def test_thing():\n"
        "    conn = psycopg2.connect(dbname='claude_memories')\n"
    )
    assert _live_resource_calls(merely_mentions)


def test_the_marker_name_matches_pytest_ini():
    """The guard's marker and the deselection must be the same word.

    ``INTEGRATION_MARKER`` is only worth having if it is the name pytest
    actually acts on: a rename in ``pytest.ini`` that left the constant
    behind would deselect nothing while the guard reported every
    live-resource test as properly quarantined.

    The mutation this kills: changing either the constant or the
    ``pytest.ini`` marker without changing the other.
    """
    ini = (Path(__file__).resolve().parent.parent / "pytest.ini").read_text(
        encoding="utf-8"
    )
    assert f'-m "not {INTEGRATION_MARKER}"' in ini, (
        f"pytest.ini does not deselect {INTEGRATION_MARKER!r}: {ini}"
    )
    assert f"\n    {INTEGRATION_MARKER}:" in ini, (
        f"pytest.ini does not register {INTEGRATION_MARKER!r}: {ini}"
    )


def test_a_set_xdg_cache_home_does_not_move_the_suite_cache(tmp_path):
    """
    The scripts write gates under ``~/.cache`` directly, but anything
    reading XDG_CACHE_HOME would follow it out of the suite's home and
    straight back into the operator's — with the guard watching the
    directory nobody was writing. conftest drops the variable when it
    repoints HOME; this is the test that says so.

    The mutation this kills: removing the ``os.environ.pop`` of
    XDG_CACHE_HOME.
    """
    stray = tmp_path / "stray-cache"
    stray.mkdir()

    work = tmp_path / "child"
    work.mkdir()
    (work / "conftest.py").write_text(
        _CHILD_CONFTEST.format(conftest=REPO_CONFTEST), encoding="utf-8",
    )
    (work / "test_probe.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def test_probe():\n"
        '    assert "XDG_CACHE_HOME" not in os.environ, (\n'
        '        "the suite inherited a cache directory outside its home"\n'
        "    )\n"
        '    assert Path(os.environ["HOME"]) in (\n'
        '        Path.home() / ".cache"\n'
        "    ).parents\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         "-p", "no:cacheprovider", str(work)],
        capture_output=True, text=True, cwd=str(work),
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": os.environ["PATH"],
            "XDG_CACHE_HOME": str(stray),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )

    assert result.returncode == 0, result.stdout
    assert not any(stray.iterdir()), (
        "the child run wrote into a cache directory outside its home"
    )


# ===========================================================================
# The runtime net under the static database guard
#
# The AST scan above names a TEST that calls psycopg2.connect itself. It
# cannot see a test that calls production code which connects — and during
# audit round 4a a new surgical UPDATE in tag-gardening did exactly that,
# opening the operator's live claude_memories from a plain unit test. The
# conftest fixture ``no_live_postgres`` is the runtime net; this pins it.
# ===========================================================================


def test_the_runtime_guard_refuses_a_real_connection():
    """A non-integration test cannot reach the live server.

    The mutation this kills: deleting the ``no_live_postgres`` fixture from
    ``conftest.py``. The connector is fetched through ``getattr`` so the
    static scan above does not read this test as an offender itself.
    """
    import psycopg2

    connector = getattr(psycopg2, "connect")
    with pytest.raises(AssertionError, match="real PostgreSQL connection"):
        connector(dbname="claude_memories")


def test_a_test_may_still_patch_the_connector():
    """A test's own patch wins over the guard, so fakes keep working."""
    import psycopg2

    sentinel = object()
    with patch("psycopg2.connect", return_value=sentinel):
        assert getattr(psycopg2, "connect")() is sentinel


# ===========================================================================
# The canonical-store half of the hermeticity guard
#
# Audit 2026-09-08, round 4a, finding B4. The guard watched ~/.cache only, so
# a test that forgot to patch a module's path constant rewrote the REAL
# data/memories/memories.jsonl and the suite stayed green (reproduced in a
# copy). conftest now snapshots the canonical files and the log directory,
# resolved through the root symlinks.
# ===========================================================================


import conftest  # noqa: E402


def test_the_store_guard_sees_a_write_through_the_symlink(tmp_path,
                                                          monkeypatch):
    """Writing via the symlink and via the real path are the same event.

    The mutation this kills: dropping ``.resolve()`` from the snapshot, which
    would let a test that writes ``data/memories/memories.jsonl`` slip past a
    guard watching ``memories/memories.jsonl``.
    """
    real_dir = tmp_path / "data" / "memories"
    real_dir.mkdir(parents=True)
    canonical = real_dir / "memories.jsonl"
    link_dir = tmp_path / "memories"
    link_dir.symlink_to(real_dir)

    monkeypatch.setattr(
        conftest, "_CANONICAL_FILES", (link_dir / "memories.jsonl",))
    monkeypatch.setattr(conftest, "_CANONICAL_DIRS", ())

    before = conftest._canonical_store_snapshot()
    assert before == {str(canonical): None}, "an absent file records as None"

    # Written through the REAL path; watched through the SYMLINK.
    canonical.write_text('{"id": "2031-01-01-aaaabbbbcccc"}\n',
                         encoding="utf-8")
    after_create = conftest._canonical_store_snapshot()
    assert after_create != before, "a created canonical must be flagged"

    canonical.write_text('{"id": "2031-01-01-aaaabbbbcccc"}\n{"id": "b"}\n',
                         encoding="utf-8")
    assert conftest._canonical_store_snapshot() != after_create, (
        "a rewritten canonical must be flagged")

    canonical.unlink()
    assert conftest._canonical_store_snapshot() == before, (
        "a deleted canonical must be flagged as a change from present")


def test_the_store_guard_watches_the_log_directory(tmp_path, monkeypatch):
    """A stray log file in the real logs/ is flagged too.

    The mutation this kills: dropping ``_CANONICAL_DIRS`` from the snapshot.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(conftest, "_CANONICAL_FILES", ())
    monkeypatch.setattr(conftest, "_CANONICAL_DIRS", (logs,))

    before = conftest._canonical_store_snapshot()
    (logs / "tag-gardening.log").write_text("stray entry\n", encoding="utf-8")
    assert conftest._canonical_store_snapshot() != before


# ===========================================================================
# The store guard's own failure path (audit 2026-09-08, round 4a-2, M5)
#
# The snapshot function was covered; the ASSERTION was not. A guard whose
# failure path never executes is a guard nobody has checked: neutering
# `assert not touched`, emptying _CANONICAL_FILES, or dropping mtime from the
# snapshot tuple all left the suite green. These run the guard's own logic
# against a throwaway tree, in-process.
# ===========================================================================




@pytest.fixture
def strict_hermeticity(monkeypatch):
    """Run the source-tree half of the guard in fail-fast mode.

    Round 4a-3 addendum: a change under wiki/, scripts/, and friends is
    ADVISORY in a shared checkout, because several sessions work this
    repository at once and a two-minute run routinely straddles someone
    else's edit. Failing on it blames the suite for another session's work.
    A clean copy sets PA_HERMETICITY_STRICT=1, and so do these tests, which
    is where a test that really did write to the checkout is caught.
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")

def _throwaway_store(tmp_path, monkeypatch):
    """A tree shaped like the repo: data/memories + logs, reached by symlink."""
    real_dir = tmp_path / "data" / "memories"
    real_dir.mkdir(parents=True)
    logs_dir = tmp_path / "data" / "logs"
    logs_dir.mkdir(parents=True)
    corpus = real_dir / "memories.jsonl"
    vocabulary = real_dir / "tag-vocabulary.txt"
    corpus.write_text('{"id": "2031-01-01-aaaabbbbcccc"}\n', encoding="utf-8")
    vocabulary.write_text("kiln\nrecording\n", encoding="utf-8")
    (tmp_path / "memories").symlink_to(real_dir)
    (tmp_path / "logs").symlink_to(logs_dir)

    monkeypatch.setattr(conftest, "_CANONICAL_FILES", (
        tmp_path / "memories" / "memories.jsonl",
        tmp_path / "memories" / "tag-vocabulary.txt",
    ))
    monkeypatch.setattr(conftest, "_CANONICAL_DIRS", (tmp_path / "logs",))
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS", (tmp_path / "logs",))
    return corpus, vocabulary, logs_dir


def test_the_guard_raises_on_a_rewritten_canonical(tmp_path, monkeypatch):
    """The assertion itself must fire, not merely the snapshot differ.

    The mutation this kills: neutering ``assert not touched`` in
    ``assert_canonical_store_untouched`` (to ``assert True``, or deleting
    it), which would let every stray write through while the run stayed
    green.
    """
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    conftest.assert_canonical_store_untouched(before, before)  # a no-op run

    corpus.write_text('{"id": "rewritten-by-a-careless-test"}\n',
                      encoding="utf-8")
    after = conftest._canonical_store_snapshot()

    with pytest.raises(AssertionError, match="canonical memory store"):
        conftest.assert_canonical_store_untouched(before, after)
    violations, appends, _tolerated = conftest.classify_store_changes(
        before, after)
    assert str(corpus.resolve()) in violations
    assert appends == [], "a rewrite is not an append"


def test_the_guard_raises_on_a_created_or_deleted_canonical(tmp_path,
                                                            monkeypatch):
    """Creation and deletion are changes too, because absence is recorded."""
    corpus, vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)
    vocabulary.unlink()

    before = conftest._canonical_store_snapshot()
    vocabulary.write_text("kiln\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())

    before = conftest._canonical_store_snapshot()
    corpus.unlink()
    with pytest.raises(AssertionError):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_the_store_guard_catches_a_same_size_rewrite(tmp_path, monkeypatch):
    """A rewrite that keeps the byte count must still be caught.

    The mutation this kills: dropping ``st_mtime_ns`` from the snapshot
    tuple. Size alone cannot see a record swapped for another of the same
    length — and a corrupting write is not obliged to change the length.
    """
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)
    original = corpus.read_text(encoding="utf-8")

    before = conftest._canonical_store_snapshot()
    replacement = '{"id": "2031-01-01-ZZZZYYYYXXXX"}\n'
    assert len(replacement) == len(original), "the fixture must be same-size"
    corpus.write_text(replacement, encoding="utf-8")
    # Pin an explicitly different mtime so the test cannot pass by accident
    # of clock resolution, nor fail by two writes landing in one tick.
    stat = corpus.stat()
    os.utime(corpus, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    with pytest.raises(AssertionError):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_the_watched_paths_name_the_canonical_files(tmp_path, monkeypatch):
    """_CANONICAL_FILES must actually name the store, and be non-empty.

    The mutation this kills: emptying ``_CANONICAL_FILES`` (or dropping
    ``_CANONICAL_DIRS``), which leaves the guard watching nothing and
    passing on every run.
    """
    names = {path.name for path in conftest._CANONICAL_FILES}
    assert names == {"memories.jsonl", "tag-vocabulary.txt"}
    assert all(
        path.parent.name == "memories" for path in conftest._CANONICAL_FILES)
    # Widened by the round 4a-2 addendum: instruction sources, task state,
    # and executable code are all clobberable and were all unwatched.
    assert {path.name for path in conftest._CANONICAL_DIRS} == {
        "logs", "tasks", "global-claude-md", "global-agent-guidance",
        "wiki", "commands", "hooks", "scripts", "tests",
    }

    # And the snapshot really visits each of them.
    _corpus, _vocabulary, logs_dir = _throwaway_store(tmp_path, monkeypatch)
    (logs_dir / "tag-gardening.log").write_text("entry\n", encoding="utf-8")
    snapshot = conftest._canonical_store_snapshot()
    assert str((tmp_path / "data" / "memories" / "memories.jsonl")) in snapshot
    assert str(
        (tmp_path / "data" / "memories" / "tag-vocabulary.txt")) in snapshot
    assert str((logs_dir / "tag-gardening.log")) in snapshot


def test_the_session_fixture_calls_the_store_assertion():
    """The fixture must still USE the guard, not merely have one available.

    Structural, like the live-resource scan above: extracting the assertion
    into a function makes its behaviour testable, but a mutation could then
    simply stop calling it from ``no_real_cache_writes``.
    """
    import ast

    source = Path(conftest.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fixture = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "no_real_cache_writes"
    )
    called = {
        ast.unparse(node.func) for node in ast.walk(fixture)
        if isinstance(node, ast.Call)
    }
    assert "store_findings" in called, (
        "the session fixture no longer checks the canonical store")
    assert "classify_store_changes" in called, (
        "the fixture must classify once and hand the result to both halves")
    assert "report_source_tree_changes" in called
    assert "_canonical_store_snapshot" in called


# ===========================================================================
# The two holes under the runtime PG net (audit round 4a-2, finding M8)
#
# Patching psycopg2.connect does not stop a module that bound the real
# function at import time with `from psycopg2 import connect`, and it does
# nothing at all for a script that shells out to psql. conftest closes both
# through the environment: PGHOST at an empty socket directory, and a stub
# psql first on PATH.
# ===========================================================================


#: Bound at MODULE import — that is, during collection, before any fixture
#: has run. This is exactly the shape of the hole: a production module doing
#: ``from psycopg2 import connect`` at import time holds the real driver
#: function, and patching the module attribute later cannot reach it.
from psycopg2 import OperationalError as _PG_OPERATIONAL_ERROR  # noqa: E402
from psycopg2 import connect as _IMPORT_BOUND_CONNECT  # noqa: E402


def test_an_import_bound_connector_cannot_reach_a_server():
    """`from psycopg2 import connect` must still fail to connect.

    The mutation this kills: dropping the PGHOST/PGPORT repoint from
    conftest. The fixture's attribute patch cannot help here -- this is the
    real driver function, bound before any fixture ran -- so the only thing
    standing between it and the operator's database is libpq's environment.
    """
    with pytest.raises(_PG_OPERATIONAL_ERROR) as excinfo:
        _IMPORT_BOUND_CONNECT(dbname="claude_memories")

    # libpq's message names the socket path it tried; assert it is the
    # suite's dead end, not a real server refusing us.
    assert conftest._NO_PG_SOCKET_DIR.name in str(excinfo.value), str(
        excinfo.value)


def test_the_pg_environment_points_nowhere():
    """PGHOST names an empty directory, and nothing overrides it."""
    assert os.environ["PGHOST"] == str(conftest._NO_PG_SOCKET_DIR)
    assert conftest._NO_PG_SOCKET_DIR.is_dir()
    assert not any(conftest._NO_PG_SOCKET_DIR.iterdir()), (
        "the dead-end socket directory must stay empty")
    assert "PGHOSTADDR" not in os.environ, (
        "PGHOSTADDR would take precedence over PGHOST")
    assert os.environ["PGPORT"] == "1"
    # A service file names a host, port, and database of its own, so an
    # inherited PGSERVICE would route straight past the dead end above
    # (round 4a-3, finding M6: deleting either pop stayed green).
    assert "PGSERVICE" not in os.environ, (
        "an inherited PGSERVICE would name a real host")
    assert "PGSERVICEFILE" not in os.environ, (
        "an inherited PGSERVICEFILE would name a real host")
    assert str(conftest._SUITE_HOME.name) in os.environ["PGHOST"], (
        "the dead end must live inside the suite's own home")


def test_a_script_shelling_out_to_psql_is_refused():
    """A stub psql is first on PATH and exits non-zero.

    The mutation this kills: dropping the PATH stub from conftest.
    monthly-archive.py and check-memory-drift.py reach PostgreSQL by
    subprocess, so psycopg2 patching never sees them.
    """
    resolved = shutil.which("psql")
    assert resolved is not None
    assert Path(resolved).parent == Path(conftest._STUB_BIN), (
        f"the real psql is first on PATH: {resolved}")

    result = subprocess.run(
        ["psql", "-t", "-A", "-c", "SELECT count(*) FROM memories"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert conftest.PSQL_STUB_MESSAGE in result.stderr
    assert result.stdout == ""


def test_the_stub_is_inherited_by_a_child_process():
    """A grandchild sees the stub too, so a script's own subprocess is covered."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import subprocess, sys;"
         "r = subprocess.run(['psql', '-c', 'select 1'],"
         " capture_output=True, text=True);"
         "sys.stdout.write(str(r.returncode)); sys.stderr.write(r.stderr)"],
        capture_output=True, text=True,
    )
    assert result.stdout == "1"
    assert conftest.PSQL_STUB_MESSAGE in result.stderr


# ===========================================================================
# The network guard (audit round 4a-2 addendum)
#
# Nothing watched sockets: a probe test stood up a local TCP server, connected
# to it, and passed with no complaint — which means an escaped httpx,
# pyzotero, urllib, or Slack call from any test would have reached the real
# internet. conftest now refuses by default, with a loopback-only opt-in.
# ===========================================================================


def test_an_unmarked_test_cannot_reach_a_listening_loopback_server():
    """Loopback ALONE does not open the door, even to a live listener.

    A server really is listening here, so the refusal cannot be an accident
    of nothing being there. This is the policy under test: allowing loopback
    unconditionally was rejected because this machine runs the operator's
    PostgreSQL and Ollama on 127.0.0.1, and a stray connection to either is
    exactly what the guard is for.

    The mutations this kills: dropping the ``no_network`` fixture, and
    relaxing the opt-in to "any loopback address" by removing the
    ``_ACTIVE_TEST["local_socket"]`` half of the condition.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))   # bind and listen are not guarded
    server.listen(1)
    port = server.getsockname()[1]
    try:
        with pytest.raises(AssertionError, match="refused by the test suite"):
            socket.create_connection(("127.0.0.1", port), timeout=1)
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(AssertionError, match="no network"):
                client.connect(("127.0.0.1", port))
        finally:
            client.close()
    finally:
        server.close()


def test_a_routable_connection_is_refused():
    """A real host is refused before any DNS or TCP work happens."""
    with pytest.raises(AssertionError, match="no network"):
        socket.create_connection(("api.zotero.org", 443), timeout=1)


def test_the_refusal_names_the_test_and_the_address():
    """A bare "no network" would not say where to look."""
    with pytest.raises(AssertionError) as excinfo:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            ("example.invalid", 80))
    message = str(excinfo.value)
    assert "test_the_refusal_names_the_test_and_the_address" in message
    assert "example.invalid" in message
    assert conftest.LOCAL_SOCKET_MARKER in message


def test_connect_ex_is_guarded_too():
    """``connect_ex`` needs its own wrapper.

    It returns an errno rather than raising, so an unguarded ``connect_ex``
    would connect and report success while the guarded ``connect`` beside it
    refused -- the kind of half-closed door that reads as covered.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(AssertionError, match="refused by the test suite"):
            sock.connect_ex(("127.0.0.1", 9))
    finally:
        sock.close()


@pytest.mark.local_socket
def test_a_marked_test_may_reach_a_server_it_owns():
    """The opt-in works, and only for loopback.

    A test that starts its own server must be able to talk to it; the marker
    is how it says so. The routable address at the end shows the opt-in does
    not become a blanket exemption.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.close()
    finally:
        server.close()

    with pytest.raises(AssertionError, match="no network"):
        socket.create_connection(("api.zotero.org", 443), timeout=1)


def test_the_marker_is_registered():
    """An unregistered marker is silently a no-op under --strict-markers."""
    ini = (Path(conftest.__file__).resolve().parent.parent / "pytest.ini")
    assert conftest.LOCAL_SOCKET_MARKER in ini.read_text(encoding="utf-8")


def test_zotero_data_dir_is_not_inherited():
    """A stray ZOTERO_DATA_DIR would point a test at the real library."""
    assert "ZOTERO_DATA_DIR" not in os.environ


# ===========================================================================
# The widened store guard (audit round 4a-2 addendum)
#
# The snapshot watched only memories.jsonl, tag-vocabulary.txt, and logs/. A
# probe test clobbered global-claude-md/claude.md — the source the composer
# reads — plus data/tasks/FOCUS.md and wiki/continuity.md, and stayed green.
# ===========================================================================


def _throwaway_checkout(tmp_path, monkeypatch):
    """A tree with the instruction, task, and code directories the guard watches."""
    (tmp_path / "data" / "tasks").mkdir(parents=True)
    (tmp_path / "tasks").symlink_to(tmp_path / "data" / "tasks")
    for name in ("global-claude-md", "wiki", "commands", "hooks", "scripts"):
        (tmp_path / name).mkdir()
    (tmp_path / "global-claude-md" / "claude.md").write_text(
        "# composed source\n", encoding="utf-8")
    (tmp_path / "data" / "tasks" / "FOCUS.md").write_text(
        "# Current Focus\n", encoding="utf-8")
    (tmp_path / "wiki" / "continuity.md").write_text(
        "# Continuity\n", encoding="utf-8")
    (tmp_path / "scripts" / "example.py").write_text(
        "print('hello')\n", encoding="utf-8")

    monkeypatch.setattr(conftest, "_CANONICAL_FILES", ())
    monkeypatch.setattr(conftest, "_CANONICAL_DIRS", tuple(
        tmp_path / name for name in (
            "tasks", "global-claude-md", "wiki", "commands", "hooks", "scripts")
    ))
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS", ())
    return tmp_path


@pytest.mark.parametrize("relative", [
    "global-claude-md/claude.md",
    "data/tasks/FOCUS.md",
    "wiki/continuity.md",
    "scripts/example.py",
])
def test_the_guard_catches_a_clobbered_checkout_file(tmp_path, monkeypatch,
                                                     relative,
                                                     strict_hermeticity):
    """Each of the probe's targets must now be caught.

    The mutation this kills: narrowing ``_CANONICAL_DIRS`` back to ``logs``
    alone. global-claude-md/claude.md is the source the composer reads, so a
    stray write there reaches every future session.
    """
    root = _throwaway_checkout(tmp_path, monkeypatch)
    target = root / relative

    before = conftest._canonical_store_snapshot()
    target.write_text("clobbered by a careless test\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="source trees"):
        conftest.report_source_tree_changes(
            before, conftest._canonical_store_snapshot())


def test_the_guard_catches_a_file_created_in_a_watched_tree(
        tmp_path, monkeypatch, strict_hermeticity):
    """A NEW file in a watched directory is a change too."""
    root = _throwaway_checkout(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (root / "commands" / "invented.md").write_text("/invented\n",
                                                   encoding="utf-8")

    with pytest.raises(AssertionError):
        conftest.report_source_tree_changes(
            before, conftest._canonical_store_snapshot())


def test_generated_bytecode_is_not_mistaken_for_a_leak(tmp_path, monkeypatch):
    """__pycache__ is written by the interpreter, not by a careless test.

    Without the skip the guard would fail every run the moment a test
    imported a script — a false alarm that would get the guard switched off.
    """
    root = _throwaway_checkout(tmp_path, monkeypatch)
    cache = root / "scripts" / "__pycache__"
    cache.mkdir()

    before = conftest._canonical_store_snapshot()
    (cache / "example.cpython-313.pyc").write_bytes(b"\x00\x01")

    conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())


# ===========================================================================
# The network guard's real perimeter (audit round 4a-3, finding M4)
# ===========================================================================


def test_a_udp_datagram_is_refused():
    """UDP needs no connect, so sendto had to be guarded separately.

    Measured from inside a run before this: sendto to 8.8.8.8:53 succeeded
    while the guard was armed. Kills the mutation that drops the ``sendto``
    wrapper.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(AssertionError, match="send a datagram to"):
            sock.sendto(b"probe", ("8.8.8.8", 53))
    finally:
        sock.close()


def test_a_udp_sendmsg_with_a_destination_is_refused():
    """``sendmsg`` takes its destination as a fourth argument.

    Kills the mutation that drops the ``sendmsg`` wrapper.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(AssertionError, match="no network"):
            sock.sendmsg([b"probe"], [], 0, ("8.8.8.8", 53))
    finally:
        sock.close()


@pytest.mark.local_socket
def test_a_marked_test_may_send_a_datagram_to_its_own_server():
    """The opt-in covers UDP too, and still only for loopback."""
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        client.sendto(b"hello", ("127.0.0.1", port))
        assert server.recv(16) == b"hello"
        with pytest.raises(AssertionError, match="no network"):
            client.sendto(b"probe", ("8.8.8.8", 53))
    finally:
        client.close()
        server.close()


def test_only_the_two_loopback_addresses_are_allowed():
    """127.0.0.0/8 as a whole is NOT loopback for this guard.

    Kills the mutation ``host in _LOOPBACK_HOSTS`` -> ``... or
    host.startswith("127.")``: the comment promised 127.0.0.1 and the code
    allowed the whole /8, and a test that owns a server binds 127.0.0.1, so
    the wider range bought nothing.
    """
    assert conftest._is_loopback(("127.0.0.1", 80))
    assert conftest._is_loopback(("::1", 80))
    assert conftest._is_loopback(("localhost", 80))
    assert not conftest._is_loopback(("127.0.0.2", 80))
    assert not conftest._is_loopback(("127.53.0.1", 80))
    assert not conftest._is_loopback(("10.0.0.1", 80))
    assert not conftest._is_loopback("/var/run/postgresql/.s.PGSQL.5432")
    assert not conftest._is_loopback(None)


def test_the_opt_in_does_not_outlive_the_test():
    """``local_socket`` is off unless the running test asked for it.

    Kills the mutation that drops ``pytest_runtest_teardown``: the last
    marked test's permission would otherwise stay in force for fixture
    finalisers, session teardown, and the next collection. This test is
    unmarked and runs after marked ones in the same file.
    """
    assert conftest._ACTIVE_TEST["local_socket"] is False


def test_the_guard_documents_what_it_cannot_reach():
    """The comment must name the three gaps, not claim blanket denial.

    A guard whose docs overstate its scope is worse than a narrower one
    honestly described: the next author trusts it for a case it never
    covered. Kills a revert of the comment to the old unqualified
    "DEFAULT DENY".
    """
    source = Path(conftest.__file__).read_text(encoding="utf-8")
    section = source[source.index("must not open a network connection"):
                     source.index("must not write ~/.cache")]
    assert "_socket.socket()" in section, "the C accelerator gap"
    assert "Child processes" in section, "the subprocess gap"
    assert "psycopg2" in section, "the C-level driver gap"
    assert "PGHOST" in section, "what actually covers children"


#: Filled by ``record_opt_in_at_teardown`` so a later test can read what the
#: flag looked like once the marked test's body was over.
_OPT_IN_AT_TEARDOWN: list = []


@pytest.fixture
def record_opt_in_at_teardown():
    """Record ``_ACTIVE_TEST["local_socket"]`` from a fixture finaliser."""
    yield
    _OPT_IN_AT_TEARDOWN.append(conftest._ACTIVE_TEST["local_socket"])


@pytest.mark.local_socket
def test_a_marked_test_runs_with_the_opt_in(record_opt_in_at_teardown):
    """Precondition: the flag really is on inside a marked test's body."""
    assert conftest._ACTIVE_TEST["local_socket"] is True


def test_the_opt_in_is_dropped_before_finalisers_run():
    """The marked test above must not leave its permission behind.

    Kills the mutation that empties ``pytest_runtest_teardown``: without it
    the flag is still True while the previous test's fixture finalisers run,
    and stays True through session teardown. Fail closed: a finaliser only
    ever closes a socket, which needs no permission.
    """
    assert _OPT_IN_AT_TEARDOWN, (
        "test_a_marked_test_runs_with_the_opt_in must run first")
    assert _OPT_IN_AT_TEARDOWN[-1] is False, (
        "the opt-in was still in force during the marked test's teardown")


# ===========================================================================
# The PG* environment survives every test (audit round 4a-3, findings M5, M6)
#
# psycopg2 opens its socket in C, below the network guard, so the PGHOST
# repoint is the only thing keeping an import-bound `from psycopg2 import
# connect` away from the operator's database. A fixture that repointed
# PGHOST and forgot to restore it re-opened that door for every following
# test -- reproduced in a copy, with server_version coming back.
# ===========================================================================


@pytest.mark.pg_env
def test_the_pg_snapshot_covers_the_whole_prefix(monkeypatch):
    """Every PG* variable is watched, not a hand-listed few.

    Marked ``pg_env`` even though ``monkeypatch`` restores the variable:
    pytest is free to tear the two fixtures down in either order, and when
    the guard runs first it sees the mutation. The marker is the sanctioned
    way to say "this test varies PG* on purpose"; the restore happens either
    way.
    """
    monkeypatch.setenv("PGPASSFILE", "/tmp/nowhere")
    snapshot = conftest.pg_env_snapshot()
    assert snapshot["PGPASSFILE"] == "/tmp/nowhere"
    assert snapshot["PGHOST"] == os.environ["PGHOST"]
    assert all(key.startswith("PG") for key in snapshot)


def test_the_assertion_flags_a_changed_variable():
    """Set, changed, and removed are all flagged.

    Kills the mutation that neuters ``assert not changed``.
    """
    base = {"PGHOST": "/dead/end", "PGPORT": "1"}
    for after in (
        {"PGHOST": "/var/run/postgresql", "PGPORT": "1"},   # repointed
        {"PGPORT": "1"},                                    # removed
        {"PGHOST": "/dead/end", "PGPORT": "1", "PGUSER": "x"},  # added
    ):
        with pytest.raises(AssertionError, match="PG\\* environment"):
            conftest.assert_pg_env_unchanged(base, after, "some::test")

    conftest.assert_pg_env_unchanged(base, dict(base), "some::test")


@pytest.mark.pg_env
def test_a_marked_test_may_vary_the_pg_environment():
    """The exemption exists for tests that must vary these deliberately."""
    os.environ["PGHOST"] = "/tmp/somewhere-else"
    os.environ["PGSERVICE"] = "invented"
    assert os.environ["PGHOST"] == "/tmp/somewhere-else"


def test_the_environment_is_restored_after_a_marked_test():
    """The restore is unconditional, so one test cannot poison the rest.

    Kills the mutation that drops the restore loop from ``pg_env_unchanged``:
    the marked test above leaves PGHOST pointing elsewhere and PGSERVICE set,
    and every test after it would inherit both.
    """
    assert os.environ["PGHOST"] == str(conftest._NO_PG_SOCKET_DIR)
    assert "PGSERVICE" not in os.environ


def test_the_autouse_fixture_uses_the_assertion():
    """Structural: the fixture must still CALL the guard it defines.

    Kills the mutation that leaves the function in place but stops calling
    it from ``pg_env_unchanged``.
    """
    import ast

    source = Path(conftest.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fixture = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "pg_env_unchanged"
    )
    called = {
        ast.unparse(node.func) for node in ast.walk(fixture)
        if isinstance(node, ast.Call)
    }
    assert "assert_pg_env_unchanged" in called
    assert "pg_env_snapshot" in called


def test_a_new_empty_directory_is_caught(tmp_path, monkeypatch,
                                         strict_hermeticity):
    """Creating an empty directory in a watched tree is a change.

    Kills the mutation that records files only: a test could leave a new
    empty directory anywhere in the checkout and the guard saw nothing.
    Audit round 4a-3, low finding — decided in favour of catching it,
    since a directory costs one dict entry and no stat.
    """
    root = _throwaway_checkout(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (root / "wiki" / "invented-section").mkdir()

    with pytest.raises(AssertionError, match="source trees"):
        conftest.report_source_tree_changes(
            before, conftest._canonical_store_snapshot())


def test_a_removed_directory_is_caught(tmp_path, monkeypatch,
                                       strict_hermeticity):
    """And so is deleting one."""
    root = _throwaway_checkout(tmp_path, monkeypatch)
    (root / "wiki" / "section").mkdir()

    before = conftest._canonical_store_snapshot()
    (root / "wiki" / "section").rmdir()

    with pytest.raises(AssertionError):
        conftest.report_source_tree_changes(
            before, conftest._canonical_store_snapshot())


def test_a_generated_cache_directory_is_still_ignored(tmp_path, monkeypatch):
    """Recording directories must not resurrect the __pycache__ false alarm."""
    root = _throwaway_checkout(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (root / "scripts" / "__pycache__").mkdir()
    (root / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"\x00")

    conftest.report_source_tree_changes(
        before, conftest._canonical_store_snapshot())


@pytest.mark.parametrize("watched", [
    "logs", "tasks", "global-claude-md", "global-agent-guidance",
    "wiki", "commands", "hooks", "scripts", "tests",
])
def test_each_watched_directory_is_really_watched(tmp_path, monkeypatch,
                                                  watched,
                                                  strict_hermeticity):
    """One behavioural check per watched tree, not just a name list.

    ``test_the_watched_paths_name_the_canonical_files`` compares
    ``_CANONICAL_DIRS`` against a hard-coded list, which proves the names
    match a list and nothing more. This creates a file in each directory of
    a throwaway tree and requires the guard to notice — so dropping any one
    entry from ``_CANONICAL_DIRS`` fails here (round 4a-3, low finding).
    """
    # Build the tree from _CANONICAL_DIRS' own basenames, so a directory
    # added to the guard later is exercised the moment it is listed here.
    root = tmp_path / "checkout"
    (root / "data").mkdir(parents=True)
    watched_dirs = []
    for name in [path.name for path in conftest._CANONICAL_DIRS]:
        if name in ("logs", "tasks"):
            real = root / "data" / name
            real.mkdir(parents=True)
            (root / name).symlink_to(real)
        else:
            (root / name).mkdir()
        watched_dirs.append(root / name)
    monkeypatch.setattr(conftest, "_CANONICAL_FILES", ())
    monkeypatch.setattr(conftest, "_CANONICAL_DIRS", tuple(watched_dirs))

    before = conftest._canonical_store_snapshot()
    (root / watched / "stray.md").write_text("left behind\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="source trees"):
        conftest.report_source_tree_changes(
            before, conftest._canonical_store_snapshot())


# ===========================================================================
# The suite's temporary home does not accumulate (round 4a-3, low finding)
# ===========================================================================


def test_a_stale_suite_home_is_swept(tmp_path):
    """An abandoned home older than the window is removed.

    TemporaryDirectory's finaliser does not run when the process is killed
    outright, so a suite that dies that way leaves its whole home behind --
    stub psql and all. Seven were sitting in /tmp when this was written.
    """
    stale = tmp_path / f"{conftest.SUITE_HOME_PREFIX}old"
    stale.mkdir()
    (stale / "bin").mkdir()
    (stale / "bin" / "psql").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    old_time = time.time() - 48 * 3600
    os.utime(stale, (old_time, old_time))

    removed = conftest.sweep_stale_suite_homes(tmp_path)

    assert removed == [stale.name]
    assert not stale.exists()


def test_a_fresh_or_current_suite_home_is_left_alone(tmp_path):
    """A concurrent sibling run must not have its home pulled out.

    Kills a mutation that drops the age check or the ``keep`` check: another
    agent's worktree runs this same suite, and its home is minutes old.
    """
    fresh = tmp_path / f"{conftest.SUITE_HOME_PREFIX}fresh"
    fresh.mkdir()
    current = tmp_path / f"{conftest.SUITE_HOME_PREFIX}current"
    current.mkdir()
    old_time = time.time() - 48 * 3600
    os.utime(current, (old_time, old_time))

    removed = conftest.sweep_stale_suite_homes(tmp_path, current)

    assert removed == []
    assert fresh.exists(), "a fresh home belongs to a live run"
    assert current.exists(), "the running suite's own home must survive"


def test_the_sweep_touches_nothing_else(tmp_path):
    """Only direct children matching the prefix are ever removed.

    Kills a mutation that widens the name test: /tmp holds other agents'
    scratch directories, and this runs unattended on every collection.
    """
    old_time = time.time() - 48 * 3600
    bystanders = []
    for name in ("pytest-of-shawn", "mut-ABCDEF", "pa-round4a2-XXXX",
                 "not-pa-test-home-x"):
        path = tmp_path / name
        path.mkdir()
        os.utime(path, (old_time, old_time))
        bystanders.append(path)
    # A matching name that is a FILE, and one that is a symlink to a real
    # directory: neither is a suite home.
    plain = tmp_path / f"{conftest.SUITE_HOME_PREFIX}file"
    plain.write_text("", encoding="utf-8")
    os.utime(plain, (old_time, old_time))
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / f"{conftest.SUITE_HOME_PREFIX}link"
    link.symlink_to(target)

    assert conftest.sweep_stale_suite_homes(tmp_path) == []
    assert all(path.exists() for path in bystanders)
    assert plain.exists()
    assert target.exists()


def test_the_current_home_is_registered_for_cleanup_at_exit():
    """atexit is the deterministic half of the cleanup.

    Structural: the weakref finaliser is not guaranteed to run at
    interpreter shutdown, so the hook must be registered. Kills the mutation
    that drops ``atexit.register(_SUITE_HOME.cleanup)``.
    """
    import ast

    source = Path(conftest.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    registered = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) == "atexit.register"
    ]
    assert any("_SUITE_HOME.cleanup" in call for call in registered), (
        f"the suite home is not registered for cleanup: {registered}")
    # And the sweep runs at import, not merely exists.
    called = {
        ast.unparse(node.func) for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "sweep_stale_suite_homes" in called


# ===========================================================================
# Concurrency: strict in a clean copy, advisory in a shared checkout
#
# Audit round 4a-3 addendum, CONFIRMED by reproduction. The widened guard
# snapshots the REAL checkout, and this repository is worked by several
# concurrent sessions BY DESIGN (CLAUDE.md). A two-minute run therefore
# straddles other people's edits routinely -- and data/logs/extraction.log
# was rewritten by a session hook mid-run during the investigation. Failing
# for that blames the suite for work the suite did not do, which is the
# fastest way to get a guard switched off.
# ===========================================================================


def test_an_append_to_a_watched_log_is_tolerated(tmp_path, monkeypatch):
    """The extraction hook adding a line must not fail the run.

    Kills the mutation that treats any size change as a violation: the live
    system appends to memories.jsonl and data/logs/* continuously, and the
    suite has no business reporting that.
    """
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)
    log = logs / "extraction.log"
    log.write_text("first line\n", encoding="utf-8")

    before = conftest._canonical_store_snapshot()
    with log.open("a", encoding="utf-8") as handle:
        handle.write("a line the hook appended mid-run\n")

    appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())

    assert appended == [str(log.resolve())]
    assert tolerated == []


def test_an_append_to_the_corpus_is_tolerated(tmp_path, monkeypatch):
    """The same for memories.jsonl itself."""
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "2031-01-02-ddddeeeeffff",
            "content": "A memory the hook appended mid-run.",
            "created_at": "2031-01-02T09:00:00+00:00",
        }) + "\n")

    appended, _tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert appended == [str(corpus.resolve())]


def test_a_rewritten_prefix_is_not_an_append(tmp_path, monkeypatch):
    """A file that GREW but whose earlier bytes changed is still a rewrite.

    Kills the mutation that accepts any size increase without checking the
    prefix: a dedup pass that rewrote the store and happened to end up
    larger would sail through.
    """
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    corpus.write_text(
        '{"id": "rewritten-by-a-careless-test"}\n'
        '{"id": "2031-01-02-ddddeeeeffff"}\n',
        encoding="utf-8",
    )
    assert corpus.stat().st_size > 0

    with pytest.raises(AssertionError, match="APPEND"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_truncated_log_is_still_a_violation(tmp_path, monkeypatch):
    """A shrink is never an append."""
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)
    log = logs / "extraction.log"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")

    before = conftest._canonical_store_snapshot()
    log.write_text("one\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_source_edit_is_queued_for_the_terminal_summary(tmp_path,
                                                          monkeypatch,
                                                          isolated_report):
    """A concurrent session's edit is reported, not fatal.

    Asserts the QUEUE, not a captured print: the operator-visible half is
    covered end to end by
    test_the_advisory_reaches_the_operator_under_default_capture, which runs
    a nested pytest under default capture and greps its output. Reading
    capsys here was exactly the mistake -- the old warning was swallowed and
    its test stayed green (round 4a-4, finding M1).
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    root = _throwaway_checkout(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (root / "wiki" / "someone-elses-note.md").write_text(
        "another session's work\n", encoding="utf-8")

    changed = conftest.report_source_tree_changes(
        before, conftest._canonical_store_snapshot())

    expected = str((root / "wiki" / "someone-elses-note.md").resolve())
    assert changed == [expected]
    assert isolated_report["source_changes"] == [expected], (
        "the advisory was not queued for the terminal summary")


def test_the_same_source_edit_fails_under_strict(tmp_path, monkeypatch):
    """A clean copy has nothing else writing, so the finding is fatal there.

    Kills the mutation that warns unconditionally: the guard would then
    never catch a test that really did write to the checkout.
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    root = _throwaway_checkout(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (root / "wiki" / "written-by-a-test.md").write_text("oops\n",
                                                        encoding="utf-8")

    with pytest.raises(AssertionError, match="source trees"):
        conftest.report_source_tree_changes(
            before, conftest._canonical_store_snapshot())


def test_strict_is_off_unless_the_variable_is_exactly_one(monkeypatch):
    """Only ``1`` turns it on; a stray truthy string does not."""
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    assert conftest.hermeticity_is_strict() is False
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "0")
    assert conftest.hermeticity_is_strict() is False
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "true")
    assert conftest.hermeticity_is_strict() is False
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    assert conftest.hermeticity_is_strict() is True


def test_the_store_half_is_strict_in_both_modes(tmp_path, monkeypatch):
    """Advisory mode applies to the SOURCE trees only.

    A test that rewrites memories.jsonl fails whether or not STRICT is set:
    that is the guard's original purpose and nothing about concurrency
    excuses it.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    corpus.write_text('{"id": "clobbered"}\n', encoding="utf-8")

    with pytest.raises(AssertionError, match="canonical memory store"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


# ===========================================================================
# The advisories must survive pytest's output capture (round 4a-4, M1)
#
# The warning was printed from a session-scoped fixture teardown, which
# pytest captures and discards on a green run: measured at zero occurrences
# at -q and at default verbosity, visible only under -s. Its own test read
# capsys, so it stayed green while the operator saw nothing.
# ===========================================================================

#: Appended to a COPY of the real conftest, so the nested run gets the real
#: guards, hooks and fixtures verbatim and only the watched paths move. A
#: module-level reassignment rather than a hook: it runs at import, long
#: before any snapshot, and cannot be shadowed by a second hook definition.
_NESTED_OVERRIDE = "\n".join([
    "",
    "_CANONICAL_FILES = ()",
    "_APPEND_TOLERANT_DIRS = ()",
    '_CANONICAL_DIRS = (Path(__file__).resolve().parent / "watched",)',
    "",
])

_NESTED_TEST = "\n".join([
    "from pathlib import Path",
    "",
    "_ROOT = Path(__file__).resolve().parent",
    "",
    "",
    "def test_that_writes_into_the_watched_tree():",
    '    (_ROOT / "watched" / "left-behind.md").write_text(',
    '        "x\\n", encoding="utf-8")',
    "    assert True",
    "",
])


def _run_nested_pytest(tmp_path, extra_env=None):
    """Run a nested pytest with DEFAULT capture and return its result.

    The nested tree carries a copy of the real conftest with only the
    watched paths repointed, so what is measured is the real guard's real
    output channel under the real capture settings.
    """
    work = tmp_path / "nested"
    (work / "watched").mkdir(parents=True)
    real_conftest = Path(conftest.__file__).resolve()
    (work / "conftest.py").write_text(
        real_conftest.read_text(encoding="utf-8") + _NESTED_OVERRIDE,
        encoding="utf-8",
    )
    (work / "test_writer.py").write_text(_NESTED_TEST, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "bt"),
         str(work)],
        capture_output=True, text=True, cwd=str(work), env=env,
    )


def test_the_advisory_reaches_the_operator_under_default_capture(tmp_path):
    """The warning must appear in a plain ``-q`` run's own output.

    This is the finding itself: the old ``print`` from a session-fixture
    teardown was swallowed, and the test that "covered" it read capsys, so
    both were green and the operator was told nothing. Kills a revert of the
    ``pytest_terminal_summary`` channel back to ``print``.
    """
    result = _run_nested_pytest(tmp_path)

    combined = result.stdout + result.stderr
    assert "hermeticity" in combined, combined[-3000:]
    assert "WARNING" in combined
    assert "left-behind.md" in combined, "the warning must name the path"
    assert "CONCURRENT SESSION" in combined
    assert conftest.STRICT_ENV_VAR in combined
    assert result.returncode == 0, "advisory mode must not fail the run"


def test_the_same_change_fails_the_nested_run_under_strict(tmp_path):
    """And with STRICT set it is fatal, not merely louder."""
    result = _run_nested_pytest(
        tmp_path, {conftest.STRICT_ENV_VAR: "1"})

    assert result.returncode != 0, result.stdout[-2000:]
    assert "source trees" in result.stdout + result.stderr


# ===========================================================================
# The session path's own pairing (round 4a-4, finding M3)
# ===========================================================================


def test_the_session_pair_leaves_source_changes_to_the_advisory_half(
    tmp_path, monkeypatch, isolated_report,
):
    """A source-tree edit must not make the STORE assertion raise.

    ``assert_canonical_store_untouched`` filters ``violations`` down to the
    append-tolerant paths precisely so a concurrent session's wiki edit goes
    to the advisory half instead of failing the run. Dropping that filter
    (``list(violations)``) survived 395 tests, because every existing test
    drove one half or the other and never the pair the session fixture
    actually uses.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    root = _throwaway_checkout(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (root / "wiki" / "concurrent-edit.md").write_text("theirs\n",
                                                      encoding="utf-8")
    after = conftest._canonical_store_snapshot()

    # The pair, in the order the session fixture calls them.
    changed = conftest.report_source_tree_changes(before, after)
    appended, tolerated = conftest.assert_canonical_store_untouched(
        before, after)

    assert changed == [str((root / "wiki" / "concurrent-edit.md").resolve())]
    assert appended == [] and tolerated == []


# ===========================================================================
# An append is only benign if it is the shape the writer produces (M4)
# ===========================================================================


def test_a_garbage_append_to_the_corpus_is_a_violation(tmp_path, monkeypatch):
    """Growth alone is not enough to call an append the live system's work.

    Kills the mutation that drops ``_appended_content_problem``: a test that
    forgot to patch its path and appended a line of its own to the real
    memories.jsonl was classified benign purely because the file grew.
    """
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write("not json at all\n")

    with pytest.raises(AssertionError, match="not JSON"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_an_appended_record_missing_required_keys_is_a_violation(
    tmp_path, monkeypatch,
):
    """Valid JSON is not enough either; it must look like a memory."""
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "2031-01-02-ddddeeeeffff"}) + "\n")

    with pytest.raises(AssertionError, match="lacks"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_prose_append_to_the_vocabulary_is_a_violation(tmp_path,
                                                         monkeypatch):
    """The vocabulary holds one bare tag per line."""
    _corpus, vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with vocabulary.open("a", encoding="utf-8") as handle:
        handle.write("this is a sentence, not a tag\n")

    with pytest.raises(AssertionError, match="not a bare tag"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_real_tag_append_is_still_benign(tmp_path, monkeypatch):
    """The hook adding a tag must not be reported as a violation."""
    _corpus, vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with vocabulary.open("a", encoding="utf-8") as handle:
        handle.write("kiln-firing-log\n")

    appended, _tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert appended == [str(vocabulary.resolve())]


def test_tolerated_appends_are_described_with_byte_counts(tmp_path,
                                                          monkeypatch):
    """The operator is told what grew and by how much.

    Without this line a test that appended to the real store is invisible,
    since the append itself is classified benign.
    """
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)
    log = logs / "extraction.log"
    log.write_text("first\n", encoding="utf-8")

    before = conftest._canonical_store_snapshot()
    with log.open("a", encoding="utf-8") as handle:
        handle.write("0123456789\n")
    after = conftest._canonical_store_snapshot()

    described = conftest.describe_tolerated_appends(
        before, [str(log.resolve())], after)
    assert described == [f"{log.resolve()} (+11 bytes)"]


# ===========================================================================
# Shared-checkout noise: lock files and rotations (round 4a-4, finding L3)
# ===========================================================================


def test_a_lock_file_appearing_is_tolerated_in_advisory_mode(tmp_path,
                                                             monkeypatch):
    """_bulk_rewrite_guard creates logs/daily-sync.lock in the watched tree.

    Kills the mutation that drops the ``*.lock`` allowance: any bulk rewrite
    running anywhere on the machine during the suite would fail the run.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / "daily-sync.lock").write_text("", encoding="utf-8")

    appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert appended == []
    assert tolerated == [str((logs / "daily-sync.lock").resolve())]


def test_a_log_rotation_is_tolerated_in_advisory_mode(tmp_path, monkeypatch):
    """`mv X X.1` plus a fresh X is a rotation, not the suite writing.

    The fresh X reads as a shrink, which is otherwise a violation. Kills the
    mutation that drops the rotation allowance.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)
    log = logs / "extraction.log"
    log.write_text("a long-standing log with plenty of content\n",
                   encoding="utf-8")

    before = conftest._canonical_store_snapshot()
    log.rename(logs / "extraction.log.1")
    log.write_text("fresh\n", encoding="utf-8")

    appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert appended == []
    assert set(tolerated) == {
        str((logs / "extraction.log.1").resolve()),
        str(log.resolve()),
    }


def test_lock_files_and_rotations_are_violations_under_strict(tmp_path,
                                                              monkeypatch):
    """In a clean copy nothing else is running, so this IS the suite.

    Kills the mutation that tolerates the noise unconditionally.
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / "daily-sync.lock").write_text("", encoding="utf-8")

    with pytest.raises(AssertionError, match="canonical memory store"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_new_log_file_is_tolerated_in_advisory_mode(tmp_path, monkeypatch):
    """The live system starting a new log is not the suite writing.

    Round 4a-5, finding 4: a new ``logs/*.log`` failed in both modes, so any
    script that opened a fresh log during the run failed a shared-checkout
    suite. Narrow on purpose: that directory, that extension.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / "tag-gardening.log").write_text("started\n", encoding="utf-8")

    _appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert tolerated == [str((logs / "tag-gardening.log").resolve())]


def test_a_new_log_file_is_fatal_under_strict(tmp_path, monkeypatch):
    """In a clean copy nothing else is writing, so it IS the suite."""
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / "tag-gardening.log").write_text("started\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="canonical memory store"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_new_non_log_file_under_logs_is_still_a_violation(tmp_path,
                                                            monkeypatch):
    """The allowance is by extension: anything else is still the suite.

    Kills a mutation that widens the rule to every new file under logs/.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / "written-by-a-test.txt").write_text("oops\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


@pytest.mark.parametrize("rotated", [
    "extraction.log.1", "extraction.log.gz", "extraction.log.1.gz",
    "extraction.log.2.bz2", "extraction.log.zst", "extraction.log.xz",
    "extraction.log.3.xz", "extraction.log.Z",
])
def test_a_compressed_rotation_is_tolerated(tmp_path, monkeypatch, rotated):
    """logrotate compresses what it rotates; the digit-only rule missed that.

    Kills the mutation that drops the compression-suffix strip: ``X.gz``
    would read as an ordinary new file and fail a shared-checkout run.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)
    log = logs / "extraction.log"
    log.write_text("a long-standing log with plenty of content\n",
                   encoding="utf-8")

    before = conftest._canonical_store_snapshot()
    log.rename(logs / rotated)
    log.write_text("fresh\n", encoding="utf-8")

    _appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert str((logs / rotated).resolve()) in tolerated
    assert str(log.resolve()) in tolerated


# ===========================================================================
# Strict mode says so when the store half is watching nothing (M2)
# ===========================================================================


def test_strict_reports_an_inert_store_half(tmp_path, monkeypatch):
    """An archive export has no data/, so the store paths dangle.

    That was the one invocation with STRICT set — and the half it made
    strict was watching nothing. Kills the mutation that drops the
    self-check.
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    monkeypatch.setattr(conftest, "_CANONICAL_FILES",
                        (tmp_path / "memories" / "memories.jsonl",))
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS",
                        (tmp_path / "logs",))

    message = conftest.strict_store_coverage_warning()

    assert message is not None
    assert "INERT" in message
    assert "memories.jsonl" in message
    assert "data/ submodule" in message


def test_no_inert_warning_when_the_store_is_present(tmp_path, monkeypatch):
    """A populated checkout under STRICT says nothing."""
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    _corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)
    assert conftest.strict_store_coverage_warning() is None


def test_no_inert_warning_without_strict(tmp_path, monkeypatch):
    """Advisory mode never mentions it: the store half is not strict there."""
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    monkeypatch.setattr(conftest, "_CANONICAL_FILES",
                        (tmp_path / "absent.jsonl",))
    assert conftest.strict_store_coverage_warning() is None


# ===========================================================================
# Round 4a-4, L5 — four mutations the re-audit found surviving in conftest
# ===========================================================================


def test_growth_without_a_start_digest_is_a_violation(tmp_path, monkeypatch):
    """An unreadable file at session start cannot be shown to have grown.

    Kills the mutation that drops ``or old_digest is None``. The hole it
    closes is narrow but real: when the file cannot be hashed at EITHER end
    the comparison becomes ``None != None``, which is false, and the growth
    would be waved through as an append with nothing checked. Fail closed.
    """
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)
    key = str(corpus.resolve())

    before = conftest._canonical_store_snapshot()
    mtime, size, _digest = before[key]
    before[key] = (mtime, size, None)      # unreadable at session start
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "2031-01-02-ddddeeeeffff",
            "content": "A perfectly ordinary appended memory.",
            "created_at": "2031-01-02T09:00:00+00:00",
        }) + "\n")
    after = conftest._canonical_store_snapshot(with_digests=False)
    # ...and unreadable at teardown too, so the digests compare equal.
    monkeypatch.setattr(conftest, "_digest_prefix",
                        lambda path, length: None)

    violations, appends, _tolerated = conftest.classify_store_changes(
        before, after)
    assert appends == []
    assert violations == [key]


def test_the_sweep_never_follows_a_symlinked_directory(tmp_path,
                                                       monkeypatch):
    """A symlink named like a suite home is never handed to rmtree.

    Kills the mutation that drops ``entry.is_symlink() or`` from the type
    test: ``is_dir()`` FOLLOWS symlinks, so a stale symlink pointing at (say)
    a real project directory would be passed to ``shutil.rmtree``. Today
    rmtree refuses a symlink and ``ignore_errors`` swallows it, so the
    target survives by rmtree's grace rather than by this guard — which is
    exactly why the call itself has to be observed.
    """
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep.txt").write_text("do not delete\n", encoding="utf-8")
    link = tmp_path / f"{conftest.SUITE_HOME_PREFIX}link"
    link.symlink_to(target)
    old_time = time.time() - 48 * 3600
    os.utime(link, (old_time, old_time), follow_symlinks=False)
    os.utime(target, (old_time, old_time))

    attempted = []
    real_rmtree = shutil.rmtree
    monkeypatch.setattr(
        shutil, "rmtree",
        lambda path, **kwargs: (attempted.append(str(path)),
                                real_rmtree(path, **kwargs))[1],
    )

    removed = conftest.sweep_stale_suite_homes(tmp_path)

    assert attempted == [], f"rmtree was called on a symlink: {attempted}"
    assert removed == []
    assert link.is_symlink(), "the symlink itself must be left alone"
    assert (target / "keep.txt").exists(), "the target must not be deleted"


def test_sendto_reads_the_destination_from_the_last_argument():
    """``sendto(data, flags, address)`` puts the destination last.

    Kills the mutation ``args[-1]`` -> ``args[0]``: with a flags argument
    present, ``args[0]`` is the integer 0, which is not loopback, so the
    three-argument form would be refused for the wrong reason -- and, worse,
    a marked test's legitimate loopback send would be refused while the
    address was never examined at all.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(AssertionError) as excinfo:
            sock.sendto(b"probe", 0, ("8.8.8.8", 53))
        assert "('8.8.8.8', 53)" in str(excinfo.value), (
            "the refusal named the flags argument, not the destination")
    finally:
        sock.close()


@pytest.mark.local_socket
def test_a_marked_test_may_use_the_three_argument_sendto():
    """And the same form works for a loopback server the test owns."""
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        client.sendto(b"hello", 0, ("127.0.0.1", port))
        assert server.recv(16) == b"hello"
    finally:
        client.close()
        server.close()


# ===========================================================================
# The three notes must reach the terminal (round 4a-5, finding 1)
#
# All three survived mutation: the INERT banner's call site could return
# None, and either _DEFERRED_REPORT key could be renamed, and the suite
# stayed green because every test exercised the FUNCTION and none the
# WIRING. These run a nested pytest under default capture and grep stdout.
# ===========================================================================

#: Populates a synthetic store inside the nested tree and points the guard
#: at it, so the store half is live there rather than inert.
_NESTED_POPULATED_STORE = "\n".join([
    "",
    "_STORE = Path(__file__).resolve().parent / 'data' / 'memories'",
    "_STORE.mkdir(parents=True, exist_ok=True)",
    "_LOGS = Path(__file__).resolve().parent / 'data' / 'logs'",
    "_LOGS.mkdir(parents=True, exist_ok=True)",
    "(_STORE / 'memories.jsonl').write_text(",
    "    '{\"id\": \"2031-01-01-aaaabbbbcccc\", \"content\": \"seed\", '",
    "    '\"created_at\": \"2031-01-01T00:00:00+00:00\"}\\n', encoding='utf-8')",
    "(_STORE / 'tag-vocabulary.txt').write_text('kiln\\n', encoding='utf-8')",
    "_CANONICAL_FILES = (",
    "    _STORE / 'memories.jsonl', _STORE / 'tag-vocabulary.txt')",
    "_APPEND_TOLERANT_DIRS = (_LOGS,)",
    "_CANONICAL_DIRS = (_LOGS,)",
    "",
])

#: Points the guard at store paths that do not exist, the shape an archive
#: export has.
_NESTED_DANGLING_STORE = "\n".join([
    "",
    "_ABSENT = Path(__file__).resolve().parent / 'no-data' / 'memories'",
    "_CANONICAL_FILES = (",
    "    _ABSENT / 'memories.jsonl', _ABSENT / 'tag-vocabulary.txt')",
    "_APPEND_TOLERANT_DIRS = (_ABSENT.parent / 'logs',)",
    "_CANONICAL_DIRS = (_ABSENT.parent / 'logs',)",
    "",
])


def _nested_test_body(statement: str) -> str:
    """A one-test module whose body runs ``statement``."""
    return "\n".join([
        "import json",
        "from pathlib import Path",
        "",
        "_ROOT = Path(__file__).resolve().parent",
        "",
        "",
        "def test_the_live_system_does_something():",
        f"    {statement}",
        "    assert True",
        "",
    ])


def _run_nested(tmp_path, override, body, extra_env=None):
    """Run a nested pytest with DEFAULT capture; return the CompletedProcess."""
    work = tmp_path / "nested"
    (work / "watched").mkdir(parents=True)
    real_conftest = Path(conftest.__file__).resolve()
    (work / "conftest.py").write_text(
        real_conftest.read_text(encoding="utf-8") + override, encoding="utf-8")
    (work / "test_body.py").write_text(body, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "bt"),
         str(work)],
        capture_output=True, text=True, cwd=str(work), env=env,
    )


def test_the_inert_banner_reaches_the_terminal(tmp_path):
    """STRICT over a dangling store must SAY the store half is inert.

    Kills the mutation that makes the call site
    (``coverage = strict_store_coverage_warning()``) return None: the
    function keeps its own tests and the banner never prints.
    """
    result = _run_nested(
        tmp_path, _NESTED_DANGLING_STORE,
        _nested_test_body("pass"),
        {conftest.STRICT_ENV_VAR: "1"},
    )

    combined = result.stdout + result.stderr
    assert "hermeticity" in combined, combined[-2000:]
    assert "INERT" in combined
    assert "memories.jsonl" in combined, "the banner must name what is missing"
    assert result.returncode == 0


def test_the_append_note_reaches_the_terminal(tmp_path):
    """A well-formed append to a populated store is reported, with bytes.

    Kills the mutation that renames the ``appends`` key: the append is still
    tolerated, but the operator is told nothing — which is the whole point
    of the note, since a test that forgot to patch a path appends silently.
    """
    append = (
        "(_ROOT / 'data' / 'memories' / 'memories.jsonl').open("
        "'a', encoding='utf-8').write(json.dumps({"
        "'id': '2031-01-02-ddddeeeeffff', 'content': 'appended', "
        "'created_at': '2031-01-02T00:00:00+00:00'}) + '\\n')"
    )
    result = _run_nested(tmp_path, _NESTED_POPULATED_STORE,
                         _nested_test_body(append))

    combined = result.stdout + result.stderr
    assert "hermeticity" in combined, combined[-2000:]
    assert "the live system appended to" in combined
    assert "memories.jsonl" in combined
    assert "bytes)" in combined, "the note must carry the byte count"
    assert result.returncode == 0


def test_the_tolerated_noise_note_reaches_the_terminal(tmp_path):
    """A .lock creation without STRICT is reported as tolerated noise.

    Kills the mutation that renames the ``tolerated`` key.
    """
    result = _run_nested(
        tmp_path, _NESTED_POPULATED_STORE,
        _nested_test_body(
            "(_ROOT / 'data' / 'logs' / 'daily-sync.lock')"
            ".write_text('', encoding='utf-8')"),
    )

    combined = result.stdout + result.stderr
    assert "hermeticity" in combined, combined[-2000:]
    assert "tolerated shared-checkout noise" in combined
    assert "daily-sync.lock" in combined
    # The LABEL, at its call site. Round 4a-7, finding M-f1: replacing
    # describe_tolerated_kind(path) with the literal "a lock file or a
    # rotation" left 3937 tests green, because the function had its own
    # tests and the call site had none — the same shape as round 4a-4's M1.
    assert "(a lock file)" in combined, combined[-2000:]
    assert "a lock file or a rotation" not in combined
    assert result.returncode == 0


# ===========================================================================
# One classification per teardown (round 4a-5, finding 2)
# ===========================================================================


def test_the_session_teardown_classifies_once(tmp_path, monkeypatch,
                                              isolated_report):
    """Both halves share one answer instead of recomputing it.

    Each changed file is hashed and content-checked inside
    classify_store_changes, so calling it twice doubled that work over the
    live 45 MB corpus. Kills the mutation that drops ``classified=`` from
    either call.
    """
    calls = []
    real = conftest.classify_store_changes
    monkeypatch.setattr(
        conftest, "classify_store_changes",
        lambda before, after: (calls.append(1), real(before, after))[1],
    )
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)

    before = conftest._canonical_store_snapshot()
    (logs / "extraction.log").write_text("a line\n", encoding="utf-8")
    after = conftest._canonical_store_snapshot(with_digests=False)

    classified = conftest.classify_store_changes(before, after)
    conftest.report_source_tree_changes(
        before, after, classified=classified, raise_on_strict=False)
    conftest.store_findings(before, after, classified=classified)

    assert len(calls) == 1, (
        f"the classification was computed {len(calls)} times, not once")


# ===========================================================================
# Both halves are reported before either fails (round 4a-5, finding 6)
# ===========================================================================


def test_a_source_edit_does_not_mask_a_store_violation(tmp_path, monkeypatch,
                                                      isolated_report):
    """Under STRICT, a simultaneous source edit used to raise first.

    ``report_source_tree_changes`` raising before the store half ran meant
    the store violation was never even computed, so the operator saw the
    lesser of the two problems. Kills the mutation that restores the early
    raise (``raise_on_strict=True`` from the session teardown).
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    root = tmp_path / "checkout"
    store = root / "data" / "memories"
    store.mkdir(parents=True)
    wiki = root / "wiki"
    wiki.mkdir()
    corpus = store / "memories.jsonl"
    corpus.write_text('{"id": "a", "content": "x", '
                      '"created_at": "2031-01-01T00:00:00+00:00"}\n',
                      encoding="utf-8")
    monkeypatch.setattr(conftest, "_CANONICAL_FILES", (corpus,))
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS", ())
    monkeypatch.setattr(conftest, "_CANONICAL_DIRS", (wiki,))

    before = conftest._canonical_store_snapshot()
    (wiki / "theirs.md").write_text("a concurrent edit\n", encoding="utf-8")
    corpus.write_text('{"id": "clobbered"}\n', encoding="utf-8")
    after = conftest._canonical_store_snapshot(with_digests=False)

    classified = conftest.classify_store_changes(before, after)
    source_changes = conftest.report_source_tree_changes(
        before, after, classified=classified, raise_on_strict=False)
    store_violations, _appends, _tolerated = conftest.store_findings(
        before, after, classified=classified)

    assert source_changes, "the source edit must still be reported"
    assert store_violations, (
        "the store violation was hidden behind the source edit")


# ===========================================================================
# An indented vocabulary line is not a bare tag (round 4a-5, finding 3)
# ===========================================================================


def test_an_indented_vocabulary_append_is_a_violation(tmp_path, monkeypatch):
    """``stripped != line``, not ``stripped != line.strip()``.

    The old disjunct compared a value with itself and could never fire, so
    an indented append was accepted as a bare tag.
    """
    _corpus, vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with vocabulary.open("a", encoding="utf-8") as handle:
        handle.write("   indented\n")

    with pytest.raises(AssertionError, match="not a bare tag"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_trailing_space_vocabulary_append_is_a_violation(tmp_path,
                                                           monkeypatch):
    """Trailing whitespace is the same defect from the other side."""
    _corpus, vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with vocabulary.open("a", encoding="utf-8") as handle:
        handle.write("kiln-firing   \n")

    with pytest.raises(AssertionError, match="not a bare tag"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


# ===========================================================================
# A half-written trailing line (round 4a-5, finding 5)
# ===========================================================================


def test_a_partial_trailing_line_is_tolerated_in_advisory_mode(tmp_path,
                                                               monkeypatch):
    """A writer caught mid-line is normal in a live checkout.

    Kills the mutation that treats an unterminated tail as an ordinary
    content violation: the extraction hook appending while the guard reads
    would fail a shared-checkout run.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "2031-01-02-ddddeeeeffff",
            "content": "A complete record.",
            "created_at": "2031-01-02T00:00:00+00:00",
        }) + "\n")
        # A COMPLETE record whose terminating newline has not landed yet —
        # the shape a short write leaves behind. Anything less than a
        # complete record is judged as content and refused (finding M2).
        handle.write(json.dumps({
            "id": "2031-01-03-999988887777",
            "content": "Written, but the newline has not landed.",
            "created_at": "2031-01-03T00:00:00+00:00",
        }))

    _appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert any("not terminated" in entry for entry in tolerated), tolerated


def test_a_partial_trailing_line_is_fatal_under_strict(tmp_path, monkeypatch):
    """In a clean copy nothing should be writing at all."""
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "2031-01-03-999988887777",
            "content": "Written, but the newline has not landed.",
            "created_at": "2031-01-03T00:00:00+00:00",
        }))

    with pytest.raises(AssertionError, match="not terminated"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_garbage_complete_line_before_a_partial_tail_is_still_fatal(
    tmp_path, monkeypatch,
):
    """The allowance covers the LAST line only, not what precedes it."""
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write("not json at all\n")
        handle.write('{"id": "partial", "cont')

    with pytest.raises(AssertionError, match="not JSON"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


# ===========================================================================
# The INERT banner names what is missing (round 4a-5, finding 7)
# ===========================================================================


def test_the_inert_banner_does_not_assume_an_archive_export(tmp_path,
                                                            monkeypatch):
    """A worktree with a populated logs/ but no store files says so.

    The old wording asserted "an archive export has no data/ submodule"
    whatever was actually absent, which is wrong from a worktree where only
    the two files are missing.
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(conftest, "_CANONICAL_FILES",
                        (tmp_path / "memories" / "memories.jsonl",))
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS", (logs,))

    message = conftest.strict_store_coverage_warning()

    assert message is not None
    assert "memories.jsonl" in message
    assert str(logs) not in message, "a present directory must not be listed"
    assert "missing or dangling" in message


def _session_fixture_calls():
    """Every Call node inside the ``no_real_cache_writes`` fixture."""
    import ast

    source = Path(conftest.__file__).read_text(encoding="utf-8")
    fixture = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef)
        and node.name == "no_real_cache_writes"
    )
    return [node for node in ast.walk(fixture) if isinstance(node, ast.Call)]


def test_the_session_teardown_shares_one_classification():
    """Both halves must be HANDED the classification, not recompute it.

    Structural, because the cost is invisible to an assertion on results:
    dropping ``classified=`` from either call leaves every test green while
    each changed file is hashed and content-checked twice over. Kills that
    mutation on the session fixture itself (round 4a-5, finding 2).
    """
    import ast

    calls = _session_fixture_calls()
    by_name = {}
    for call in calls:
        name = ast.unparse(call.func)
        by_name.setdefault(name, []).append(call)

    assert len(by_name.get("classify_store_changes", [])) == 1, (
        "the fixture must classify exactly once")
    for name in ("report_source_tree_changes", "store_findings"):
        call = by_name[name][0]
        keywords = {kw.arg for kw in call.keywords}
        assert "classified" in keywords, (
            f"{name} recomputes the classification instead of reusing it")


def test_the_session_teardown_defers_the_strict_source_raise():
    """The source half must not raise before the store half has run.

    Kills the mutation that restores ``raise_on_strict=True`` on the
    session fixture's call (round 4a-5, finding 6).
    """
    import ast

    call = next(
        node for node in _session_fixture_calls()
        if ast.unparse(node.func) == "report_source_tree_changes"
    )
    deferred = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
    assert deferred.get("raise_on_strict") == "False", (
        "the source half still raises before the store half is checked")


def test_a_run_with_both_kinds_of_violation_reports_both(tmp_path):
    """End to end: under STRICT the operator is told about BOTH.

    A source edit and a store violation in the same run used to surface as
    the source edit alone, because ``report_source_tree_changes`` raised
    first and the store half never ran. The nested run's output must name
    each of them.
    """
    override = "\n".join([
        "",
        "_ROOT2 = Path(__file__).resolve().parent",
        "_STORE2 = _ROOT2 / 'data' / 'memories'",
        "_STORE2.mkdir(parents=True, exist_ok=True)",
        "(_STORE2 / 'memories.jsonl').write_text(",
        "    '{\"id\": \"a\", \"content\": \"seed\", '",
        "    '\"created_at\": \"2031-01-01T00:00:00+00:00\"}\\n',",
        "    encoding='utf-8')",
        "(_ROOT2 / 'wiki').mkdir(exist_ok=True)",
        "_CANONICAL_FILES = (_STORE2 / 'memories.jsonl',)",
        "_APPEND_TOLERANT_DIRS = ()",
        "_CANONICAL_DIRS = (_ROOT2 / 'wiki',)",
        "",
    ])
    body = "\n".join([
        "from pathlib import Path",
        "",
        "_ROOT = Path(__file__).resolve().parent",
        "",
        "",
        "def test_touches_both():",
        "    (_ROOT / 'wiki' / 'theirs.md').write_text(",
        "        'a concurrent edit\\n', encoding='utf-8')",
        "    (_ROOT / 'data' / 'memories' / 'memories.jsonl').write_text(",
        "        '{\"id\": \"clobbered\"}\\n', encoding='utf-8')",
        "    assert True",
        "",
    ])

    result = _run_nested(tmp_path, override, body,
                         {conftest.STRICT_ENV_VAR: "1"})

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined[-2000:]
    assert "theirs.md" in combined, "the source edit was not reported"
    assert "memories.jsonl" in combined, "the store violation was not reported"
    assert "source trees" in combined
    assert "canonical memory store" in combined


# ===========================================================================
# Round 4a-6
# ===========================================================================


def test_the_report_queue_is_isolated_for_every_test(isolated_report):
    """The isolation is AUTOMATIC, not opt-in (finding M3).

    It used to be a fixture a test had to remember: removing it from the one
    test that used it left 117 tests green while the run's terminal summary
    warned about a path under pytest's basetemp. Nothing failed; the guard
    just cried wolf. Kills a mutation that drops ``autouse=True``.
    """
    import ast

    source = Path(conftest.__file__).read_text(encoding="utf-8")
    fixture = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "isolated_report"
    )
    decorators = [ast.unparse(d) for d in fixture.decorator_list]
    assert any("autouse=True" in d for d in decorators), (
        f"isolated_report is not autouse: {decorators}")

    # And it really is a different dict from the session's.
    isolated_report["source_changes"] = ["a throwaway path"]
    assert conftest._DEFERRED_REPORT is isolated_report


def test_a_test_cannot_leak_a_basetemp_path_into_the_summary(tmp_path,
                                                             monkeypatch):
    """The counterfactual, run for real: queue a path, and it stays local.

    Drives ``report_source_tree_changes`` exactly as the leaking test did.
    With the autouse isolation the entry lands in this test's own dict and
    the session's queue is untouched, so the terminal summary cannot report
    it.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    root = _throwaway_checkout(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (root / "wiki" / "someone-elses-note.md").write_text("theirs\n",
                                                         encoding="utf-8")
    conftest.report_source_tree_changes(
        before, conftest._canonical_store_snapshot())

    queued = conftest._DEFERRED_REPORT.get("source_changes", [])
    assert queued, "the call should have queued into THIS test's dict"
    assert all(str(tmp_path) in path for path in queued), queued


# --------------------------------------------------------------------------
# M2 — an unterminated fragment is content too
# --------------------------------------------------------------------------


#: The two tail shapes and what each must do in each mode (round 4a-7,
#: finding M-b1). A short write cuts the record mid-JSON and the newline is
#: the LAST byte to arrive, so a truncated object is the state that really
#: occurs; requiring the tail to parse tolerated only the state that almost
#: never does, and a real truncated append failed an advisory run.
_TRUNCATED_RECORD = '{"id": "2031-01-03-999988887777", "content": "half a rec'
_GARBAGE_FRAGMENT = "not json at all"


@pytest.mark.parametrize("strict", [False, True], ids=["advisory", "strict"])
@pytest.mark.parametrize("tail,is_prefix", [
    (_TRUNCATED_RECORD, True),
    (_GARBAGE_FRAGMENT, False),
], ids=["json-prefix", "garbage"])
def test_the_four_unterminated_tail_cells(tmp_path, monkeypatch, strict,
                                          tail, is_prefix):
    """All four cells of (advisory|strict) x (JSON prefix|garbage).

    A truncated JSON object is what a short write leaves behind, so in
    advisory mode it is reported as in-progress; garbage never is. Under
    STRICT nothing should be writing at all, so both fail.

    Kills the mutation that requires the tail to PARSE (which refuses the
    truncated record in advisory mode) and the one that drops the check
    entirely (which tolerates the garbage).
    """
    if strict:
        monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    else:
        monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(tail)

    if strict or not is_prefix:
        expected = ("not terminated" if is_prefix
                    else "does not start a JSON record")
        with pytest.raises(AssertionError, match=expected):
            conftest.assert_canonical_store_untouched(
                before, conftest._canonical_store_snapshot())
        return

    _appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert any("not terminated" in entry for entry in tolerated), tolerated


def test_a_truncated_record_after_a_complete_one_is_in_progress(tmp_path,
                                                                monkeypatch):
    """The real shape: one whole record, then a cut-off one.

    This is what a short write on the second append actually produces.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "2031-01-02-ddddeeeeffff",
            "content": "A complete record.",
            "created_at": "2031-01-02T00:00:00+00:00",
        }) + "\n")
        handle.write(_TRUNCATED_RECORD)

    _appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert any("not terminated" in entry for entry in tolerated), tolerated


def test_a_fragment_spanning_a_newline_is_a_violation(tmp_path, monkeypatch):
    """Text carrying its own line break is judged as COMPLETE lines.

    ``{"id": "a",`` is a complete line and is not JSON, so it fails before
    the unterminated tail is ever considered. (The prefix rule needs no
    newline test of its own: its input is the last element of a ``"\n"``
    split.)
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "a",\n "content": "spans a break')

    with pytest.raises(AssertionError):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_an_unterminated_vocabulary_fragment_is_judged_too(tmp_path,
                                                           monkeypatch):
    """The vocabulary's shape rule applies to a partial line as well."""
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with vocabulary.open("a", encoding="utf-8") as handle:
        handle.write("a sentence, not a tag")

    with pytest.raises(AssertionError, match="not a bare tag"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


# --------------------------------------------------------------------------
# L4/L5 — what the live logs/ directory really grows
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "drift-sweep.jsonl", "bulk-archive-manifest.json", "surfacing.log",
])
def test_the_shapes_the_real_logs_directory_holds_are_tolerated(
    tmp_path, monkeypatch, name,
):
    """``.log`` alone was too narrow for the directory it describes.

    The real ``data/logs/`` holds ``drift-sweep.jsonl`` and
    ``bulk-archive-manifest.json``; either appearing mid-run failed a
    shared-checkout suite. Kills the mutation that narrows the suffix list
    back to ``.log``.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / name).write_text("{}\n", encoding="utf-8")

    _appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert tolerated == [str((logs / name).resolve())]


def test_a_new_directory_under_logs_is_tolerated(tmp_path, monkeypatch):
    """``data/logs/`` really does grow subtrees (terra-enrich-responses).

    A directory carries no content of its own, and the first file written
    into it is judged on its own merits. Kills the mutation that tolerates
    files only.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / "terra-enrich-responses").mkdir()

    _appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert tolerated == [str((logs / "terra-enrich-responses").resolve())]


def test_a_file_in_a_new_logs_subdirectory_is_still_judged(tmp_path,
                                                           monkeypatch):
    """Tolerating the directory does not tolerate what goes into it."""
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    subtree = logs / "terra-enrich-responses"
    subtree.mkdir()
    (subtree / "written-by-a-test.txt").write_text("oops\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_new_logs_shapes_are_fatal_under_strict(tmp_path, monkeypatch):
    """In a clean copy nothing else is writing, so they are the suite's."""
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    (logs / "drift-sweep.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="canonical memory store"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_a_created_store_file_is_never_noise(tmp_path, monkeypatch):
    """``memories.jsonl`` ends with .jsonl but is not under logs/.

    Kills the mutation that drops the ``_under_logs`` test from the
    new-suffix branch: the suite creating a corpus where there was none
    would then read as ordinary log output. This is also what makes
    ``_under_logs`` reachable-False at its call site (finding L7).
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    _corpus, _vocabulary, logs = _throwaway_store(tmp_path, monkeypatch)
    store_dir = logs.parent / "memories"
    corpus = store_dir / "memories.jsonl"
    corpus.unlink()

    before = conftest._canonical_store_snapshot()
    corpus.write_text('{"id": "invented-by-a-test"}\n', encoding="utf-8")

    with pytest.raises(AssertionError, match="canonical memory store"):
        conftest.assert_canonical_store_untouched(
            before, conftest._canonical_store_snapshot())


def test_under_logs_is_anchored_on_the_separator(tmp_path, monkeypatch):
    """``/logs-old/x`` is not inside ``/logs``.

    Kills the mutation that drops the ``+ os.sep`` from the prefix test.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS", (logs,))

    assert conftest._under_logs(str(logs / "extraction.log"))
    assert conftest._under_logs(str(logs / "sub" / "x.log"))
    assert not conftest._under_logs(str(tmp_path / "logs-old" / "x.log"))
    assert not conftest._under_logs(str(logs))


# --------------------------------------------------------------------------
# L6 — each tolerated entry is labelled by its class
# --------------------------------------------------------------------------


def test_a_new_directory_is_labelled_as_one(tmp_path):
    """A directory is decided by what it IS, not by its name.

    Kills the mutation that drops the ``is_dir()`` arm: a subtree called
    ``run.2`` was labelled "a log rotation", and an ordinary one fell
    through to the catch-all (round 4a-7, finding L-e1).
    """
    plain = tmp_path / "terra-enrich-responses"
    plain.mkdir()
    numbered = tmp_path / "run.2"
    numbered.mkdir()

    assert conftest.describe_tolerated_kind(str(plain)) == "a new directory"
    assert conftest.describe_tolerated_kind(str(numbered)) == "a new directory"
    # The same NAME as a file is a rotation again.
    (tmp_path / "extraction.log.2").write_text("", encoding="utf-8")
    assert conftest.describe_tolerated_kind(
        str(tmp_path / "extraction.log.2")) == "a log rotation"


@pytest.mark.parametrize("entry,expected", [
    ("/x/logs/daily-sync.lock", "a lock file"),
    ("/x/logs/extraction.log.1", "a log rotation"),
    ("/x/logs/extraction.log.gz", "a log rotation"),
    ("/x/logs/extraction.log.1.gz", "a log rotation"),
    ("/x/logs/surfacing.log", "a new log file"),
    ("/x/logs/drift-sweep.jsonl", "a new log file"),
    ("/x/memories/memories.jsonl (the final appended line is not "
     "terminated — an append in progress)", "an append in progress"),
])
def test_each_tolerated_entry_is_named_by_its_class(entry, expected):
    """"a lock file or a rotation" was printed for a half-written append too.

    Kills the mutation that returns one fixed label for every class.
    """
    assert conftest.describe_tolerated_kind(entry) == expected


def test_the_inert_banner_names_a_missing_directory(tmp_path, monkeypatch):
    """A dangling logs/ is as inert as a missing store file.

    Kills the mutation that drops the ``_APPEND_TOLERANT_DIRS`` half of the
    coverage check: with the files present but logs/ gone, the banner said
    nothing and the run looked fully strict.
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    store = tmp_path / "memories"
    store.mkdir()
    corpus = store / "memories.jsonl"
    corpus.write_text("", encoding="utf-8")
    monkeypatch.setattr(conftest, "_CANONICAL_FILES", (corpus,))
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS",
                        (tmp_path / "absent-logs",))

    message = conftest.strict_store_coverage_warning()

    assert message is not None, "a missing watched DIRECTORY must be named"
    assert "absent-logs" in message
    assert str(corpus) not in message, "a present file must not be listed"


def test_a_watched_log_path_that_is_a_file_is_not_a_directory(tmp_path,
                                                              monkeypatch):
    """``is_dir()``, not ``exists()``: a dangling symlink is not a directory.

    Kills the mutation ``not path.is_dir()`` -> ``not path.exists()``: a
    symlink whose target is gone still "exists" for ``exists()`` only when
    it resolves, but a plain FILE where a directory belongs passes
    ``exists()`` and fails ``is_dir()`` — and the store half is inert
    either way.
    """
    monkeypatch.setenv(conftest.STRICT_ENV_VAR, "1")
    store = tmp_path / "memories"
    store.mkdir()
    corpus = store / "memories.jsonl"
    corpus.write_text("", encoding="utf-8")
    not_a_directory = tmp_path / "logs"
    not_a_directory.write_text("", encoding="utf-8")
    monkeypatch.setattr(conftest, "_CANONICAL_FILES", (corpus,))
    monkeypatch.setattr(conftest, "_APPEND_TOLERANT_DIRS", (not_a_directory,))

    message = conftest.strict_store_coverage_warning()

    assert message is not None
    assert "logs" in message


def test_a_partial_line_of_only_whitespace_is_not_a_violation(tmp_path,
                                                              monkeypatch):
    """``partial.strip()`` — a trailing blank is not an in-progress line.

    Kills the mutation ``partial.strip()`` -> ``partial``: a trailing run of
    spaces would then be reported as an append in progress on every
    otherwise-clean append.
    """
    monkeypatch.delenv(conftest.STRICT_ENV_VAR, raising=False)
    corpus, _vocabulary, _logs = _throwaway_store(tmp_path, monkeypatch)

    before = conftest._canonical_store_snapshot()
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "2031-01-02-ddddeeeeffff",
            "content": "A complete record.",
            "created_at": "2031-01-02T00:00:00+00:00",
        }) + "\n   ")

    appended, tolerated = conftest.assert_canonical_store_untouched(
        before, conftest._canonical_store_snapshot())
    assert appended == [str(corpus.resolve())]
    assert tolerated == []


# ===========================================================================
# The queue net catches a WIDER-scoped leak (round 4a-7, finding M-a1)
#
# isolated_report is function-scoped, so a session- or module-scoped fixture
# that queues into _DEFERRED_REPORT writes to the real dict and the summary
# warns about a path under pytest's own basetemp. The round 4a-6 "net" could
# not see it: the autouse isolation applied to that test too, so it always
# inspected an empty monkeypatched dict, and most of the suite ran after it.
# ===========================================================================

#: A nested conftest whose SESSION-scoped fixture queues a basetemp path —
#: the leak shape the function-scoped isolation cannot reach.
_NESTED_SESSION_LEAK = "\n".join([
    "",
    "@pytest.fixture(scope='session', autouse=True)",
    "def _leaks_a_basetemp_path(tmp_path_factory):",
    "    leaked = tmp_path_factory.mktemp('leaked')",
    "    _DEFERRED_REPORT['source_changes'] = [",
    "        str(leaked / 'someone-elses-note.md')]",
    "    yield",
    "",
])


def test_a_session_scoped_fixture_cannot_leak_into_the_summary(tmp_path):
    """A wider-scoped leak fails the nested run instead of crying wolf.

    Reproduces the finding exactly: a ``scope="session", autouse=True``
    fixture queues a ``tmp_path_factory`` path. Before the net that run
    exited 0 and printed "WARNING: the checkout's source trees changed …
    /bt/leaked0/someone-elses-note.md". Kills the mutation that deletes
    ``pytest_sessionfinish``, and the one that stops setting
    ``session.exitstatus``.
    """
    result = _run_nested(tmp_path, _NESTED_SESSION_LEAK,
                         _nested_test_body("pass"))

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined[-2000:]
    assert "leaked a temporary path" in combined
    assert "someone-elses-note.md" in combined
    # And the wolf-cry must NOT appear: the leaked entry is dropped, so the
    # summary cannot report it as a real source change.
    assert "the checkout's source trees changed" not in combined


def test_the_net_leaves_a_real_source_change_alone(tmp_path):
    """A genuine change outside the basetemp still reports normally.

    Kills a mutation that drops every queue entry rather than the leaked
    ones: the net must not swallow the warning it exists to protect.
    """
    result = _run_nested(tmp_path, _NESTED_OVERRIDE,
                         _nested_test_body(
                             "(_ROOT / 'watched' / 'left-behind.md')"
                             ".write_text('x\\n', encoding='utf-8')"))

    combined = result.stdout + result.stderr
    assert "the checkout's source trees changed" in combined
    assert "left-behind.md" in combined
    assert "leaked a temporary path" not in combined
    assert result.returncode == 0


def test_the_basetemp_roots_cover_both_sources(tmp_path, monkeypatch):
    """The net looks at ``--basetemp`` AND the factory's own root.

    A run may use either, so checking one leaves the other unguarded.
    """
    class _Option:
        basetemp = str(tmp_path / "explicit")

    class _Factory:
        @staticmethod
        def getbasetemp():
            return tmp_path / "factory"

    class _Config:
        option = _Option()
        _tmp_path_factory = _Factory()

    roots = conftest._basetemp_roots(_Config())
    assert any("explicit" in root for root in roots)
    assert any("factory" in root for root in roots)


def test_the_new_log_label_reaches_the_terminal(tmp_path):
    """A second class through the same call site, so one literal cannot pass.

    With only the lock-file case asserted, replacing the call with the
    literal "a lock file" would still be green. Two classes through one
    call site means no constant satisfies both.
    """
    result = _run_nested(
        tmp_path, _NESTED_POPULATED_STORE,
        _nested_test_body(
            "(_ROOT / 'data' / 'logs' / 'drift-sweep.jsonl')"
            ".write_text('{}\\n', encoding='utf-8')"),
    )

    combined = result.stdout + result.stderr
    assert "tolerated shared-checkout noise" in combined, combined[-2000:]
    assert "(a new log file)" in combined
    assert "drift-sweep.jsonl" in combined
    assert result.returncode == 0


def test_the_strict_note_does_not_call_a_fatal_item_tolerated(tmp_path):
    """Under STRICT the same entry FAILED, so the wording must not say
    "tolerated" flatly (round 4a-7, finding L-g1)."""
    result = _run_nested(
        tmp_path, _NESTED_POPULATED_STORE,
        _nested_test_body(
            "(_ROOT / 'data' / 'logs' / 'daily-sync.lock')"
            ".write_text('', encoding='utf-8')"),
        {conftest.STRICT_ENV_VAR: "1"},
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined[-2000:]
    assert "would be tolerated in advisory mode" in combined
    assert "fatal under PA_HERMETICITY_STRICT" in combined
    assert "note: tolerated shared-checkout noise" not in combined


def test_the_net_drops_only_the_leaked_entry(tmp_path):
    """A run with BOTH a leak and a real source change keeps the real one.

    Kills the mutation that replaces the selective drop with
    ``_DEFERRED_REPORT.clear()``: the leak would be reported and the
    genuine warning silently thrown away with it.
    """
    override = _NESTED_OVERRIDE + "\n".join([
        "",
        "@pytest.fixture(scope='session', autouse=True)",
        "def _also_leaks(tmp_path_factory):",
        "    leaked = tmp_path_factory.mktemp('leaked')",
        # Into `tolerated`, not `source_changes`: the session teardown
        # ASSIGNS source_changes when it finds a real change, which would
        # overwrite the leak before the net ever saw it.
        "    _DEFERRED_REPORT.setdefault('tolerated', []).append(",
        "        str(leaked / 'not-mine.md'))",
        "    yield",
        "",
    ])
    result = _run_nested(
        tmp_path, override,
        _nested_test_body(
            "(_ROOT / 'watched' / 'left-behind.md')"
            ".write_text('x\\n', encoding='utf-8')"),
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined[-2000:]
    assert "leaked a temporary path" in combined
    assert "not-mine.md" in combined
    assert "left-behind.md" in combined, (
        "the genuine source change was thrown away with the leak")


# ===========================================================================
# The M1 hole, closed by an in-process audit hook (round 4a-7)
#
# A well-formed append to the real store is indistinguishable AFTER THE FACT
# from the extraction hook's. It is distinguishable WHILE IT HAPPENS: the
# hook runs in another process, so an audit hook in this interpreter sees
# only what this process opens.
# ===========================================================================


@pytest.mark.parametrize("mode,flags,writing", [
    ("r", None, False),
    ("rb", None, False),
    ("a", None, True),
    ("w", None, True),
    ("r+", None, True),
    ("xb", None, True),
    (None, os.O_RDONLY, False),
    (None, os.O_WRONLY | os.O_APPEND, True),
    (None, os.O_RDWR, True),
    (None, os.O_CREAT, True),
    (None, None, False),
])
def test_which_open_events_count_as_writing(mode, flags, writing):
    """``os.open`` reports mode=None, so the flags must be consulted too.

    The first prototype checked only the mode string and missed every
    ``os.open``; a read must never count. Kills a mutation that drops
    either half of the test.
    """
    assert conftest._audit_is_writing(mode, flags) is writing


def test_the_audit_path_helper_accepts_what_the_event_carries(tmp_path):
    """``Path.open`` hands the event a PosixPath, not a str.

    That is the commonest route into the store, and an ``isinstance(raw,
    str)`` test misses it — which is why the first prototype reported
    nothing. Kills a mutation that drops ``os.fspath``.
    """
    target = tmp_path / "memories.jsonl"
    assert conftest._audit_path(target) == str(target)
    assert conftest._audit_path(str(target)) == str(target)
    assert conftest._audit_path(str(target).encode()) == str(target)
    assert conftest._audit_path(7) is None      # an fd, not a path
    assert conftest._audit_path(None) is None


def test_arming_is_a_no_op_without_a_store(tmp_path, monkeypatch):
    """No store, nothing to watch — and audit hooks cannot be removed.

    An archive export has no store, so arming there would install a
    permanent hook that could never match.
    """
    monkeypatch.setattr(conftest, "_AUDIT_ARMED", [False])
    monkeypatch.setattr(conftest, "_CANONICAL_FILES",
                        (tmp_path / "absent" / "memories.jsonl",))
    assert conftest.arm_store_write_audit() is False


def test_arming_twice_installs_one_hook(tmp_path, monkeypatch):
    """``sys.addaudithook`` is permanent, so a second arm must be a no-op.

    Kills a mutation that drops the ``_AUDIT_ARMED`` guard: the session
    fixture would stack a hook per invocation.
    """
    installed = []
    monkeypatch.setattr(conftest, "_AUDIT_ARMED", [False])
    monkeypatch.setattr(conftest, "_CANONICAL_FILES", ())
    monkeypatch.setattr(sys, "addaudithook",
                        lambda hook: installed.append(hook))
    corpus = tmp_path / "memories.jsonl"
    corpus.write_text("", encoding="utf-8")
    monkeypatch.setattr(conftest, "_CANONICAL_FILES", (corpus,))

    assert conftest.arm_store_write_audit() is True
    assert conftest.arm_store_write_audit() is True
    assert len(installed) == 1


def test_store_write_opens_names_the_test(monkeypatch):
    """The report must name the test, not just the path."""
    monkeypatch.setattr(
        conftest, "_STORE_WRITE_OPENS",
        [("tests/test_x.py::test_y", "/store/memories.jsonl")])
    assert conftest.store_write_opens() == [
        "tests/test_x.py::test_y opened /store/memories.jsonl for writing"]


#: A nested tree whose store is populated AND whose test appends a
#: well-formed record to it — the M1 hole, reproduced end to end.
_NESTED_M1_APPEND = "\n".join([
    "import json",
    "from pathlib import Path",
    "",
    "import conftest",
    "",
    "",
    "def test_forgets_to_patch_its_path():",
    "    corpus = conftest._CANONICAL_FILES[0]",
    "    with corpus.open('a', encoding='utf-8') as fh:",
    "        fh.write(json.dumps({",
    "            'id': '2031-09-09-ffffeeeedddd',",
    "            'content': 'appended by a careless test',",
    "            'created_at': '2031-09-09T00:00:00+00:00'}) + '\\n')",
    "    assert True",
    "",
])


def test_an_in_process_append_is_reported_in_advisory_mode(tmp_path):
    """The hole itself: a well-formed append the snapshot cannot catch.

    Before the audit hook this run was silent and green — the append was
    verified as an append and tolerated, exactly as documented. Now the
    write is named with the test that made it, while the run still passes
    (advisory). Kills the mutation that drops ``arm_store_write_audit``.
    """
    result = _run_nested(tmp_path, _NESTED_POPULATED_STORE, _NESTED_M1_APPEND)

    combined = result.stdout + result.stderr
    assert "opened the real canonical store for writing" in combined, (
        combined[-2500:])
    assert "test_forgets_to_patch_its_path" in combined
    assert "memories.jsonl" in combined
    assert result.returncode == 0, "advisory mode reports, it does not fail"


def test_an_in_process_append_is_fatal_under_strict(tmp_path):
    """And in a clean copy it fails the run.

    Kills the mutation that reports without ever failing.
    """
    result = _run_nested(tmp_path, _NESTED_POPULATED_STORE, _NESTED_M1_APPEND,
                         {conftest.STRICT_ENV_VAR: "1"})

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined[-2500:]
    assert "opened the REAL canonical store for writing" in combined
    assert "test_forgets_to_patch_its_path" in combined


def test_a_read_of_the_store_is_not_reported(tmp_path):
    """Reading the corpus is what most tests legitimately do.

    Kills a mutation that reports every open regardless of mode — which
    would fail on the guard's own snapshot reads.
    """
    body = "\n".join([
        "import conftest",
        "",
        "",
        "def test_reads_the_store():",
        "    corpus = conftest._CANONICAL_FILES[0]",
        "    assert corpus.read_text(encoding='utf-8')",
        "",
    ])
    result = _run_nested(tmp_path, _NESTED_POPULATED_STORE, body,
                         {conftest.STRICT_ENV_VAR: "1"})

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined[-2500:]
    assert "opened the real canonical store for writing" not in combined
