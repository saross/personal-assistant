"""
Shared fixtures for personal-assistant test suite.

Provides temporary directories and sample data for hook testing
without touching the real memory system.
"""

import atexit
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Add project root to path so we can import hook modules
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "hooks"))


# ---------------------------------------------------------------------------
# HOME belongs to the suite, not to the operator
#
# Every script here resolves ``~`` — gate files, sidecars, refusal
# memories, lock files, the daily-sync marker — and the hermeticity guard
# below watches that directory for writes the suite should not have made.
# Watching the OPERATOR'S home made the guard wrong in both directions:
# it blamed the suite for other processes' writes (after merge, cron
# rewrites the memories gate every five minutes, so a full run would fail
# at random), and it could only ever catch a leak after the damage was
# done (ninth re-audit, finding M5).
#
# So the suite gets a home of its own, and the guard watches THAT. The
# repoint happens at import time rather than in a fixture because several
# modules bake ``Path.home()`` into constants when they are imported, and
# a fixture runs far too late to change what those constants mean.
#
# A test that genuinely needs the real checkout must find it from
# ``__file__`` or an explicit environment variable — never from ``~``.
# ---------------------------------------------------------------------------

#: Prefix of the suite's own temporary home, and of the strays it sweeps.
SUITE_HOME_PREFIX = "pa-test-home-"

#: A stray older than this is nobody's live run. A concurrent sibling suite
#: (another agent's worktree, a parallel run) may well have one minutes old,
#: so the window is generous on purpose.
STALE_SUITE_HOME_HOURS = 24


def sweep_stale_suite_homes(
    root: Path,
    keep: Path | None = None,
    *,
    max_age_hours: int = STALE_SUITE_HOME_HOURS,
    now: float | None = None,
) -> list[str]:
    """Remove abandoned ``pa-test-home-*`` directories under ``root``.

    ``TemporaryDirectory``'s finaliser does not run when the process is
    killed outright — SIGKILL, an OOM kill, a hard Ctrl-\\ — so a suite that
    dies that way leaves its whole home behind, stub ``psql`` and all. They
    accumulate (seven were sitting in /tmp when this was written). Harmless
    individually; untidy in aggregate, and each one holds an executable that
    shadows a real binary if anything ever put it on PATH.

    Returns the names removed, so the behaviour can be asserted. Only
    directories that are DIRECT children of ``root``, whose name starts with
    :data:`SUITE_HOME_PREFIX`, that are not ``keep``, and whose mtime is
    older than ``max_age_hours`` are touched; anything else is left alone.
    """
    cutoff = (now if now is not None else time.time()) - max_age_hours * 3600
    removed: list[str] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:  # pragma: no cover — an unreadable tmpdir is not our problem
        return removed
    for entry in entries:
        if not entry.name.startswith(SUITE_HOME_PREFIX):
            continue
        if keep is not None and entry == keep:
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed.append(entry.name)
    return removed


