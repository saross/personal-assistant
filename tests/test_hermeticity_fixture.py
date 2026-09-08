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
    assert str(corpus.resolve()) in conftest.canonical_store_changes(
        before, after)


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


def test_the_guard_catches_a_same_size_rewrite(tmp_path, monkeypatch):
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
    assert [path.name for path in conftest._CANONICAL_DIRS] == ["logs"]

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
    assert "assert_canonical_store_untouched" in called, (
        "the session fixture no longer checks the canonical store")
    assert "_canonical_store_snapshot" in called
