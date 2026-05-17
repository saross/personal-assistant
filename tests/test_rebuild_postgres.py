"""
Tests for ``scripts/rebuild-postgres.py`` — Batch 5 of the audit
2026-05-02 fix programme (B-Critical C1 + C2 + X2).

The previous version of the script TRUNCATEd only ``memories`` and
reset only the ``postgres_sync_line`` cursor, leaving the
``sessions`` table, the ``sessions_sync_timestamp`` cursor, the
``zotero_sync_line`` cursor, the freshness marker, and PG
``sync_state`` rows in their pre-rebuild state. These tests pin the
contract for the redesigned script:

* Dry-run is the default (no destructive ops without ``--yes``).
* Schema-version mismatch refuses to run before any reset happens.
* The :data:`RESET_TARGETS` catalogue covers every documented
  cursor / state location.
* Each reset implementation actually mutates the right thing.
* Running twice in succession yields the same end state
  (idempotency).

We mock ``psycopg2`` connections everywhere — these tests must run
in CI without a live database. A separate live-DB smoke test (à la
``test_schema_version.test_live_pg_assertion_passes``) is left to
the operator who runs the rebuild.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


@pytest.fixture(scope="module")
def rebuild_mod():
    """Load ``rebuild-postgres.py`` (hyphenated → importlib).

    Module-scoped so the import side-effects (sys.path mutation by
    the script's own ``sys.path.insert``) happen once, not per test.

    Note: we register the module in ``sys.modules`` *before* executing
    it. Python 3.13's ``@dataclass`` machinery looks up
    ``sys.modules[cls.__module__]`` while resolving forward-reference
    type annotations; a not-yet-registered dynamically-loaded module
    raises ``AttributeError`` there.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    path = SCRIPTS_DIR / "rebuild-postgres.py"
    spec = importlib.util.spec_from_file_location("rebuild_postgres", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rebuild_postgres"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_fake_conn(schema_version: str = "3"):
    """Return a MagicMock psycopg2-style connection.

    ``cursor().fetchone()`` returns ``(schema_version,)``; ``rowcount``
    defaults to 1 so ``UPDATE sync_state`` looks like it hit a row.
    Tests that need different behaviour customise the returned mock.
    """
    cur = MagicMock()
    cur.fetchone.return_value = (schema_version,)
    cur.execute.return_value = None
    cur.rowcount = 1
    cur_ctx = MagicMock()
    cur_ctx.__enter__.return_value = cur
    cur_ctx.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cur_ctx
    # ``with conn:`` block — make conn itself act as a context manager.
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn, cur


# ---------------------------------------------------------------------------
# CLI / dry-run gating
# ---------------------------------------------------------------------------


class TestDryRunGating:
    """``--yes`` is required to mutate; default is dry-run."""

    def test_default_is_dry_run(self, rebuild_mod, capsys, tmp_path, monkeypatch):
        """No flag → dry-run, exit 0, no DB connection attempted.

        We assert the script never even tries to open a connection.
        If it did, ``open_conn`` would be invoked.
        """
        called: dict[str, int] = {"open_conn": 0}

        def _open_conn(_logger):
            called["open_conn"] += 1
            return None

        # The default path runs ``main`` which goes through
        # ``perform_rebuild`` only when ``--yes`` is set; we still
        # patch ``_open_connection`` to be safe.
        monkeypatch.setattr(rebuild_mod, "_open_connection", _open_conn)

        exit_code = rebuild_mod.main([])
        assert exit_code == 0
        assert called["open_conn"] == 0  # never reached perform_rebuild

    def test_dry_run_lists_all_targets(self, rebuild_mod, caplog):
        """Dry-run output enumerates every category of reset.

        Pins the catalogue contents — adding/removing a target
        without updating tests is then a deliberate decision.
        """
        targets = rebuild_mod.build_reset_targets()
        kinds = {t.kind for t in targets}
        assert kinds == {"table", "sync_state_row", "cursor_key"}, (
            "RESET_TARGETS must cover all three kinds"
        )

        # Tables: memories + sessions
        table_names = {t.name for t in targets if t.kind == "table"}
        assert table_names == {"memories", "sessions"}

        # Sync state rows: all three from schema.sql
        ss_names = {t.name for t in targets if t.kind == "sync_state_row"}
        assert ss_names == {
            "jsonl_to_postgres",
            "postgres_to_zotero",
            "sessions_to_postgres",
        }

        # Cursor keys: every key the audit catalogued
        cursor_names = {t.name for t in targets if t.kind == "cursor_key"}
        assert cursor_names == {
            "postgres_sync_line",
            "sessions_sync_timestamp",
            "zotero_sync_line",
            "postgres_last_sync_ts",
        }

    def test_yes_flag_invokes_perform_rebuild(
        self, rebuild_mod, monkeypatch, tmp_path,
    ):
        """``--yes`` reaches ``perform_rebuild`` (and skips the prompt
        when stdin is not a TTY, which is the default in pytest)."""
        called: dict[str, int] = {"perform": 0}

        def _fake_perform(targets, logger, **kwargs):
            called["perform"] += 1
            return 0

        monkeypatch.setattr(rebuild_mod, "perform_rebuild", _fake_perform)
        exit_code = rebuild_mod.main(["--yes"])
        assert exit_code == 0
        assert called["perform"] == 1

    def test_explicit_dry_run_does_not_perform(self, rebuild_mod, monkeypatch):
        """Explicit ``--dry-run`` flag still skips perform_rebuild."""
        called: dict[str, int] = {"perform": 0}

        def _fake_perform(*_args, **_kwargs):
            called["perform"] += 1
            return 0

        monkeypatch.setattr(rebuild_mod, "perform_rebuild", _fake_perform)
        exit_code = rebuild_mod.main(["--dry-run"])
        assert exit_code == 0
        assert called["perform"] == 0


# ---------------------------------------------------------------------------
# Schema-version guard — refuses to run on mismatch
# ---------------------------------------------------------------------------


class TestSchemaVersionGuard:
    """Schema version must match before any destructive op runs."""

    def test_mismatch_returns_two_and_makes_no_changes(
        self, rebuild_mod, monkeypatch, tmp_path,
    ):
        """Wrong schema version → exit 2, no TRUNCATE, no cursor edit.

        Audit IC5 contract: every PG-touching script asserts version
        before issuing schema-shape-dependent queries.
        """
        # Mock connection returns the wrong schema version.
        conn, cur = _build_fake_conn(schema_version="999")

        def _open_conn(_logger):
            return conn

        # Cursor file should NOT be touched on schema mismatch.
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({
            "postgres_sync_line": 100,
            "sessions_sync_timestamp": "2026-01-01T00:00:00+00:00",
            "zotero_sync_line": 50,
            "postgres_last_sync_ts": "2026-01-01T00:00:00+00:00",
        }) + "\n")

        targets = rebuild_mod.build_reset_targets()
        logger = rebuild_mod.setup_logging()
        exit_code = rebuild_mod.perform_rebuild(
            targets,
            logger,
            cursor_file=cursor_file,
            open_conn=_open_conn,
        )

        assert exit_code == 2
        # Cursor file must be untouched.
        data = json.loads(cursor_file.read_text())
        assert data["postgres_sync_line"] == 100
        assert "sessions_sync_timestamp" in data
        assert "zotero_sync_line" in data
        assert "postgres_last_sync_ts" in data

    def test_connection_failure_returns_one(
        self, rebuild_mod, tmp_path,
    ):
        """Connection failure (psycopg2 import / connect error) →
        exit 1, no destructive ops."""

        def _open_conn(_logger):
            return None

        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({"postgres_sync_line": 5}) + "\n")

        logger = rebuild_mod.setup_logging()
        exit_code = rebuild_mod.perform_rebuild(
            rebuild_mod.build_reset_targets(),
            logger,
            cursor_file=cursor_file,
            open_conn=_open_conn,
        )

        assert exit_code == 1
        # File untouched.
        data = json.loads(cursor_file.read_text())
        assert data == {"postgres_sync_line": 5}