#: Held for the life of the process; its finaliser removes the directory.
#: ``ignore_cleanup_errors`` so the atexit hook below can run the same
#: cleanup a second time without raising during interpreter shutdown.
_SUITE_HOME = tempfile.TemporaryDirectory(
    prefix=SUITE_HOME_PREFIX, ignore_cleanup_errors=True,
)
# Belt and braces: the weakref finaliser is not guaranteed to run at
# shutdown, and an atexit hook is (for every exit short of a signal kill).
atexit.register(_SUITE_HOME.cleanup)
# And for the kills that skip atexit too, clear out what earlier runs left.
sweep_stale_suite_homes(
    Path(tempfile.gettempdir()), Path(_SUITE_HOME.name),
)
#: The operator's real home, kept only so a test can assert we left it.
REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = _SUITE_HOME.name
os.environ.pop("XDG_CACHE_HOME", None)
# A stray ZOTERO_DATA_DIR points a test at the operator's real Zotero
# library (audit round 4a-2 addendum); the suite supplies its own.
os.environ.pop("ZOTERO_DATA_DIR", None)
Path(_SUITE_HOME.name, ".cache").mkdir(parents=True, exist_ok=True)
# A minimal identity, so a throwaway repository can commit without
# borrowing the operator's name or failing outright.
Path(_SUITE_HOME.name, ".gitconfig").write_text(
    "[user]\n\tname = Personal Assistant Tests\n"
    "\temail = tests@personal-assistant.invalid\n",
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Hermeticity: no route to a real PostgreSQL, for ANY caller
#
# The ``no_live_postgres`` fixture below patches ``psycopg2.connect``. Two
# holes survived that (audit round 4a-2, finding M8):
#
#   * a module that did ``from psycopg2 import connect`` at import time bound
#     the REAL function before the fixture ever ran, and calling it reached
#     the driver;
#   * scripts that shell out to ``psql`` (monthly-archive.py,
#     check-memory-drift.py) never touch psycopg2 at all.
#
# Both are closed here, at import time so that env changes are in place before
# any module constant is baked and before any subprocess is spawned:
#
#   * ``PGHOST`` points at an empty directory inside the suite's own home, so
#     libpq looks for a Unix socket that cannot be there and fails
#     immediately. ``PGHOSTADDR`` is removed (it would override PGHOST) and
#     ``PGPORT`` is pinned so a TCP fallback has nothing to reach either.
#     This covers psycopg2 and psql alike, since both go through libpq.
#   * a stub ``psql`` is placed FIRST on ``PATH``; it exits 1 with a message
#     naming the suite, so a script that shells out gets a clean refusal
#     rather than the operator's database.
#
# All of this lives in this process's environment only: it is inherited by
# test subprocesses and by nothing else. No shell profile, no settings file,
# and no file outside the suite's temporary home is touched, so nothing here
# can reach a cron run, a hook, or an interactive session.
# ---------------------------------------------------------------------------

#: An empty directory: libpq will look for ``.s.PGSQL.<port>`` in it and fail.
_NO_PG_SOCKET_DIR = Path(_SUITE_HOME.name, "no-postgres-here")
_NO_PG_SOCKET_DIR.mkdir(parents=True, exist_ok=True)
os.environ["PGHOST"] = str(_NO_PG_SOCKET_DIR)
os.environ.pop("PGHOSTADDR", None)  # would take precedence over PGHOST
os.environ["PGPORT"] = "1"          # nothing listens on port 1
os.environ.pop("PGSERVICE", None)   # a service file could name a real host
os.environ.pop("PGSERVICEFILE", None)

#: Text the stub prints, asserted by ``test_hermeticity_fixture.py``.
PSQL_STUB_MESSAGE = "psql refused by the test suite"

_STUB_BIN = Path(_SUITE_HOME.name, "bin")
_STUB_BIN.mkdir(parents=True, exist_ok=True)
_PSQL_STUB = _STUB_BIN / "psql"
_PSQL_STUB.write_text(
    "#!/bin/sh\n"
    f'echo "{PSQL_STUB_MESSAGE}: $*" >&2\n'
    "exit 1\n",
    encoding="utf-8",
)
_PSQL_STUB.chmod(0o755)
os.environ["PATH"] = f"{_STUB_BIN}{os.pathsep}{os.environ.get('PATH', '')}"


#: The pytest marker that quarantines a test needing a live service, and
#: the exact name ``pytest.ini`` deselects with ``-m "not integration"``.
#: Named here because the structural guard in
#: ``test_hermeticity_fixture.py`` looks for this spelling on a decorator:
#: with the word inlined in the guard, renaming the marker in ``pytest.ini``
#: would leave the guard hunting for a decorator nobody writes any more,
#: reporting a clean suite while every live-resource test ran (eleventh
#: re-audit follow-up L1). ``test_the_marker_name_matches_pytest_ini`` ties
#: the two together.
INTEGRATION_MARKER = "integration"


@pytest.fixture
def tmp_pa_dir(tmp_path):
    """Create a temporary personal-assistant directory structure."""
    (tmp_path / "memories").mkdir()
    (tmp_path / "tasks").mkdir()
    (tmp_path / "logs").mkdir()
    return tmp_path


@pytest.fixture
def sample_memories():
    """Sample memory records for testing."""
    return [
        {
            "id": "2026-02-07-abc123",
            "session_id": "test-session-1",
            "project": "-home-shawn-test-project",
            "source": "extraction",
            "category": "decision",
            "content": "Use PostgreSQL for memory queries.",
            "confidence": "high",
            "research_tags": ["database", "architecture"],
            "source_context": "Phase 2 planning",
            "created_at": "2026-02-07T10:00:00+00:00",
        },
        {
            "id": "2026-02-07-def456",
            "session_id": "test-session-1",
            "project": "-home-shawn-test-project",
            "source": "manual",
            "category": "commitment",
            "content": "Finish results section by Friday.",
            "confidence": "high",
            "research_tags": ["mirror-recoating", "deadline"],
            "source_context": "Manual capture via /remember",
            "created_at": "2026-02-07T12:00:00+00:00",
            "deadline_at": "2026-02-13T15:00:00+11:00",
        },
        {
            "id": "2026-02-08-ghi789",
            "session_id": "test-session-2",
            "source": "extraction",
            "category": "progress",
            "content": "Phase 3 implementation complete.",
            "confidence": "medium",
            "research_tags": ["gtd-implementation"],
            "source_context": "Session summary",
            "created_at": "2026-02-08T09:00:00+00:00",
        },
    ]


@pytest.fixture
def sample_focus_md():
    """Sample FOCUS.md content with 3 slots."""
    return """# Current Focus

**Last updated:** 2024-02-08 (standup)
**Focus check:** 3 of 3 slots filled

---

## Slot 1: Mirror recoating

- **Project:** observatory/optics
- **Started:** 2024-02-06
- **Deadline:** 2024-02-28
- **Why this matters:** End-of-February deadline.
- **Next action:** Book the coating chamber.
- **Blocked by:** Nothing

---

## Slot 2: Dome automation

- **Project:** observatory/dome
- **Started:** 2024-02-08
- **Deadline:** None
- **Why this matters:** Shutter controller documentation.
- **Next action:** Review the driver output.
- **Blocked by:** Nothing

---

## Slot 3: Observing run prep

- **Project:** observatory/scheduling
- **Started:** 2024-02-08
- **Deadline:** 2024-02-25
- **Why this matters:** First run 25 Feb.
- **Next action:** Check roster access.
- **Blocked by:** Possibly roster access

---

## Paused (Must Finish Focus Before Resuming)

| Item | Project | Paused Since | Why Paused |
|------|---------|--------------|------------|

---

## Rules

1. **Max 3 focus items.** (Raised from 2 on 2024-02-08.)
2. **Finish or explicitly abandon** before starting something new.
3. **If stuck for 3+ days**, something is wrong. Surface it.
4. **Paused items are paused**, not "also working on." Don't touch them.
"""


@pytest.fixture
def sample_system_md():
    """Sample SYSTEM.md content."""
    return """# System Configuration

Last updated: 2024-02-08

## Parameters

| Parameter | Current | Default | Notes |
|-----------|---------|---------|-------|
| focus_limit | 3 | 2 | Max items in FOCUS.md |
| escalation_question_day | 3 | 3 | When to start asking questions |
| escalation_confront_day | 7 | 7 | When to get confrontational |
| escalation_abandon_day | 14 | 14 | When to discuss abandonment |
"""




# ---------------------------------------------------------------------------
# Hermeticity: the PG* environment must survive every test
#
# The PGHOST repoint above is the only thing standing between an
# import-bound ``from psycopg2 import connect`` and the operator's database,
# because psycopg2 opens its socket in C where the network guard cannot see
# it. A fixture that repoints PGHOST and forgets to restore it therefore
# re-opens that door for every test that follows — reproduced in a copy, with
# ``server_version`` coming back from the real server (audit round 4a-3,
# finding M5).
#
# So the whole PG* environment is snapshotted around every test, RESTORED
# unconditionally (one offending test must not poison the rest of the run),
# and then compared. A test that genuinely needs to vary it declares
# ``@pytest.mark.pg_env`` and is exempt from the comparison — never from the
# restore. Note that ``monkeypatch.setenv`` is NOT sufficient on its own:
# pytest may tear this fixture down before monkeypatch's undo runs, in which
# case the guard sees the mutation. Mark such a test; the restore below
# happens either way, so nothing leaks whichever order they run in.
# ---------------------------------------------------------------------------

#: The marker that exempts a test from the PG-environment comparison.
PG_ENV_MARKER = "pg_env"


def pg_env_snapshot() -> dict[str, str]:
    """Every ``PG*`` variable currently in the environment.

    The whole prefix rather than a hand-listed few: PGHOST, PGHOSTADDR,
    PGPORT, PGSERVICE, and PGSERVICEFILE all steer a connection, and so do
    PGDATABASE, PGUSER, and PGPASSFILE. A list would go stale; the prefix
    cannot.
    """
    return {
        key: value for key, value in os.environ.items() if key.startswith("PG")
    }


def assert_pg_env_unchanged(
    before: dict[str, str], after: dict[str, str], nodeid: str,
) -> None:
    """Raise if a test changed where libpq would connect.

    A named function rather than an inline assert so its behaviour can be
    exercised in-process, the way the canonical-store guard's is.
    """
    changed = sorted(
        key for key in set(before) | set(after)
        if before.get(key) != after.get(key)
    )
    assert not changed, (
        f"{nodeid} changed the PG* environment and did not restore it: "
        f"{ {key: (before.get(key), after.get(key)) for key in changed} }. "
        f"psycopg2 connects in C, below the network guard, so these "
        f"variables are what keeps an import-bound connector away from the "
        f"operator's database. Use monkeypatch (which restores), or mark the "
        f"test @pytest.mark.{PG_ENV_MARKER} if it must vary them."
    )


@pytest.fixture(autouse=True)
def pg_env_unchanged(request):
    """Restore the PG* environment after every test, and flag the offender."""
    before = pg_env_snapshot()
    yield
    after = pg_env_snapshot()
    # Restore FIRST, unconditionally: whether or not this test is allowed to
    # have changed things, the next one must start from the dead end.
    for key in set(after) - set(before):
        os.environ.pop(key, None)
    for key, value in before.items():
        os.environ[key] = value
    if request.node.get_closest_marker(PG_ENV_MARKER) is not None:
        return
    assert_pg_env_unchanged(before, after, request.node.nodeid)


# ---------------------------------------------------------------------------
# Hermeticity: the suite must not open a network connection
#
# A probe test that stood up a local TCP server and connected to it passed
# with no complaint, which means an escaped httpx, pyzotero, urllib, or Slack
# call from any test would have reached the real internet (audit round 4a-2
# addendum). Nothing else in the suite was watching sockets at all.
#
# WHAT THIS GUARD ACTUALLY COVERS (audit round 4a-3, finding M4 — the
# previous comment claimed "DEFAULT DENY" without qualification, which
# overstated it):
#
#   Covered — calls made IN THIS PROCESS through the Python ``socket``
#   module's own class and helpers: ``socket.socket.connect``,
#   ``socket.socket.connect_ex``, ``socket.create_connection`` (TCP), and
#   ``socket.socket.sendto`` / ``socket.socket.sendmsg`` with an explicit
#   destination (connectionless UDP). That is the surface httpx, requests,
#   urllib, pyzotero, and the Slack SDK all sit on.
#
#   NOT covered, measured from inside a run:
#     1. ``_socket.socket()`` — the C accelerator class underneath. Patching
#        the Python subclass does not touch it, so code that reaches for the
#        private module bypasses this entirely. Nothing in this repo does.
#     2. Child processes. A subprocess got to 1.1.1.1:80 while this guard was
#        armed, because it is process-local monkeypatching and nothing more.
#        What covers children is the ENVIRONMENT set above — PGHOST at a dead
#        end and a stub ``psql`` first on PATH — plus the fact that the shell
#        paths the suite runs (daily-sync and its harness) operate on
#        throwaway git repositories whose remotes are local directories, so
#        they have nowhere to dial out to. A new test that shells out to
#        something network-capable is NOT protected by this guard and must
#        stub the client itself.
#     3. psycopg2. It opens its socket in C, below the Python socket module,
#        so this guard never sees it; the PGHOST/PGPORT repoint and the
#        ``no_live_postgres`` fixture are what cover PostgreSQL.
#
# Policy within the covered surface: DEFAULT DENY, with an explicit opt-in
# that is ALSO restricted to loopback. Allowing loopback unconditionally was
# rejected: this machine runs the operator's real PostgreSQL and Ollama on
# 127.0.0.1, so "it is only localhost" is not a safety boundary here — a
# stray connection could reach a live service and, in Ollama's case, spend
# GPU time. A test that genuinely owns a server it started declares
# ``@pytest.mark.local_socket`` (registered in pytest.ini) and may then reach
# 127.0.0.1 or ::1 only; everything else, marked or not, is refused.
# ---------------------------------------------------------------------------

#: The marker that opts a test into loopback connections it owns.
LOCAL_SOCKET_MARKER = "local_socket"

#: Hosts an opted-in test may reach. Nothing routable, ever. Exactly the two
#: loopback addresses plus their names: the whole of 127.0.0.0/8 used to be
#: allowed while the comment promised 127.0.0.1, and a test binds 127.0.0.1,
#: so the wider range bought nothing (round 4a-3, low finding).
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "ip6-localhost"})

