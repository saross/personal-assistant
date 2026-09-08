#!/usr/bin/env python3
"""
index-session-content.py — populate the session_chunks transcript-content index.

Walks the cc-archives tree, parses each session transcript LINE BY LINE (never
collapsing newlines — see archive-search-crash-diagnosis-2026-06-21.md), extracts
the clean human/assistant prose (one chunk per conversational turn, skipping
thinking and tool noise), and upserts it into the PostgreSQL `session_chunks`
table. That table's GENERATED tsvector column auto-builds the full-text index.

This is the one place transcripts are decompressed; steady-state search then runs
entirely against the index and never touches a .gz. Safe by construction:
streaming gzip, one JSON line at a time, bounded memory, single process, niced.

Idempotent + incremental: a file is skipped when its mtime matches what was last
indexed, so re-runs are cheap. `--force` reindexes regardless. Re-indexing a file
replaces its rows transactionally (no stale turns).

Usage:
    venv/bin/python3 scripts/index-session-content.py            # all projects
    venv/bin/python3 scripts/index-session-content.py --project inscriptions
    venv/bin/python3 scripts/index-session-content.py --force
    venv/bin/python3 scripts/index-session-content.py --include-subagents

Scope note: by default only main session transcripts are indexed — that is
the human↔assistant conversation. Both storage forms (session.jsonl.gz and
raw session.jsonl) are handled. Subagent transcripts are mostly tool work;
include them with --include-subagents.

⛔ A `--force` full re-index feeds `session_chunks`, and the same gates as
`sync-sessions-to-postgres.py --full-resync` apply: see the rebuild
preconditions in global-claude-md/postgresql-reference.md.

Exit codes:
    0 - ran to completion (possibly indexing nothing)
    2 - psycopg2 is missing, or the database schema version is not the
        one this script was written against
    3 - PostgreSQL is unreachable (at connect time or mid-run). Not
        critical: the archive tree is canonical and the index can be
        rebuilt at any time by re-running this script.
    4 - environment fault: PostgreSQL is reachable but not in the expected
        state (permissions, a missing column, a full disk). Retrying will
        not help until someone changes something.
    5 - one or more files were REFUSED **this run** and are not
        searchable. Files refused on an earlier run do not fail the run;
        they are reported once at WARNING and through the gate.

Refusal memory:
    ~/.cache/index-session-content-refusals.json maps an archive path to
    the mtime it had when PostgreSQL refused it. A refused file is skipped
    until its mtime changes (i.e. until the transcript is repaired) or
    until --force retries it. Entries whose archive no longer exists are
    pruned automatically. Delete the file to retry everything.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from pathlib import Path
from typing import NamedTuple

# Schema-version guard (audit IC5 / B-X1). scripts/schema.sql states the
# contract: "Every PG-touching script asserts meta.schema_version ...
# before issuing any query." This was the one script in the Postgres
# tranche that did not (audit round two, finding P5 / lens A-M2).
# Imported by filesystem path because the script may be invoked from any
# working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sync_gate import (  # noqa: E402
    CYCLE_COMPLETED,
    CYCLE_DEGRADED,
    CYCLE_IDLE,
    CYCLE_OUTAGE,
    INDEXER_GATE as _DEFAULT_GATE_FILE,
    GateEvent,
    apply_gate,
    gate_lock,
    read_state,
)
from _schema_version import (  # noqa: E402
    SchemaVersionError,
    assert_schema_version,
)
# Row-level Postgres guards (audit round two, finding P1; re-audit M4).
from _pg_row_guard import (  # noqa: E402
    ENVIRONMENT,
    OUTAGE,
    classify_pg_error,
    sanitise_nuls,
)

DB_NAME = "claude_memories"
DEFAULT_ARCHIVE_ROOT = Path.home() / "cc-archives"


#: Where refused files are remembered between runs. Machine-local runtime
#: state, so ~/.cache rather than the data submodule: it is a "do not retry
#: this yet" note, rebuildable by deleting the file.
REFUSAL_FILE = Path.home() / ".cache" / "index-session-content-refusals.json"

# Session-start gate for this script (third re-audit, finding C1). Its own
# file: sharing one with the syncs meant either could erase the other's
# alarm. A module constant so tests can pin it to a tmp directory.
SCRIPT_NAME = "index-session-content.py"
GATE_FILE = _DEFAULT_GATE_FILE


class IndexResult(NamedTuple):
    """
    What one index run did.

    ``refused_now`` and ``refused_remembered`` are deliberately separate
    (third re-audit, finding C2). Conflating them made every later run
    exit 5 for ever over a file that had been refused once, weeks ago:
    the exit code stopped meaning "something happened this run" and
    started meaning "something once happened", which is not actionable
    and trains the reader to ignore it.
    """

    files_indexed: int
    files_skipped: int
    chunks: int
    refused_now: int
    refused_remembered: int


class IndexerAbort(RuntimeError):
    """
    The run cannot continue, and the exit code says why.

    Every abort path funnels through this so ``main`` has one thing to
    catch. Before it, ``main`` caught only ``ImportError``, so an outage
    or an environment fault *mid-run* produced a raw traceback while the
    identical fault at connect time degraded politely (second re-audit,
    finding M4).
    """

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
# Defence-in-depth cap: natural turn text is small; this only guards against a
# pathological block. Far below anything that would stress the row.
MAX_CHUNK_CHARS = 100_000

# Configure the root logger only if nothing has already done so. An
# unconditional ``basicConfig`` at import time reaches into whatever
# process imports this module — a test runner, or another script that
# imports it for its parsing helpers — and silently reconfigures its
# logging. Every other script in this tranche guards its logging setup;
# this one did not (re-audit, low finding).
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("index-session-content")


# --- Transcript parsing (line-oriented, bounded) ----------------------------

def extract_turn_text(
    record: dict,
    stats: dict[str, int] | None = None,
) -> str | None:
    """Return the clean prose of one user/assistant turn, or None to skip it.

    Keeps: user string content, and `text` blocks from either role. Drops:
    thinking, tool_use, tool_result blocks, and all non-message record types
    (permission-mode, attachment, system, …). This keeps the index prose-only,
    so searches match conversation, not tool noise or base64.

    B7 fix (2026-08-22): also drops machine-generated records that travel in
    the `user` transport envelope but are not the human speaking. Measured on
    2026-07-28 (transcript-archive-diagnosis §7a): 40.0% of indexed `user`
    chunks were not the user's words — `isMeta` records (41.2% of the false
    population), compact summaries (25.0%), and subagent task-notification
    reports (20.0%). A long articulate "user" turn was ~7× more likely to be
    machine text than human. These are skipped, never mislabelled.
    """
    if record.get("type") not in ("user", "assistant"):
        return None
    # Machine-injected records: not conversational turns, skip entirely.
    if record.get("isMeta") or record.get("isCompactSummary"):
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    # Authorship must be explicit. The old fallback promoted the transport
    # envelope (`type: "user"`) to a speaker attribution for any record
    # lacking message.role — the root of the one-directional mislabelling.
    if message.get("role") not in ("user", "assistant"):
        return None

    content = message.get("content")
    if isinstance(content, str):
        # Same NUL strip as the block path below — a plain-string turn is
        # just as capable of carrying one (re-audit finding M4).
        text, nuls = sanitise_nuls(content.strip())
        if nuls and stats is not None:
            stats["nuls_removed"] = stats.get("nuls_removed", 0) + nuls
        return text or None
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            piece = (block.get("text") or "").strip()
            if piece:
                parts.append(piece)
    if not parts:
        return None
    text = "\n".join(parts)
    # Harness-injected notifications ride the user envelope with a real
    # message.role but are not the human speaking either (B7, third
    # category). Content-shaped check because they carry no flag.
    head = text[:200]
    if head.startswith("[SYSTEM NOTIFICATION") or "<task-notification>" in head:
        return None
    # Strip NUL before the text can reach ``session_chunks.text`` (TEXT).
    # PostgreSQL cannot store U+0000 in a text column — psycopg2 raises
    # ValueError before the statement is even sent — and the same
    # LLM-generated prose that put NULs into two session.meta.json files
    # is what this indexes (re-audit finding M4). This is the ingest
    # boundary, so it is where the stripping belongs.
    text, nuls = sanitise_nuls(text)
    if nuls and stats is not None:
        stats["nuls_removed"] = stats.get("nuls_removed", 0) + nuls
    if not text:
        return None
    return text[:MAX_CHUNK_CHARS] if len(text) > MAX_CHUNK_CHARS else text


def open_transcript(path: Path):
    """Open a transcript for text reading, resolving gzip vs plain form.

    The archive holds both forms (729 gz-only, 88 raw-only, 34 dual as of
    2026-08-22) — any consumer that assumes one form silently drops the
    other population, which is the defect class behind the false "12-week
    hole" alarm. Suffix-based, with errors="replace" both ways.
    """
    if path.suffix == ".gz":
        return gzip.open(path, "rt", errors="replace")
    return open(path, "rt", errors="replace", encoding="utf-8")


def iter_turns(transcript_path: Path, stats: dict[str, int] | None = None):
    """Yield (turn_idx, role, text) for each prose turn in one transcript.

    ``stats`` is an optional counter dict; when given, the number of NUL
    characters stripped is accumulated under ``"nuls_removed"`` so the
    caller can report them (low finding L3).

    Streams one line at a time; a malformed line is skipped, never fatal.
    turn_idx is the ordinal of the source record in the file, so it is a
    stable handle for later retrieval of the exact turn.
    """
    try:
        with open_transcript(transcript_path) as handle:
            for idx, line in enumerate(handle):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                text = extract_turn_text(record, stats=stats)
                if text is None:
                    continue
                # extract_turn_text has already required message.role —
                # never fall back to the transport envelope (B7).
                role = record["message"]["role"]
                yield idx, role, text
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        logger.warning("  skipped %s (%s)", transcript_path.name, exc)


# --- Archive discovery ------------------------------------------------------

def session_id_for(session_dir: Path) -> str | None:
    """Read the session UUID from session.meta.json, if present."""
    meta = session_dir / "session.meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text())
        return (data.get("session") or {}).get("id")
    except (OSError, json.JSONDecodeError):
        return None


def discover(archive_root: Path, project: str | None, include_subagents: bool):
    """Yield (transcript_path, project, session_dir) for transcripts to index.

    Rewritten 2026-08-22 (backlog: archive-integrity session, indexer fixes).
    The old version iterated exactly two directory levels and skipped
    `_`-prefixed dirs, so the 267 sessions in nested locations
    (`map-reader-llm/vlm-burial-mound-detection/`, `LLM-History-Paper/
    theseus-ship/` pre-move, `_legacy/**`) were never indexed — a partial
    view silently presented as the whole. Discovery now walks
    session.meta.json recursively (the same rule `bulk-archive.py verify`
    uses), so placement depth no longer decides visibility.

    The project label prefers the meta's recorded `project.name` (the
    archive-layer identity) and falls back to the parent directory name.
    Both raw and gz transcript forms are yielded (gz preferred when both
    exist).
    """
    for meta_path in sorted(archive_root.rglob("session.meta.json")):
        session_dir = meta_path.parent
        parent_rel = session_dir.parent.relative_to(archive_root)
        proj_name = None
        try:
            meta = json.loads(meta_path.read_text())
            proj_name = (meta.get("project") or {}).get("name")
        except (OSError, json.JSONDecodeError):
            pass
        if not proj_name:
            proj_name = session_dir.parent.name
        if project and project not in (proj_name, str(parent_rel)):
            continue
        main = session_dir / "session.jsonl.gz"
        if not main.is_file():
            main = session_dir / "session.jsonl"
        if main.is_file():
            yield main, proj_name, session_dir
        if include_subagents:
            by_stem: dict[str, Path] = {}
            for sub in (session_dir / "subagents").glob("*.jsonl*"):
                stem = sub.name.removesuffix(".gz")
                # gz + raw pair: index one form only, preferring gz.
                if stem not in by_stem or sub.suffix == ".gz":
                    by_stem[stem] = sub
            for stem in sorted(by_stem):
                yield by_stem[stem], proj_name, session_dir


# --- Refusal memory ---------------------------------------------------------

#: The two forms one session transcript can take on disk. A refusal
#: recorded against either must be forgotten when the other is indexed.
TRANSCRIPT_FORMS: tuple[str, ...] = ("session.jsonl", "session.jsonl.gz")


def _forget_transcript(
    refusals: dict[str, float],
    rel_path: str,
) -> list[str]:
    """Drop this transcript's refusal entries, in both storage forms.

    Returns the keys removed. The archive holds transcripts as
    ``session.jsonl`` and ``session.jsonl.gz``, and the archiver converts
    between them; keying the memory on the exact filename meant a refusal
    survived the conversion for ever, unreachable even by ``--force``
    (fifth re-audit).
    """
    directory = str(Path(rel_path).parent)
    candidates = {rel_path}
    if Path(rel_path).name in TRANSCRIPT_FORMS:
        candidates |= {f"{directory}/{form}" for form in TRANSCRIPT_FORMS}
    removed = [key for key in candidates if key in refusals]
    for key in removed:
        del refusals[key]
    return removed


def load_refusals(refusal_file: Path | None = None) -> dict[str, float]:
    """Return ``{archive_path: source_mtime}`` for files PostgreSQL refused.

    Second re-audit, finding M3: a refused file was skipped and then
    re-parsed and re-refused on every single run, for ever, reporting
    nothing. The incremental skip is keyed on ``source_mtime`` in
    ``session_chunks``, and a refused file writes no row there, so it never
    became "already indexed". Remembering the refusal alongside the mtime
    means the file is skipped until it actually changes — at which point it
    is worth another try.

    A missing or unreadable file reads as "nothing refused": the memory is
    an optimisation and a report, never a gate on correctness.

    ``refusal_file`` defaults to :data:`REFUSAL_FILE` resolved *at call
    time*, not bound into the signature: a default argument is evaluated
    once at import, so monkeypatching the module constant would not reach
    it — and a test would then write the operator's real refusal memory.
    """
    refusal_file = REFUSAL_FILE if refusal_file is None else refusal_file
    try:
        data = json.loads(refusal_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): float(value)
        for key, value in data.items()
        if isinstance(value, (int, float))
    }


def _recorded_archive_root(
    gate_path: Path, logger: logging.Logger,
) -> tuple[str | None, bool]:
    """
    Read the archive root the refusal memory was built against.

    Returns ``(root, known)``. ``known`` is ``False`` when the gate could
    not be read at all. The lock lives in ``~/.cache``, so an unwritable
    directory or a stuck lock file raised ``OSError``/``TimeoutError``
    from a call sitting outside ``main``'s handler, and any run at all
    became an exit 1 with no gate written — a lock problem rewriting the
    verdict on the indexing (eighth re-audit, finding M2). A gate is a
    diagnostic surface; failing to read one is never a reason to change
    what the run reports.

    An unreadable gate makes the refusal memory READ-ONLY for the run
    rather than assumed to be ours: the memory's keys are relative paths,
    and acting on one built for a different archive root is the failure
    the recorded root exists to prevent.
    """
    try:
        with gate_lock(gate_path):
            return read_state(gate_path, logger).archive_root, True
    except (OSError, TimeoutError) as exc:
        logger.warning(
            "Could not read the gate state under its lock (%s: %s) — "
            "leaving the refusal memory untouched for this run.",
            type(exc).__name__, exc,
        )
        return None, False


def save_refusals(
    refusals: dict[str, float],
    refusal_file: Path | None = None,
) -> bool:
    """Persist the refusal memory atomically. Returns True on success.

    Written via temp file + rename so a kill mid-write cannot leave a
    half-parsed file that reads as "nothing refused" and sends the next run
    back into the same wall. ``refusal_file`` resolves at call time — see
    :func:`load_refusals`.
    """
    refusal_file = REFUSAL_FILE if refusal_file is None else refusal_file
    try:
        refusal_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = refusal_file.with_name(f"{refusal_file.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(refusals, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, refusal_file)
    except OSError as exc:
        logger.warning("Could not save the refusal memory: %s", exc)
        return False
    return True


# --- Indexing ---------------------------------------------------------------

def index_archive(archive_root: Path, project: str | None,
                  include_subagents: bool, force: bool,
                  refusal_file: Path | None = None
                  ) -> IndexResult:
    """Index matching transcripts.

    Returns an :class:`IndexResult`. Aborts raise :class:`IndexerAbort`,
    whose ``exit_code`` the caller returns.

    A stopped database used to produce a raw traceback here — ``connect``
    was unguarded and ``main`` caught only ``ImportError`` — while every
    other script in the Postgres tranche degrades with "PostgreSQL may be
    stopped: this is not critical" (audit round two, finding P5 / lens
    A-M3). The archive tree is canonical; the index is rebuildable.
    """
    import psycopg2
    from psycopg2.extras import execute_values

    # Resolved at call time so the module constant stays monkeypatchable.
    refusal_file = REFUSAL_FILE if refusal_file is None else refusal_file

    # An archive root that exists but holds nothing is an unmounted disk
    # or the wrong path, not an empty history. Running on it would make
    # the prune loop below declare every remembered archive gone, wiping
    # the memory and lowering the gate on the strength of a missing mount
    # (fourth re-audit, finding C3). Refuse, and touch nothing.
    root_is_populated = (
        next(archive_root.rglob("session.meta.json"), None) is not None
    )
    if not root_is_populated:
        logger.error(
            "Archive root %s contains no session.meta.json at all — that "
            "is a missing mount or the wrong path, not an empty archive. "
            "Refusing to run: a scan of an empty root would look like "
            "every archive having been deleted.", archive_root)
        raise IndexerAbort(
            2, f"archive root {archive_root} is empty — refusing to run",
        )

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.error("Cannot connect to PostgreSQL: %s", exc)
        logger.error(
            "PostgreSQL may be stopped — this is not critical. The archive "
            "tree remains canonical; re-run this script once it is back to "
            "rebuild the index."
        )
        raise IndexerAbort(3, f"cannot connect to PostgreSQL: {exc}") from exc

    # Refuse to write against a schema shape this script was not written
    # for: session_chunks' columns and its (archive_path, turn_idx) unique
    # key are exactly what the INSERT below depends on.
    try:
        assert_schema_version(conn)
    except SchemaVersionError as exc:
        logger.error("Schema-version mismatch: %s", exc)
        conn.close()
        raise IndexerAbort(2, f"schema-version mismatch: {exc}") from exc

    conn.autocommit = False
    files_indexed = files_skipped = total_chunks = 0
    refused_now = refused_remembered = 0
    nuls_stripped = 0
    # Files PostgreSQL refused on a previous run, with the mtime they had
    # then. The memory is always LOADED — it has to be, or --force could
    # not clear the entries it retries, and stale entries could never be
    # pruned — but it is only CONSULTED when we are not forcing. --force
    # is the operator saying "try them again anyway", and a run that
    # retries a file must forget the old verdict whatever the outcome
    # (finding C2).
    known_refusals = load_refusals(refusal_file)
    consult_memory = not force
    refusals_changed = False
    # The memory's keys are paths RELATIVE to an archive root, so they say
    # nothing about which root they came from: the same key names a
    # different file under a copy, a restore, or another machine's mirror.
    # Against a root the memory was not built for, it is read-only — no
    # consulting, no forgetting, no recording, no pruning (sixth
    # re-audit, low).
    # Read under the gate lock, like every other consumer of this state
    # (seventh re-audit, low), and compare RESOLVED paths so a symlink or
    # a trailing slash cannot make our own root look foreign.
    recorded_root, root_known = _recorded_archive_root(GATE_FILE, logger)
    resolved_root = str(Path(archive_root).resolve())
    memory_is_ours = root_known and (
        recorded_root is None
        or str(Path(recorded_root).resolve()) == resolved_root
    )
    if not root_known:
        consult_memory = False
    elif not memory_is_ours:
        logger.warning(
            "The refusal memory was built against %s and this run scans "
            "%s — leaving it untouched.", recorded_root, archive_root)
        consult_memory = False
    try:
        with conn.cursor() as cur:
            for transcript_path, proj_name, session_dir in discover(
                    archive_root, project, include_subagents):
                rel_path = str(transcript_path.relative_to(archive_root))
                mtime = transcript_path.stat().st_mtime

                # Refused on an earlier run and unchanged since: skip it
                # rather than re-parsing and re-refusing every run. Counted
                # separately from a refusal that happened THIS run, because
                # only the latter should fail the run (finding C2).
                if (consult_memory
                        and known_refusals.get(rel_path) == mtime):
                    files_skipped += 1
                    refused_remembered += 1
                    continue
                # Forget the old verdict for this transcript in EITHER
                # form before we find out. A refusal recorded against
                # session.jsonl was stranded for ever once the archiver
                # gzipped it: the key never matched again, the entry was
                # never revisited, and the only documented remedy
                # (--force) could not reach it (fifth re-audit).
                if memory_is_ours and _forget_transcript(
                        known_refusals, rel_path):
                    refusals_changed = True

                # Incremental skip: already indexed at this mtime?
                if not force:
                    cur.execute(
                        "SELECT 1 FROM session_chunks WHERE archive_path = %s "
                        "AND source_mtime = %s LIMIT 1", (rel_path, mtime))
                    if cur.fetchone():
                        files_skipped += 1
                        continue

                sess_id = session_id_for(session_dir)
                # Per-file NUL accounting (low finding L3): the counts
                # sanitise_nuls returns were discarded, so text was being
                # silently altered on the way into the index.
                file_stats: dict[str, int] = {"nuls_removed": 0}
                rows = [
                    (sess_id, proj_name, session_dir.name, rel_path, turn_idx,
                     role, text, len(text), mtime)
                    for turn_idx, role, text in iter_turns(
                        transcript_path, stats=file_stats)
                ]
                if file_stats["nuls_removed"]:
                    nuls_stripped += file_stats["nuls_removed"]
                    logger.warning(
                        "  stripped %d NUL character(s) from %s before "
                        "indexing — PostgreSQL cannot store U+0000 in text",
                        file_stats["nuls_removed"], rel_path)

                # Replace this file's rows transactionally (no stale turns).
                # Known limitation: a file with ZERO extractable prose turns
                # records no row, so its mtime is never stored and it is
                # re-parsed every run. Dormant for main transcripts (every real
                # session has ≥1 user turn); only bites pure-tool subagent files
                # (--include-subagents) or corrupt archives, at a cost of one
                # cheap re-parse per run. Accepted rather than adding a separate
                # indexed-files table for a negligible, self-limiting cost.
                #
                # A file PostgreSQL refuses is skipped, not fatal (re-audit
                # finding M4). Aborting on the first poison file blocked
                # every later file *forever*: the skip is keyed on
                # source_mtime, so an unindexed file is retried on the next
                # run, discovery is sorted, and the run dies at the same
                # file every time before reaching the rest.
                try:
                    cur.execute(
                        "DELETE FROM session_chunks WHERE archive_path = %s",
                        (rel_path,))
                    if rows:
                        execute_values(
                            cur,
                            "INSERT INTO session_chunks (session_id, project, archive_dir, "
                            "archive_path, turn_idx, role, text, char_len, source_mtime) "
                            "VALUES %s ON CONFLICT (archive_path, turn_idx) DO UPDATE SET "
                            "text = EXCLUDED.text, role = EXCLUDED.role, "
                            "char_len = EXCLUDED.char_len, source_mtime = EXCLUDED.source_mtime, "
                            "indexed_at = NOW()",
                            rows)
                    conn.commit()
                except (psycopg2.Error, ValueError, TypeError) as exc:
                    conn.rollback()
                    verdict = classify_pg_error(exc, psycopg2)
                    if verdict in (OUTAGE, ENVIRONMENT):
                        # Not about this file: the database went away, or
                        # is not in the state this script expects. Stop —
                        # ploughing on would report every remaining file
                        # as poison. Same exit codes as the connect-time
                        # path rather than a traceback (finding M4).
                        logger.error(
                            "Aborting the index run — %s (SQLSTATE %s): %s",
                            type(exc).__name__,
                            getattr(exc, "pgcode", None) or "none",
                            str(exc).strip())
                        raise IndexerAbort(
                            3 if verdict == OUTAGE else 4,
                            f"{type(exc).__name__}: {str(exc).strip()}",
                        ) from exc
                    refused_now += 1
                    if memory_is_ours:
                        known_refusals[rel_path] = mtime
                        refusals_changed = True
                    logger.error(
                        "  REFUSED %-22s %-45s — %s. Skipping this file; it "
                        "is remembered and not retried until the file "
                        "changes (or --force).",
                        proj_name, session_dir.name[:45], str(exc).strip())
                    continue
                files_indexed += 1
                total_chunks += len(rows)
                logger.info("  indexed %-22s %-45s %4d turns",
                            proj_name, session_dir.name[:45], len(rows))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        # Prune entries whose archive has since been moved or deleted, so
        # the memory cannot accumulate for ever and report unindexed files
        # that no longer exist (finding C2). Three guards now: only on a
        # populated root (an unmounted disk must not read as "everything
        # was deleted"); only when the session DIRECTORY is verifiably
        # absent (a transcript swapped between .gz and raw still has its
        # directory); and only when this run's root is the one the memory
        # was built against — running against a *different* populated
        # root would find none of its directories and forget the lot
        # (sixth re-audit, low).
        for stale in [] if not memory_is_ours else [
            key for key in known_refusals
            if not (archive_root / key).parent.exists()
        ]:
            del known_refusals[stale]
            refusals_changed = True
            logger.info(
                "  forgetting the refusal for %s — the archive is gone",
                stale)
        if refusals_changed:
            save_refusals(known_refusals, refusal_file)
    if nuls_stripped:
        logger.warning(
            "Stripped %d NUL character(s) in total across this run.",
            nuls_stripped)
    if refused_now:
        logger.error(
            "%d file(s) were REFUSED by PostgreSQL this run and are NOT "
            "searchable. Recorded in %s; they are retried when the file "
            "changes, or with --force. The archive tree is canonical "
            "either way.",
            refused_now, refusal_file)
    if refused_remembered:
        # Once per run, at WARNING, and it does not fail the run: this is
        # a standing condition, not something that happened just now.
        logger.warning(
            "%d file(s) remain unindexed from an earlier run and were "
            "skipped. They are retried when the file changes, or with "
            "--force. Listed in %s.",
            refused_remembered, refusal_file)
    return IndexResult(
        files_indexed, files_skipped, total_chunks,
        refused_now, refused_remembered,
    )


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Populate the session_chunks index.")
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT),
                        help="Archive root (default: ~/cc-archives).")
    parser.add_argument("--project", default=None,
                        help="Index only this project sub-directory (e.g. inscriptions).")
    parser.add_argument("--include-subagents", action="store_true",
                        help="Also index subagent transcripts (default: main only).")
    parser.add_argument("--force", action="store_true",
                        help="Reindex even if the file mtime is unchanged.")
    args = parser.parse_args(argv)

    # Be a polite background citizen on the shared desktop (CPU only; this is
    # local parse work, no API). The shell never needs to wrap this.
    try:
        os.nice(10)
    except (OSError, PermissionError):
        pass

    archive_root = Path(args.archive_root).expanduser()
    if not archive_root.is_dir():
        # A degraded return rather than parser.error (sixth re-audit,
        # finding C3): argparse exits 2 straight past every gate, so a
        # mistyped or unmounted root said nothing at session start while
        # the index quietly stopped growing.
        logger.error("Archive root not found: %s", archive_root)
        apply_gate(
            GateEvent(
                outcome=CYCLE_DEGRADED,
                degraded_detail=(
                    f"[{SCRIPT_NAME}] the archive root {archive_root} does "
                    f"not exist. No transcript can be indexed — check the "
                    f"mount or the --archive-root path."
                ),
                script=SCRIPT_NAME,
            ),
            gate_path=GATE_FILE,
            logger=logger,
        )
        return 2

    logger.info("Indexing session content from %s%s ...", archive_root,
                f" (project={args.project})" if args.project else "")
    try:
        result = index_archive(
            archive_root, args.project, args.include_subagents, args.force)
    except ImportError:
        logger.error("psycopg2 is required; install it in the venv.")
        apply_gate(
            GateEvent(
                outcome=CYCLE_DEGRADED,
                fault_detail=(
                    f"[{SCRIPT_NAME}] exit 2 — psycopg2 is not installed, "
                    f"so no transcript can be indexed. Run: "
                    f"~/personal-assistant/venv/bin/pip install "
                    f"psycopg2-binary"
                ),
                script=SCRIPT_NAME,
            ),
            gate_path=GATE_FILE,
            logger=logger,
        )
        return 2
    except IndexerAbort as exc:
        # Reported in full by index_archive; the code carries the reason.
        logger.error("Index run aborted (exit %d): %s", exc.exit_code, exc)
        # EVERY non-zero exit raises a problem (finding C3), and an
        # outage goes through the streak rather than raising a fault that
        # a later all-indexed run could never lower (finding M2).
        if exc.exit_code == 3:
            event = GateEvent(
                outcome=CYCLE_OUTAGE,
                connected=False,
                script=SCRIPT_NAME,
            )
        elif exc.exit_code == 2 and "is empty" in str(exc):
            event = GateEvent(
                outcome=CYCLE_DEGRADED,
                degraded_detail=(
                    f"[{SCRIPT_NAME}] {exc} No transcript can be "
                    f"indexed — check the mount or the --archive-root "
                    f"path."
                ),
                script=SCRIPT_NAME,
            )
        else:
            event = GateEvent(
                outcome=CYCLE_DEGRADED,
                connected=True,
                fault_detail=(
                    f"[{SCRIPT_NAME}] exit {exc.exit_code} — the "
                    f"transcript indexer stopped: {exc} Newly archived "
                    f"sessions are not searchable until this is fixed."
                ),
                script=SCRIPT_NAME,
            )
        apply_gate(event, gate_path=GATE_FILE, logger=logger)
        return exc.exit_code
    logger.info(
        "Done: %d file(s) indexed, %d skipped (unchanged), %d chunks, "
        "%d refused this run, %d still refused from before.",
        result.files_indexed, result.files_skipped, result.chunks,
        result.refused_now, result.refused_remembered)

    # The gate is about the whole memory, not this run's slice: a run
    # scoped to one project has seen only part of the picture.
    outstanding = len(load_refusals())
    _apply_indexer_gate(
        outstanding, result.files_indexed, archive_root, logger=logger,
    )

    if result.refused_now:
        # Non-zero ONLY for a refusal that happened this run (finding C2).
        # A standing refusal from weeks ago is reported through the gate
        # and the WARNING above; failing every run over it would turn the
        # exit code into noise.
        logger.error(
            "%d transcript(s) were refused this run and are not "
            "searchable. See the REFUSED lines above and %s.",
            result.refused_now, REFUSAL_FILE)
        return 5
    return 0


def _apply_indexer_gate(
    outstanding: int,
    indexed: int,
    archive_root: Path,
    logger: logging.Logger,
) -> None:
    """
    Report this script's problems through the shared state machine.

    ``outstanding`` counts the WHOLE refusal memory, not this run's scope
    (fourth re-audit, finding C3), which is what makes the scope
    irrelevant here: if the memory is empty then no transcript is
    missing from the index, whoever observed it. An earlier scope flag
    inverted that and stopped a ``--project`` run from lowering the
    problem it had just resolved (sixth re-audit, finding M7).
    """
    apply_gate(
        GateEvent(
            # Indexing nothing is idle, not completed: it is no evidence
            # that a standing fault is resolved.
            outcome=CYCLE_COMPLETED if indexed else CYCLE_IDLE,
            connected=True,
            processed=indexed,
            refusals=outstanding,
            archive_root=str(Path(archive_root).resolve()),
            script=SCRIPT_NAME,
        ),
        gate_path=GATE_FILE,
        logger=logger,
    )

if __name__ == "__main__":
    raise SystemExit(main())