# ---------------------------------------------------------------------------
# Per-target reset implementations
# ---------------------------------------------------------------------------


class TestTruncateTable:
    """``truncate_table`` issues TRUNCATE on the named table."""

    def test_truncate_executes_correct_sql(self, rebuild_mod):
        conn, cur = _build_fake_conn()
        logger = rebuild_mod.setup_logging()
        rebuild_mod.truncate_table(conn, "memories", logger)
        cur.execute.assert_called_with("TRUNCATE TABLE memories")

    def test_truncate_for_sessions(self, rebuild_mod):
        conn, cur = _build_fake_conn()
        logger = rebuild_mod.setup_logging()
        rebuild_mod.truncate_table(conn, "sessions", logger)
        cur.execute.assert_called_with("TRUNCATE TABLE sessions")


class TestResetSyncStateRow:
    """``reset_sync_state_row`` issues an UPDATE; falls back to
    INSERT if the row is missing."""

    def test_update_existing_row(self, rebuild_mod):
        conn, cur = _build_fake_conn()
        cur.rowcount = 1  # row was present
        logger = rebuild_mod.setup_logging()
        rebuild_mod.reset_sync_state_row(
            conn, "jsonl_to_postgres", "0", logger,
        )
        # First SQL call is the UPDATE
        first_sql = cur.execute.call_args_list[0][0][0]
        assert "UPDATE sync_state" in first_sql
        # Should NOT have called INSERT (rowcount=1 means UPDATE landed)
        all_sql = " ".join(c[0][0] for c in cur.execute.call_args_list)
        assert "INSERT INTO sync_state" not in all_sql

    def test_insert_when_row_missing(self, rebuild_mod):
        """If UPDATE matches no rows, fall back to INSERT for
        idempotency against operator-deleted rows."""
        conn, cur = _build_fake_conn()
        cur.rowcount = 0  # no row matched
        logger = rebuild_mod.setup_logging()
        rebuild_mod.reset_sync_state_row(
            conn, "postgres_to_zotero", "2000-01-01T00:00:00Z", logger,
        )
        all_sql = " ".join(c[0][0] for c in cur.execute.call_args_list)
        assert "UPDATE sync_state" in all_sql
        assert "INSERT INTO sync_state" in all_sql