#: Updated by ``pytest_runtest_setup`` so a refusal can name the test that
#: caused it — a bare "no network" tells the reader nothing about where to
#: look — and reset by ``pytest_runtest_teardown`` so the opt-in cannot
#: outlive the test that asked for it.
_ACTIVE_TEST: dict[str, object] = {"nodeid": "<collection>", "local_socket": False}


def pytest_configure(config):
    """Register the opt-in marker even when pytest.ini is not the one in use."""
    config.addinivalue_line(
        "markers",
        f"{LOCAL_SOCKET_MARKER}: test connects to a loopback server it "
        f"started itself",
    )
    config.addinivalue_line(
        "markers",
        f"{PG_ENV_MARKER}: test deliberately varies a PG* environment "
        f"variable (it is restored either way)",
    )


def pytest_runtest_setup(item):
    """Record which test is running, and whether it may use a local socket."""
    _ACTIVE_TEST["nodeid"] = item.nodeid
    _ACTIVE_TEST["local_socket"] = (
        item.get_closest_marker(LOCAL_SOCKET_MARKER) is not None
    )


def pytest_runtest_teardown(item):
    """Drop the opt-in as soon as the test body is over.

    Without this the last marked test's permission stayed in force for
    everything that ran afterwards outside a test body — fixture finalisers,
    session teardown, and (until the next ``pytest_runtest_setup``) the
    collection of whatever came next (round 4a-3, low finding). A marked
    test's own finalisers therefore run WITHOUT the opt-in; closing a socket
    needs no permission, and failing closed is the right side to err on.
    """
    _ACTIVE_TEST["nodeid"] = f"{item.nodeid} (teardown)"
    _ACTIVE_TEST["local_socket"] = False


