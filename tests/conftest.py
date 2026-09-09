"""
Shared fixtures for personal-assistant test suite.

Provides temporary directories and sample data for hook testing
without touching the real memory system.

Hermeticity guards
------------------
Several session-scoped guards live here. They are described where they are
defined; the one thing a reader needs up front is the environment switch:

``PA_HERMETICITY_STRICT=1``
    Makes a change to the checkout's SOURCE trees (``wiki/``,
    ``scripts/``, ``hooks/``, ``commands/``, ``tests/``,
    ``global-claude-md/``, ``global-agent-guidance/``, ``tasks/``) fail
    the run instead of warning, and makes shared-checkout noise in the
    store (a ``*.lock`` file, a log rotation) fatal too. Set it in a
    clean copy — a ``git archive`` export, a re-audit, CI — where
    nothing but the suite is writing. Leave it unset in a working
    checkout: this repository is worked by several concurrent sessions
    by design (see CLAUDE.md), a run takes about two minutes, and
    another session editing a wiki page in that window is ordinary work,
    not a test misbehaving.

    An archive export has no ``data/`` submodule, so the store paths
    dangle and the store half is INERT there; the run says so under the
    ``hermeticity`` banner at the end. ``commands/audit.md`` carries the
    two invocations that between them cover both halves.

    The canonical memory store and ``logs/`` are strict in BOTH modes,
    with one allowance: an APPEND by the live system (the extraction
    hook adding a memory, a script adding a log line) is verified as an
    append — the earlier bytes must still hash to what they hashed at
    session start, and the appended text must be the shape that writer
    produces — and then tolerated, WITH ITS PATH AND BYTE COUNT
    REPORTED. A shrink, a rewritten prefix, a deletion, a new file, or
    appended text of the wrong shape is a failure either way.

    What that leaves uncaught, stated plainly: a test that forgets to
    patch its path and appends a SHAPE-CORRECT record to the real
    memories.jsonl passes in both modes. The guard cannot tell that
    append apart from the extraction hook's — they are the same
    operation with the same result. It is reported, and the shape check
    means the line must be a complete record with id, content and
    created_at, but a test writing exactly that is not stopped. See
    commands/audit.md for why closing it is not attempted here.

"""

import atexit
import hashlib
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