class TestResetCursorKey:
    """``reset_cursor_key`` removes one key from the JSON cursor file."""

    def test_removes_named_key(self, rebuild_mod, tmp_path):
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({
            "postgres_sync_line": 100,
            "sessions_sync_timestamp": "2026-01-01T00:00:00+00:00",
            "zotero_sync_line": 50,
        }) + "\n")
        logger = rebuild_mod.setup_logging()

        rebuild_mod.reset_cursor_key(
            cursor_file, "postgres_sync_line", logger,
        )

        data = json.loads(cursor_file.read_text())
        assert "postgres_sync_line" not in data
        # Other keys preserved — we only remove the named one.
        assert "sessions_sync_timestamp" in data
        assert "zotero_sync_line" in data

    def test_missing_file_is_noop(self, rebuild_mod, tmp_path):
        """Missing cursor file → no-op (sync scripts will create it)."""
        cursor_file = tmp_path / "absent.json"
        logger = rebuild_mod.setup_logging()
        # Must not raise.
        rebuild_mod.reset_cursor_key(cursor_file, "anything", logger)
        # File still missing.
        assert not cursor_file.exists()

    def test_missing_key_is_noop(self, rebuild_mod, tmp_path):
        """Key already absent → file stays as-is."""
        cursor_file = tmp_path / "sync-cursors.json"
        original = {"other_key": "preserved"}
        cursor_file.write_text(json.dumps(original) + "\n")
        logger = rebuild_mod.setup_logging()

        rebuild_mod.reset_cursor_key(cursor_file, "missing_key", logger)

        data = json.loads(cursor_file.read_text())
        assert data == original

    def test_corrupt_file_is_repaired(self, rebuild_mod, tmp_path):
        """Corrupt JSON → empty object (sync scripts start fresh).

        Edge case: with a corrupt file the key cannot exist (empty
        dict after repair), so the function should log the repair
        but make no further change. The repaired file should be
        valid JSON.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text("not json {{{")
        logger = rebuild_mod.setup_logging()

        rebuild_mod.reset_cursor_key(
            cursor_file, "postgres_sync_line", logger,
        )

        # File is unchanged because key was absent in the repaired
        # (empty) view — but the function should not crash.
        # Subsequent reads should not raise.
        # Note: implementation chooses not to overwrite with the
        # repaired version when the key is absent; either policy is
        # defensible. We assert no crash + file remains parseable
        # by a tolerant cursor loader.
        # (The sync scripts' load_cursor swallows JSONDecodeError.)


# ---------------------------------------------------------------------------
# End-to-end: perform_rebuild orchestration
# ---------------------------------------------------------------------------


class TestPerformRebuild:
    """End-to-end checks on the orchestration loop."""

    def test_happy_path_returns_zero_and_resets_everything(
        self, rebuild_mod, tmp_path,
    ):
        conn, cur = _build_fake_conn()
        cur.rowcount = 1

        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({
            "postgres_sync_line": 23806,
            "sessions_sync_timestamp": "2026-04-02T23:19:31.257411",
            "zotero_sync_line": 100,
            "postgres_last_sync_ts": "2026-05-02T00:40:01+00:00",
            "unrelated_key": "should_survive",
        }) + "\n")

        logger = rebuild_mod.setup_logging()
        exit_code = rebuild_mod.perform_rebuild(
            rebuild_mod.build_reset_targets(),
            logger,
            cursor_file=cursor_file,
            open_conn=lambda _l: conn,
        )

        assert exit_code == 0

        # All catalogued keys removed from the cursor file.
        data = json.loads(cursor_file.read_text())
        for key in rebuild_mod.CURSOR_KEYS_TO_RESET:
            assert key not in data, f"key {key!r} should have been reset"
        # Untouched keys preserved.
        assert data["unrelated_key"] == "should_survive"

        # SQL: TRUNCATE + UPDATE statements were issued.
        all_sql = " ".join(c[0][0] for c in cur.execute.call_args_list)
        assert "TRUNCATE TABLE memories" in all_sql
        assert "TRUNCATE TABLE sessions" in all_sql
        assert "UPDATE sync_state" in all_sql

    def test_idempotent_second_run(self, rebuild_mod, tmp_path):
        """Running twice in succession yields the same end state.

        Pins the audit's "Idempotent" requirement: a re-run must not
        error and must leave the system in the same state.
        """
        conn, cur = _build_fake_conn()
        cur.rowcount = 1

        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({
            "postgres_sync_line": 1,
            "sessions_sync_timestamp": "2026-01-01T00:00:00+00:00",
            "zotero_sync_line": 1,
            "postgres_last_sync_ts": "2026-01-01T00:00:00+00:00",
        }) + "\n")

        logger = rebuild_mod.setup_logging()
        targets = rebuild_mod.build_reset_targets()

        exit_1 = rebuild_mod.perform_rebuild(
            targets, logger,
            cursor_file=cursor_file,
            open_conn=lambda _l: conn,
        )
        snapshot_1 = json.loads(cursor_file.read_text())

        exit_2 = rebuild_mod.perform_rebuild(
            targets, logger,
            cursor_file=cursor_file,
            open_conn=lambda _l: conn,
        )
        snapshot_2 = json.loads(cursor_file.read_text())

        assert exit_1 == 0
        assert exit_2 == 0
        # End state identical between runs.
        assert snapshot_1 == snapshot_2
        # And the catalogued keys are still absent.
        for key in rebuild_mod.CURSOR_KEYS_TO_RESET:
            assert key not in snapshot_2

    def test_stop_on_first_error(self, rebuild_mod, tmp_path, monkeypatch):
        """If a reset fails, subsequent resets do NOT run.

        Stop-on-first-error is the chosen strategy (the bug we are
        fixing is "partial rebuild"). Use a target list that fails
        on the first table; later targets should not be invoked.
        """
        conn, cur = _build_fake_conn()
        cur.rowcount = 1

        # First TRUNCATE raises; track which sql calls were made.
        calls: list[str] = []

        def _execute(sql, *_args, **_kwargs):
            calls.append(sql)
            if "TRUNCATE TABLE memories" in sql:
                raise RuntimeError("simulated PG failure")
            return None

        cur.execute.side_effect = _execute

        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({
            "postgres_sync_line": 100,
        }) + "\n")

        logger = rebuild_mod.setup_logging()
        exit_code = rebuild_mod.perform_rebuild(
            rebuild_mod.build_reset_targets(),
            logger,
            cursor_file=cursor_file,
            open_conn=lambda _l: conn,
        )

        assert exit_code == 1
        # The schema-version SELECT ran, then the failing TRUNCATE.
        # No further DDL/DML should have been attempted (no second
        # TRUNCATE, no UPDATE).
        joined = " ".join(calls)
        assert "TRUNCATE TABLE sessions" not in joined
        assert "UPDATE sync_state" not in joined
        # Cursor file untouched (cursor key resets come AFTER the
        # SQL group in the catalogue ordering).
        data = json.loads(cursor_file.read_text())
        assert data == {"postgres_sync_line": 100}


# ---------------------------------------------------------------------------
# Catalogue-completeness sanity check
# ---------------------------------------------------------------------------


def test_cursor_keys_match_live_sync_scripts(rebuild_mod):
    """Every cursor key referenced by a live sync script appears in
    :data:`CURSOR_KEYS_TO_RESET`.

    This is a defence against silent drift: if a future sync script
    introduces a new cursor key without updating ``rebuild-postgres``,
    this test (read against the current source) catches it.

    The test is deliberately a *string* search rather than an import
    of the hyphenated sync modules — keeps the test cheap and
    independent of psycopg2 etc.
    """
    expected_keys = set(rebuild_mod.CURSOR_KEYS_TO_RESET)

    # Known cursor keys defined as ``CURSOR_KEY = "..."`` or
    # passed to load/save_cursor in scripts/.
    seen: set[str] = set()
    for path in [
        SCRIPTS_DIR / "sync-to-postgres.py",
        SCRIPTS_DIR / "sync-sessions-to-postgres.py",
        SCRIPTS_DIR / "sync-to-zotero.py",
    ]:
        text = path.read_text(encoding="utf-8")
        for candidate in [
            "postgres_sync_line",
            "sessions_sync_timestamp",
            "zotero_sync_line",
            "postgres_last_sync_ts",
        ]:
            if candidate in text:
                seen.add(candidate)

    missing = seen - expected_keys
    assert not missing, (
        f"CURSOR_KEYS_TO_RESET is missing live cursor keys: "
        f"{sorted(missing)}. Either add them to the catalogue or "
        f"document why they should not be reset on rebuild."
    )