def _is_loopback(address) -> bool:
    """True only for an AF_INET/AF_INET6 address on the loopback interface.

    A Unix-domain path is deliberately NOT loopback: it is the route to the
    operator's PostgreSQL socket, which this guard exists to block.
    """
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if not isinstance(host, str):
        return False
    return host in _LOOPBACK_HOSTS


def _network_refusal(address, verb: str = "connect to") -> str:
    """The refusal text, naming the test and what it reached for."""
    return (
        f"refused by the test suite: no network. "
        f"{_ACTIVE_TEST['nodeid']} tried to {verb} {address!r}. "
        f"Mock the client, or — if the test owns a loopback server it "
        f"started itself — mark it @pytest.mark.{LOCAL_SOCKET_MARKER}."
    )


@pytest.fixture(scope="session", autouse=True)
def no_network():
    """Refuse outbound Python-level connections for the whole session.

    Patched at session scope rather than per test so a connection opened from
    a fixture, a background thread, or an import is caught too. See the
    section comment above for exactly what this does and does not reach.

    ``sendto``/``sendmsg`` are wrapped as well as ``connect``: a UDP datagram
    needs no connect at all, so a DNS query or a metrics packet would
    otherwise leave the machine unremarked (round 4a-3, finding M4). A
    CONNECTED datagram socket goes through ``connect`` first and is covered
    there.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection
    real_sendto = socket.socket.sendto
    real_sendmsg = socket.socket.sendmsg

    def guarded_connect(self, address):
        if _ACTIVE_TEST["local_socket"] and _is_loopback(address):
            return real_connect(self, address)
        raise AssertionError(_network_refusal(address))

    def guarded_connect_ex(self, address):
        if _ACTIVE_TEST["local_socket"] and _is_loopback(address):
            return real_connect_ex(self, address)
        raise AssertionError(_network_refusal(address))

    def guarded_create_connection(address, *args, **kwargs):
        if _ACTIVE_TEST["local_socket"] and _is_loopback(address):
            return real_create_connection(address, *args, **kwargs)
        raise AssertionError(_network_refusal(address))

    def guarded_sendto(self, data, *args):
        # sendto(data, address) or sendto(data, flags, address): the
        # destination is always the last positional argument.
        address = args[-1] if args else None
        if _ACTIVE_TEST["local_socket"] and _is_loopback(address):
            return real_sendto(self, data, *args)
        raise AssertionError(_network_refusal(address, verb="send a datagram to"))

    def guarded_sendmsg(self, buffers, ancdata=None, flags=0, address=None):
        if address is None:
            # No destination: this is a connected socket, and the connect
            # that got it there was guarded.
            return real_sendmsg(self, buffers, ancdata or [], flags)
        if _ACTIVE_TEST["local_socket"] and _is_loopback(address):
            return real_sendmsg(self, buffers, ancdata or [], flags, address)
        raise AssertionError(_network_refusal(address, verb="send a datagram to"))

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.create_connection = guarded_create_connection
    socket.socket.sendto = guarded_sendto
    socket.socket.sendmsg = guarded_sendmsg
    try:
        yield
    finally:
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex
        socket.create_connection = real_create_connection
        socket.socket.sendto = real_sendto
        socket.socket.sendmsg = real_sendmsg


# ---------------------------------------------------------------------------
# Hermeticity: the suite must not write ~/.cache at all
#
# Three separate times during the September 2026 audit a test wrote a real
# gate, sidecar, or refusal-memory file, putting a fabricated
# infrastructure problem in front of Shawn at his next session start. Each
# time the fix was another fixture, and each time the next new test forgot
# it. This asserts the property itself, once, for the whole run.
#
# HOME is the suite's own now (see above), so nothing here can reach the
# operator's files even if a test tries — and the guard is measuring a
# directory no other process writes, so it accuses only the suite.
# ---------------------------------------------------------------------------

#: Files under ~/.cache the assistant's infrastructure owns. A test that
#: creates, modifies, or DELETES one of these has escaped its tmp
#: directory, and every one of them is read at session start and relayed
#: to Shawn — so a stray write fabricates an infrastructure problem and a
#: stray delete hides a real one (eighth re-audit, finding M7).
_PIPELINE_CACHE_GLOBS = (
    "postgres-sync-*",
    "index-session-content-*",
    "daily-sync-gate",
    "daily-sync-last-run",
    "memory-drift-gate",
    "cc-archives-gate",
    "cc-archive-drift-gate",
    "syncthing-gate",
)


def _pipeline_cache_snapshot() -> dict[str, tuple[int, int]]:
    """Map every watched cache file to ``(mtime_ns, size)``.

    Size as well as mtime: a rewrite within the same clock tick can leave
    the mtime alone, and the whole point of this fixture is to catch the
    write nobody meant to make.
    """
    cache = Path.home() / ".cache"
    snapshot: dict[str, tuple[int, int]] = {}
    if not cache.is_dir():
        return snapshot
    for pattern in _PIPELINE_CACHE_GLOBS:
        for path in cache.glob(pattern):
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


# ---------------------------------------------------------------------------
# Hermeticity: no test may open a real PostgreSQL connection
#
# ``test_hermeticity_fixture.py`` already refuses a TEST that calls
# ``psycopg2.connect`` itself without the integration marker. It cannot see a
# test that calls production code which connects — and during audit round 4a a
# new surgical UPDATE in tag-gardening did exactly that: the merge tests opened
# the operator's live ``claude_memories`` and committed a transaction against
# it. The static guard stays (it names the offending line); this is the runtime
# net underneath it.
#
# A test that wants a fake connection patches ``psycopg2.connect`` itself, and
# that patch simply wins over this one. A test that genuinely needs the live
# server carries the ``integration`` marker and is deselected by default.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_live_postgres(request, monkeypatch):
    """Refuse a real ``psycopg2.connect`` from any non-integration test."""
    if request.node.get_closest_marker(INTEGRATION_MARKER) is not None:
        return
    try:
        import psycopg2
    except ImportError:  # pragma: no cover — no driver, nothing to guard
        return

    def refuse(*args, **kwargs):
        raise AssertionError(
            "this test opened a real PostgreSQL connection. Production code "
            "reached psycopg2.connect with nothing stubbed: inject a fake "
            "connection, patch psycopg2.connect, or mark the test "
            f"'{INTEGRATION_MARKER}' if it truly needs the live server."
        )

    monkeypatch.setattr(psycopg2, "connect", refuse)


#: Canonical files in the repo tree that no test may create, modify, or
#: delete. These are reached through the root symlinks (``memories`` ->
#: ``data/memories``, ``logs`` -> ``data/logs``), so they are resolved before
#: being watched: a test that writes the real path and one that writes the
#: symlink are the same event. HOME is the suite's own, but these paths come
#: from ``__file__``, not from ``~``, so the HOME repoint does not cover them
#: — and a test that forgets to patch a module's path constant lands here
#: (audit 2026-09-08, finding B4: reproduced in a copy, the tag-gardening
#: suite rewrote data/memories/memories.jsonl and stayed green).
_CANONICAL_FILES = (
    PROJECT_ROOT / "memories" / "memories.jsonl",
    PROJECT_ROOT / "memories" / "tag-vocabulary.txt",
)
#: Directories whose entire contents are watched, recursively. Widened by the
#: round 4a-2 addendum: a probe test clobbered global-claude-md/claude.md
#: (the source the composer reads), data/tasks/FOCUS.md, and
#: wiki/continuity.md in the checkout and the suite stayed green. Everything
#: here is instruction, task state, or executable code that a stray write
#: would corrupt silently.
_CANONICAL_DIRS = (
    PROJECT_ROOT / "logs",
    PROJECT_ROOT / "tasks",              # -> data/tasks
    PROJECT_ROOT / "global-claude-md",
    PROJECT_ROOT / "global-agent-guidance",
    PROJECT_ROOT / "wiki",
    PROJECT_ROOT / "commands",
    PROJECT_ROOT / "hooks",
    PROJECT_ROOT / "scripts",
)

#: Directory names skipped while walking the watched trees. ``__pycache__`` is
#: written by the interpreter itself the moment a test imports a script, so
#: watching it would fail every run for a reason that is not a leak.
_SNAPSHOT_SKIP_DIRS = frozenset({"__pycache__", ".git", ".pytest_cache"})


def _canonical_store_snapshot() -> dict[str, tuple[int, int] | None]:
    """Map every watched canonical path to ``(mtime_ns, size)``, or ``None``.

    ``None`` records "absent", so a test that CREATES one of these is caught
    as surely as one that rewrites it. Size as well as mtime: a rewrite
    within one clock tick can leave the mtime alone.

    Cost is one ``stat`` per file and no reads, over roughly 240 files, so a
    pair of snapshots adds milliseconds to a two-minute run.
    """
    snapshot: dict[str, tuple[int, int] | None] = {}

    def record(path: Path) -> None:
        resolved = path.resolve()
        try:
            stat = resolved.stat()
        except OSError:
            snapshot[str(resolved)] = None
            return
        snapshot[str(resolved)] = (stat.st_mtime_ns, stat.st_size)

    def walk(directory: Path) -> None:
        """Record every file AND directory under ``directory``.

        Directories are recorded with a ``(0, 0)`` sentinel rather than a
        stat: their mtime changes whenever a child is written, which the
        child's own entry already reports, so stat-ing them would double
        every diff. The sentinel is there purely so that CREATING an empty
        directory is caught — before this, a test could leave a new empty
        directory anywhere in the checkout and the guard saw nothing, since
        it recorded files alone (audit round 4a-3, low finding). Generated
        trees are skipped entirely, so ``__pycache__`` appearing during a
        run is not a diff.
        """
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink() and entry.is_dir():
                continue  # do not follow a symlinked subtree twice
            if entry.is_dir():
                if entry.name in _SNAPSHOT_SKIP_DIRS:
                    continue
                snapshot[str(entry.resolve())] = (0, 0)
                walk(entry)
            elif entry.is_file():
                record(entry)

    for path in _CANONICAL_FILES:
        record(path)
    for directory in _CANONICAL_DIRS:
        resolved_dir = directory.resolve()
        snapshot[str(resolved_dir)] = None if not resolved_dir.is_dir() else (0, 0)
        if resolved_dir.is_dir():
            walk(resolved_dir)
    return snapshot


def canonical_store_changes(
    before: dict[str, tuple[int, int] | None],
    after: dict[str, tuple[int, int] | None],
) -> list[str]:
    """Paths whose recorded state differs between two snapshots.

    Covers creation, modification, and deletion in one comparison, because
    ``None`` is a recorded state rather than an absent key.
    """
    return sorted(
        path for path in set(after) | set(before)
        if before.get(path) != after.get(path)
    )


def assert_canonical_store_untouched(
    before: dict[str, tuple[int, int] | None],
    after: dict[str, tuple[int, int] | None],
) -> None:
    """Raise if the suite created, modified, or deleted a canonical file.

    A named function rather than an inline assert so its behaviour can be
    exercised in-process by ``test_hermeticity_fixture.py`` — a guard whose
    own failure path is never executed is a guard nobody has checked (audit
    round 4a-2, finding M5).
    """
    touched = canonical_store_changes(before, after)
    assert not touched, (
        "the test suite wrote to the REAL checkout — the canonical memory "
        "store, the task files, the instruction sources, or the code. A test "
        "that forgot to patch a module's path constant rewrote the "
        "operator's data.\n"
        f"  touched: {touched}"
    )


@pytest.fixture(scope="session", autouse=True)
def no_real_cache_writes():
    """Fail the run if the suite touched a real pipeline file in ~/.cache.

    Also fails if a test left ``HOME`` pointing somewhere else: this
    guard resolves ``~`` at call time, so a test that repoints HOME and
    does not put it back moves the very thing being watched and makes the
    check vacuous.
    """
    home_before = os.environ.get("HOME")
    assert home_before == _SUITE_HOME.name, (
        "HOME was moved off the suite's own directory before the first "
        "test ran"
    )
    before = _pipeline_cache_snapshot()
    store_before = _canonical_store_snapshot()
    yield
    after = _pipeline_cache_snapshot()
    store_after = _canonical_store_snapshot()
    home_after = os.environ.get("HOME")

    # HOME first: a repointed HOME means the snapshot above was taken of
    # a different directory, so every other verdict here is meaningless
    # and the diagnosis has to name the real cause.
    assert home_after == home_before, (
        "a test left HOME repointed "
        f"({home_before!r} -> {home_after!r}); the hermeticity guard here "
        "resolves ~ at call time, so the rest of the run was watching the "
        "wrong directory. Use monkeypatch.setenv, which restores it."
    )

    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(
        path for path in set(after) & set(before)
        if after[path] != before[path]
    )
    assert not created and not modified and not deleted, (
        "the test suite wrote to the operator's real ~/.cache — a "
        "fabricated infrastructure problem would appear at their next "
        "session start, or a real one would have vanished.\n"
        f"  created:  {created}\n"
        f"  modified: {modified}\n"
        f"  deleted:  {deleted}"
    )

    # The canonical store is the graver case: a stray write there corrupts
    # the memory system itself, not a cache the pipeline can rebuild.
    assert_canonical_store_untouched(store_before, store_after)