def describe_tolerated_kind(entry: str) -> str:
    """Name the class of one tolerated entry.

    Every entry used to be labelled "a lock file or a rotation", including a
    half-written append, which told the reader the wrong thing about the one
    case where knowing which it was actually matters (round 4a-6, L6).
    """
    if "not terminated" in entry:
        return "an append in progress"
    path = entry.split(" (")[0]
    if path.endswith(".lock"):
        return "a lock file"
    if path.endswith(_TOLERATED_NEW_LOG_SUFFIXES):
        stem = path
        for suffix in _COMPRESSION_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        base, _, tail = stem.rpartition(".")
        if tail.isdigit() or stem != path:
            return "a log rotation"
        return "a new log file"
    if any(path.endswith(suffix) for suffix in _COMPRESSION_SUFFIXES):
        return "a log rotation"
    stem, _, tail = path.rpartition(".")
    if tail.isdigit():
        return "a log rotation"
    return "a new directory or a rotated file"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Emit the hermeticity advisories where the operator will see them.

    A session-fixture teardown's ``print`` goes through pytest's capture and
    is discarded on a green run — measured at zero occurrences at ``-q`` and
    at default verbosity, visible only under ``-s`` (round 4a-4, finding
    M1). The terminal reporter writes straight to the real terminal, so
    everything queued in :data:`_DEFERRED_REPORT` lands whatever the capture
    mode.
    """
    coverage = strict_store_coverage_warning()
    report = dict(_DEFERRED_REPORT)
    if not report and not coverage:
        return
    terminalreporter.write_sep("=", "hermeticity", yellow=True)
    if coverage:
        terminalreporter.write_line(coverage, yellow=True)
    for path in report.get("source_changes", []):
        terminalreporter.write_line(
            f"WARNING: the checkout's source trees changed during this run: "
            f"{path}", yellow=True,
        )
    if report.get("source_changes"):
        terminalreporter.write_line(
            "  In a shared checkout this is usually a CONCURRENT SESSION, "
            f"not the suite. Set {STRICT_ENV_VAR}=1 where nothing else is "
            "writing to make it fatal.", yellow=True,
        )
    for line in report.get("appends", []):
        terminalreporter.write_line(
            f"note: the live system appended to {line}", yellow=True)
    for path in report.get("tolerated", []):
        terminalreporter.write_line(
            f"note: tolerated shared-checkout noise "
            f"({describe_tolerated_kind(path)}): {path}", yellow=True,
        )

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


@pytest.fixture(autouse=True)
def isolated_report(monkeypatch):
    """Give every test its own report queue, not the session's.

    ``report_source_tree_changes`` QUEUES into the module-level
    :data:`_DEFERRED_REPORT`, so a test driving it directly left its
    throwaway paths there and the session's terminal summary reported them
    as though the suite had touched the real checkout. It was an opt-in
    fixture; removing it from the one test that used it left 117 tests green
    while the run printed a warning about a path under pytest's basetemp
    (round 4a-6, finding M3). A guard that cries wolf is a guard that gets
    ignored, so the isolation is now automatic and a test cannot forget it.

    The session teardown runs after every test's fixtures are torn down, so
    it writes to the real queue and the terminal summary reports only what
    the SESSION found.
    """
    monkeypatch.setattr(_conftest_module(), "_DEFERRED_REPORT", {})
    return _DEFERRED_REPORT


def _conftest_module():
    """This module object, for monkeypatching its globals from a fixture."""
    return sys.modules[__name__]


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
        f"operator's database. Mark the test @pytest.mark.{PG_ENV_MARKER}: "
        f"monkeypatch.setenv alone is NOT enough, because this fixture "
        f"finalises before monkeypatch's undo runs and still sees the "
        f"change. The restore happens either way."
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
#: Watched trees whose files the LIVE SYSTEM appends to while the suite runs
#: — the extraction hook appending a memory, a script appending to a log. An
#: append there is legitimate and must not be reported (round 4a-3 addendum);
#: a shrink, a rewritten prefix, a deletion, or a NEW file still is.
_APPEND_TOLERANT_DIRS = (PROJECT_ROOT / "logs",)

#: Directories whose entire contents are watched, recursively. Widened by the
#: round 4a-2 addendum: a probe test clobbered global-claude-md/claude.md
#: (the source the composer reads), data/tasks/FOCUS.md, and
#: wiki/continuity.md in the checkout and the suite stayed green. Everything
#: here is instruction, task state, or executable code that a stray write
#: would corrupt silently.
_CANONICAL_DIRS = _APPEND_TOLERANT_DIRS + (
    PROJECT_ROOT / "tasks",              # -> data/tasks
    PROJECT_ROOT / "global-claude-md",
    PROJECT_ROOT / "global-agent-guidance",
    PROJECT_ROOT / "wiki",
    PROJECT_ROOT / "commands",
    PROJECT_ROOT / "hooks",
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "tests",              # advisory, like every source tree:
                                         # concurrent sessions edit tests too
)

#: Directory names skipped while walking the watched trees. ``__pycache__`` is
#: written by the interpreter itself the moment a test imports a script, so
#: watching it would fail every run for a reason that is not a leak.
_SNAPSHOT_SKIP_DIRS = frozenset({"__pycache__", ".git", ".pytest_cache"})

#: Filled during session teardown and emitted by
#: ``pytest_terminal_summary``, which writes through the terminal reporter
#: and is therefore not swallowed by pytest's output capture.
#:
#: A module-level queue that anything calling ``report_source_tree_changes``
#: writes into — including a TEST driving that function directly, which then
#: leaves its throwaway paths here for the session's summary to report as
#: though the suite had touched the real checkout. The autouse
#: ``isolated_report`` fixture below hands every test its own dict so that
#: cannot happen; only the session teardown writes to this one (round 4a-6,
#: finding M3, where removing the opt-in fixture left 117 tests green while
#: the run cried wolf about a basetemp path).
_DEFERRED_REPORT: dict[str, list[str]] = {}

#: The keys the extraction hook always writes. An appended memories.jsonl
#: line without them is not something the live system produced.
_REQUIRED_MEMORY_KEYS = frozenset({"id", "content", "created_at"})

#: Set this to make a change under a SOURCE tree fail the run rather than
#: warn. See :func:`report_source_tree_changes` for why it is off by default.
STRICT_ENV_VAR = "PA_HERMETICITY_STRICT"


def hermeticity_is_strict() -> bool:
    """Is the source-tree half of the guard set to fail rather than warn?"""
    return os.environ.get(STRICT_ENV_VAR, "") == "1"


def _append_tolerant_roots() -> tuple[str, ...]:
    """Resolved prefixes under which an append is not a violation."""
    return tuple(str(path.resolve()) for path in _APPEND_TOLERANT_DIRS)


def _is_append_tolerant(path: str) -> bool:
    """True for the two store files and anything under ``logs/``."""
    if path in {str(candidate.resolve()) for candidate in _CANONICAL_FILES}:
        return True
    return any(
        path == root or path.startswith(root + os.sep)
        for root in _append_tolerant_roots()
    )


def _digest_prefix(path: Path, length: int) -> str | None:
    """Hash the first ``length`` bytes of ``path``, or ``None`` if unreadable.

    Streamed in chunks so hashing a 45 MB corpus does not hold it in memory.
    """
    if length < 0:
        return None
    digest = hashlib.blake2b(digest_size=16)
    remaining = length
    try:
        with path.open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(1 << 20, remaining))
                if not chunk:
                    return None  # the file is shorter than it was
                remaining -= len(chunk)
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _canonical_store_snapshot(
    *, with_digests: bool = True,
) -> dict[str, tuple[int, int] | None]:
    """Map every watched canonical path to ``(mtime_ns, size)``, or ``None``.

    ``None`` records "absent", so a test that CREATES one of these is caught
    as surely as one that rewrites it. Size as well as mtime: a rewrite
    within one clock tick can leave the mtime alone.

    Cost is one ``stat`` per file over roughly 240 files, plus — on the
    session-start snapshot only, and only for the append-tolerant paths — a
    single streamed hash of each. Measured at 0.43 s per run against the
    live 45 MB corpus; the teardown snapshot does no hashing at all.
    """
    snapshot: dict[str, tuple[int, int] | None] = {}

    def record(path: Path) -> None:
        resolved = path.resolve()
        key = str(resolved)
        try:
            stat = resolved.stat()
        except OSError:
            snapshot[key] = None
            return
        if _is_append_tolerant(key):
            # Three-tuple: the digest is what lets an APPEND by the live
            # system be told apart from a rewrite. It is computed ONCE, on
            # the session-start snapshot; the teardown snapshot passes
            # ``with_digests=False`` because the comparison re-reads the
            # changed files from disk anyway.
            snapshot[key] = (
                stat.st_mtime_ns, stat.st_size,
                _digest_prefix(resolved, stat.st_size) if with_digests else None,
            )
        else:
            snapshot[key] = (stat.st_mtime_ns, stat.st_size)

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


def classify_store_changes(
    before: dict[str, object],
    after: dict[str, object],
) -> tuple[list[str], list[str], list[str]]:
    """Split the changed paths into (violations, appends, tolerated).

    ``appends`` are growth by the live system on an append-tolerant path
    (the two store files and ``logs/``): the size only GREW, the first ``old
    size`` bytes still hash to what they hashed at session start, and — for
    ``memories.jsonl`` and the vocabulary — the appended text is the shape
    that writer produces. Anything else about those paths is a violation.

    ``tolerated`` are the two shapes a shared checkout produces that are not
    appends and not the suite's doing either: a ``*.lock`` file appearing
    (``_bulk_rewrite_guard`` creates ``logs/daily-sync.lock``), and a log
    ROTATION — ``X`` renamed to ``X.1`` and a fresh ``X`` put in its place.
    They are violations under ``PA_HERMETICITY_STRICT``, where nothing else
    is running; the caller decides.

    Everything outside the append-tolerant roots is a violation here and is
    sorted into advisory or fatal by :func:`report_source_tree_changes`.

    The prefix is read at teardown, once, and only for files that changed,
    so the common case where nothing moved costs no I/O at all.
    """
    def comparable(entry):
        """The part of an entry that says whether the file CHANGED.

        The third slot of an append-tolerant entry is the session-start
        digest, which the teardown snapshot deliberately does not compute
        (``with_digests=False``). Comparing it would mark every store file
        as changed on every run.
        """
        if isinstance(entry, tuple) and len(entry) == 3:
            return entry[:2]
        return entry

    violations: list[str] = []
    appends: list[str] = []
    in_progress_appends: list[str] = []
    changed = [
        path for path in sorted(set(after) | set(before))
        if comparable(before.get(path)) != comparable(after.get(path))
    ]
    created = [path for path in changed if before.get(path) is None]

    for path in changed:
        old = before.get(path)
        new = after.get(path)
        if not _is_append_tolerant(path):
            violations.append(path)
            continue
        # Both states must be present files for an append to be possible.
        if not (isinstance(old, tuple) and isinstance(new, tuple)
                and len(old) == 3 and len(new) == 3):
            violations.append(path)
            continue
        _old_mtime, old_size, old_digest = old
        _new_mtime, new_size, _unused = new
        # ``old_digest is None`` means the file could not be read at session
        # start. Without it there is nothing to compare a prefix against, so
        # growth cannot be shown to be an append: fail closed.
        if new_size < old_size or old_digest is None:
            violations.append(path)
            continue
        if _digest_prefix(Path(path), old_size) != old_digest:
            violations.append(path)
            continue
        problem, in_progress = _appended_content_problem(Path(path), old_size)
        if problem is None:
            appends.append(path)
        elif in_progress:
            in_progress_appends.append(f"{path} ({problem})")
        else:
            violations.append(f"{path} ({problem})")

    tolerated = _shared_checkout_noise(violations, created, before)
    violations = [path for path in violations if path not in tolerated]
    return violations, appends, sorted(tolerated + in_progress_appends)


#: Suffixes logrotate adds when it compresses a rotated file.
_COMPRESSION_SUFFIXES = (".gz", ".bz2", ".xz", ".zst", ".Z")


#: New file extensions the live system creates under ``logs/``. The real
#: ``data/logs/`` holds ``drift-sweep.jsonl`` and
#: ``bulk-archive-manifest.json`` beside the ``*.log`` files, so restricting
#: the allowance to ``.log`` failed a shared-checkout run whenever one of
#: those appeared (round 4a-6, findings L4/L5).
_TOLERATED_NEW_LOG_SUFFIXES = (".log", ".json", ".jsonl")


def _shared_checkout_noise(
    violations: list[str], created: list[str], before: dict[str, object],
) -> list[str]:
    """Violations that a live checkout produces on its own, not the suite.

    All under the append-tolerant roots:

    * a ``*.lock`` file appearing — ``_bulk_rewrite_guard`` creates
      ``logs/daily-sync.lock`` the moment any bulk rewrite runs;
    * a rotation — ``X`` renamed to ``X.1`` (or ``.2``, ...) with a fresh
      ``X`` in its place, which shows up as a new ``X.N`` plus an ``X`` that
      appears to have shrunk. logrotate may also COMPRESS the rotated copy,
      so ``X.gz`` and ``X.1.gz`` count too;
    * a new ``*.log``, ``*.json`` or ``*.jsonl`` under ``logs/`` — output the
      live system started writing during the run;
    * a new DIRECTORY under ``logs/`` — ``data/logs/`` really does grow
      subtrees (``terra-enrich-responses/terra``), and a directory carries
      no content of its own; the first file written into it is judged on its
      own merits.

    Every one of these is advisory-only. Under ``PA_HERMETICITY_STRICT``
    nothing else is running, so the caller treats them as violations.
    """
    noise: set[str] = set()
    for path in created:
        if not _is_append_tolerant(path):
            continue
        if path.endswith(".lock"):
            noise.add(path)
            continue
        stem = path
        for suffix in _COMPRESSION_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        base, _, tail = stem.rpartition(".")
        rotated_from = None
        if tail.isdigit() and base in before:
            rotated_from = base          # X -> X.1 (optionally compressed)
        elif stem != path and stem in before:
            rotated_from = stem          # X -> X.gz, no number in between
        if rotated_from is not None:
            noise.add(path)
            if rotated_from in violations:
                # The fresh file that replaced it reads as a shrink.
                noise.add(rotated_from)
            continue
        if not _under_logs(path):
            # The two store files are append-tolerant but are NOT under
            # logs/: a CREATED memories.jsonl or tag-vocabulary.txt is the
            # suite building a store where there was none, never noise.
            continue
        if Path(path).is_dir():
            noise.add(path)
            continue
        if path.endswith(_TOLERATED_NEW_LOG_SUFFIXES):
            noise.add(path)
    return sorted(noise)


def _under_logs(path: str) -> bool:
    """Is ``path`` inside one of the append-tolerant log directories?

    Anchored on the separator so ``/logs-old/x`` is not read as being
    inside ``/logs``.
    """
    for directory in _APPEND_TOLERANT_DIRS:
        root = str(directory.resolve())
        if path.startswith(root + os.sep):
            return True
    return False


def _appended_content_problem(
    path: Path, old_size: int,
) -> tuple[str | None, bool]:
    """Why the bytes appended to ``path`` are not what its writer emits.

    Returns ``(problem, in_progress)``. ``problem`` is ``None`` when the
    appended text is plausible. ``in_progress`` is true when the ONLY thing
    wrong is that the last appended line has no terminating newline — a
    writer caught mid-line, or a crash-truncated tail. That is a normal
    sight in a live checkout and is tolerated in advisory mode, but it stays
    fatal under STRICT, where nothing should be writing at all (round 4a-5,
    finding 5).

    Growth alone used to be enough to call an append benign, so a test that
    appended a garbage line to the real ``memories.jsonl`` was classified as
    the live system doing its job (round 4a-4, finding M4). Only the two
    structured files are checked; a log line has no shape to check against.
    """
    resolved = str(path)
    canonical = {str(candidate.resolve()): candidate.name
                 for candidate in _CANONICAL_FILES}
    kind = canonical.get(resolved)
    if kind is None:
        return None, False  # a log file: nothing to validate
    try:
        with path.open("rb") as handle:
            handle.seek(old_size)
            tail = handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"the appended bytes could not be read as UTF-8: {exc}", False

    lines = tail.split("\n")
    # A trailing "" means the append ended on a newline; anything else in
    # that slot is a partial line still being written.
    partial = lines.pop() if lines else ""

    for line in lines:
        problem = _line_problem(kind, line)
        if problem is not None:
            return problem, False
    if partial.strip():
        # The complete lines are all fine, but the tail is unterminated.
        # Judge it too: with NO complete lines the loop above never ran, so
        # a lone unterminated garbage fragment used to be waved through as
        # "an append in progress" (round 4a-6, finding M2). A fragment is
        # only in-progress if what there is of it is still the right shape.
        problem = _line_problem(kind, partial)
        if problem is not None:
            return f"{problem} (and the line is unterminated)", False
        return ("the final appended line is not terminated — an append in "
                "progress, or a crash-truncated tail"), True
    return None, False


def _line_problem(kind: str, line: str) -> str | None:
    """Why one appended line is not what ``kind``'s writer emits."""
    stripped = line.strip()
    if kind == "memories.jsonl":
        if not stripped:
            return None
        try:
            record = json.loads(stripped)
        except ValueError:
            return "an appended line is not JSON"
        if not isinstance(record, dict):
            return "an appended line is not a JSON object"
        missing = _REQUIRED_MEMORY_KEYS - set(record)
        if missing:
            return f"an appended record lacks {sorted(missing)}"
        return None

    # tag-vocabulary.txt: one bare tag per line, plus comments and blanks.
    if not stripped or stripped.startswith("#"):
        return None
    # ``stripped != line`` — NOT ``line.strip()``, which is what ``stripped``
    # already is. The old disjunct compared a value with itself and could
    # never fire, so an indented append was accepted (round 4a-5, finding 3).
    if stripped != line or " " in stripped or "\t" in stripped:
        return "an appended vocabulary line is not a bare tag"
    return None


def assert_canonical_store_untouched(
    before: dict[str, object],
    after: dict[str, object],
    *,
    classified: tuple[list[str], list[str], list[str]] | None = None,
) -> tuple[list[str], list[str]]:
    """Raise if the suite created, modified, or deleted a canonical file.

    Returns ``(appends, tolerated)`` — the benign growth and the
    shared-checkout noise it let through — so the caller can report both.

    ``classified`` takes an already-computed
    :func:`classify_store_changes` result. The session teardown passes it,
    because both halves of the guard need the same answer and computing it
    twice hashed and content-checked every changed file twice over (round
    4a-5, finding 2).

    Under ``PA_HERMETICITY_STRICT`` the noise is fatal too: in a clean copy
    nothing else is running, so a lock file, a rotation, or a half-written
    line IS the suite's doing.

    A named function rather than an inline assert so its behaviour can be
    exercised in-process by ``test_hermeticity_fixture.py`` — a guard whose
    own failure path is never executed is a guard nobody has checked (audit
    round 4a-2, finding M5).
    """
    store_violations, appends, tolerated = store_findings(
        before, after, classified=classified)
    assert not store_violations, _store_failure_text(store_violations)
    return appends, tolerated


def store_findings(
    before: dict[str, object],
    after: dict[str, object],
    *,
    classified: tuple[list[str], list[str], list[str]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """The store half's verdict, without raising.

    Returns ``(store_violations, appends, tolerated)``. Split out from the
    assertion so the session teardown can collect BOTH halves before failing
    (round 4a-5, finding 6): a source edit landing in the same run used to
    raise first and hide the store violation underneath it.
    """
    violations, appends, tolerated = (
        classified if classified is not None
        else classify_store_changes(before, after)
    )
    # ``_is_append_tolerant`` is what splits the store half from the source
    # half here: a source-tree path in ``violations`` belongs to
    # report_source_tree_changes, not to this assertion. Dropping the filter
    # makes this raise on a concurrent session's wiki edit, which is the
    # false failure the whole advisory split exists to prevent.
    store_violations = [path for path in violations
                        if _is_append_tolerant(path.split(" (")[0])]
    if hermeticity_is_strict():
        store_violations = store_violations + tolerated
    return store_violations, appends, tolerated


def _store_failure_text(store_violations: list[str]) -> str:
    """The message for a store violation."""
    return (
        "the test suite wrote to the REAL canonical memory store or its "
        "logs. An APPEND by the live system is tolerated; this was not — a "
        "shrink, a rewritten prefix, a deletion, a new file, or appended "
        "text the writer would not produce. A test that forgot to patch a "
        "module's path constant rewrote the operator's data.\n"
        f"  touched: {store_violations}"
    )


def describe_tolerated_appends(
    before: dict[str, object], appends: list[str],
    after: dict[str, object] | None = None,
) -> list[str]:
    """One line per tolerated append, naming the path and the bytes added.

    Printed through the terminal reporter so it survives default capture: a
    test that forgot to patch a path and appended to the real store is
    otherwise invisible, since the append itself is classified benign
    (round 4a-4, finding M4).
    """
    lines: list[str] = []
    for path in appends:
        old = before.get(path)
        new = (after or {}).get(path)
        old_size = old[1] if isinstance(old, tuple) and len(old) == 3 else 0
        if isinstance(new, tuple) and len(new) == 3:
            new_size = new[1]
        else:
            try:
                new_size = Path(path).stat().st_size
            except OSError:
                new_size = old_size
        lines.append(f"{path} (+{new_size - old_size} bytes)")
    return lines


def strict_store_coverage_warning() -> str | None:
    """Under STRICT, say so when the store half is watching nothing.

    An export or a fresh worktree may have no ``data/`` submodule content,
    so ``memories/`` and ``logs/`` dangle and the store half of the guard is
    INERT — the one invocation that turns strict mode on was the one where
    the strictness bought nothing (round 4a-4, finding M2). The message
    names exactly what is missing rather than assuming a cause, because the
    same words used to claim "an archive export has no data/ submodule" from
    a worktree where only the two store files were absent (round 4a-5,
    finding 7).
    """
    if not hermeticity_is_strict():
        return None
    missing = [str(path) for path in _CANONICAL_FILES if not path.exists()]
    missing += [str(path) for path in _APPEND_TOLERANT_DIRS
                if not path.is_dir()]
    if not missing:
        return None
    return (
        f"{STRICT_ENV_VAR}=1, but these watched store paths are missing or "
        f"dangling here: {missing}. The store half of the hermeticity guard "
        "is INERT in this run; only the source-tree half is strict. (A "
        "git-archive export carries no data/ submodule, and a fresh worktree "
        "has it uninitialised.) Run where the store files exist to exercise "
        "that half."
    )


def report_source_tree_changes(
    before: dict[str, object],
    after: dict[str, object],
    *,
    classified: tuple[list[str], list[str], list[str]] | None = None,
    raise_on_strict: bool = True,
) -> list[str]:
    """Warn — or, under ``PA_HERMETICITY_STRICT=1``, fail — on source edits.

    This repository is worked by SEVERAL CONCURRENT SESSIONS by design
    (CLAUDE.md says so outright), and a suite run takes about two minutes.
    Another session editing ``wiki/continuity.md`` or a script in that window
    is ordinary, expected work — and failing the run for it blames the suite
    for something the suite did not do, which is the fastest way to get a
    guard switched off (round 4a-3 addendum, reproduced live).

    So in a shared checkout this is ADVISORY: a loud warning naming the
    paths, and the run continues. In a clean copy — a git-archive export, a
    re-audit, CI — nothing else is writing, so
    ``PA_HERMETICITY_STRICT=1`` makes the same finding fatal, which is where
    a test that really did write to the checkout gets caught.

    Returns the changed paths.
    """
    violations, _appends, _tolerated = (
        classified if classified is not None
        else classify_store_changes(before, after)
    )
    changed = [path for path in violations
               if not _is_append_tolerant(path.split(" (")[0])]
    if not changed:
        return changed
    detail = "\n".join(f"    {path}" for path in changed)
    if hermeticity_is_strict():
        if not raise_on_strict:
            # The session teardown collects both halves before failing, so
            # a simultaneous source edit cannot hide a store violation
            # underneath it (round 4a-5, finding 6).
            _DEFERRED_REPORT["source_changes"] = list(changed)
            return changed
        raise AssertionError(
            "the test suite changed the REAL checkout's source trees "
            f"({STRICT_ENV_VAR}=1, so this is fatal):\n{detail}"
        )
    # Queued for pytest_terminal_summary rather than printed here. A
    # session-fixture teardown's stdout and stderr are CAPTURED and thrown
    # away on a green run, so this warning reached the operator zero times
    # at default verbosity while its own test read capsys and stayed green
    # (round 4a-4, finding M1).
    _DEFERRED_REPORT["source_changes"] = list(changed)
    return changed


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
    # No digests on the second snapshot: the only prefix that matters is the
    # one from session start, and the comparison re-reads the changed files
    # itself. Hashing everything twice and discarding the second set was
    # pure waste (round 4a-4, finding L2).
    store_after = _canonical_store_snapshot(with_digests=False)
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
    # the memory system itself, not a cache the pipeline can rebuild. An
    # APPEND by the live system (the extraction hook, a log line) is
    # tolerated; anything else is not. The source trees are reported
    # separately, because a concurrent session editing them is ordinary work
    # — see report_source_tree_changes.
    # Classified ONCE and handed to both halves: each changed file is
    # hashed and content-checked a single time (round 4a-5, finding 2).
    classified = classify_store_changes(store_before, store_after)
    source_changes = report_source_tree_changes(
        store_before, store_after, classified=classified,
        raise_on_strict=False,
    )
    store_violations, appended, tolerated = store_findings(
        store_before, store_after, classified=classified)
    if appended:
        _DEFERRED_REPORT["appends"] = describe_tolerated_appends(
            store_before, appended, store_after)
    if tolerated:
        _DEFERRED_REPORT["tolerated"] = list(tolerated)

    # BOTH halves are reported before either one fails, so a source edit
    # landing in the same run cannot mask a store violation underneath it
    # (round 4a-5, finding 6). The notes above are queued either way, so the
    # terminal summary still explains a failing run.
    problems: list[str] = []
    if store_violations:
        problems.append(_store_failure_text(store_violations))
    if source_changes and hermeticity_is_strict():
        detail = "\n".join(f"    {path}" for path in source_changes)
        problems.append(
            "the test suite changed the REAL checkout's source trees "
            f"({STRICT_ENV_VAR}=1, so this is fatal):\n{detail}"
        )
    assert not problems, "\n\n".join(problems)
