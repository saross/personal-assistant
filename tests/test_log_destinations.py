"""
Where the instrumentation logs write — and, under pytest, do not (audit R17).

``surfacing_log.py`` learned this in audit S22: a log path derived from
``__file__`` points at the operator's own checkout no matter where the
suite pins ``HOME``, and runs through the ``logs`` symlink into the private
``data`` submodule. A test exercising a logging path therefore appended
live-looking rows to the operator's real instrumentation — rows that later
get read as evidence.

``fetch-memories.py``, ``log-recall.py``, ``log-confab-flag.py``, and
``digest-preview.py`` all had the same shape and none of the guard. This
file pins the shared contract for all of them:

1. the environment override wins;
2. under pytest an unpinned call resolves to ``None`` and writes NOTHING —
   not even the parent directory;
3. otherwise the shipped path, derived from ``__file__``.

It also pins the reader/writer agreement the earned-utility aggregator
depends on (lens B, RT10).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

fetch_memories = __import__("fetch-memories")
log_recall = __import__("log-recall")
log_confab_flag = __import__("log-confab-flag")
surfacing_log = importlib.import_module("surfacing_log")
surfacing_stats = importlib.import_module("surfacing_stats")


def _load_digest_preview():
    """Import the hyphenated preview harness by path."""
    spec = importlib.util.spec_from_file_location(
        "digest_preview", SCRIPTS_DIR / "digest-preview.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


digest_preview = _load_digest_preview()

#: (module, env var, expected shipped filename) for every writer here.
WRITERS = [
    pytest.param(fetch_memories, "PA_FETCH_LOG", "fetch-memories.log",
                 id="fetch-memories"),
    pytest.param(log_recall, "PA_FETCH_LOG", "fetch-memories.log",
                 id="log-recall"),
    pytest.param(log_confab_flag, "PA_CONFAB_LOG", "confab-flags.log",
                 id="log-confab-flag"),
    pytest.param(surfacing_log, "PA_SURFACED_LOG", "surfaced.log",
                 id="surfacing-log"),
    pytest.param(digest_preview, "PA_DIGEST_PREVIEW_LOG", "digest-preview.log",
                 id="digest-preview"),
]


@pytest.mark.parametrize("module,env,filename", WRITERS)
def test_environment_override_wins(
    monkeypatch: pytest.MonkeyPatch, module, env: str, filename: str,
    tmp_path: Path,
) -> None:
    """An operator (or a test) can pin the destination without touching callers."""
    pinned = tmp_path / "pinned.log"
    monkeypatch.setenv(env, str(pinned))
    assert module.default_log_path() == pinned


@pytest.mark.parametrize("module,env,filename", WRITERS)
def test_unpinned_under_pytest_has_no_destination(
    monkeypatch: pytest.MonkeyPatch, module, env: str, filename: str,
) -> None:
    """Kills: binding the shipped path as a default argument.

    Rule 2 of the contract. Without it, running the suite writes rows into
    the operator's live logs.
    """
    monkeypatch.delenv(env, raising=False)
    assert module.default_log_path() is None


@pytest.mark.parametrize("module,env,filename", WRITERS)
def test_shipped_path_is_derived_from_the_script_not_home(
    module, env: str, filename: str,
) -> None:
    """The production destination is the checkout's own logs directory."""
    assert module.SHIPPED_LOG_PATH.name == filename
    assert module.SHIPPED_LOG_PATH.is_absolute()


class TestNothingIsWrittenWhenUnpinned:
    """An unpinned call writes no file AND creates no directory."""

    def test_fetch_memories_invocation_log(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("PA_FETCH_LOG", raising=False)
        monkeypatch.setattr(
            fetch_memories, "SHIPPED_LOG_PATH", tmp_path / "logs" / "f.log",
        )
        args = Namespace(tags=None, query="x", semantic=None, category=None,
                         memory_id=None, limit=10)
        fetch_memories._log_invocation(args, [])
        assert not (tmp_path / "logs").exists()

    def test_log_recall(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("PA_FETCH_LOG", raising=False)
        monkeypatch.setattr(
            log_recall, "SHIPPED_LOG_PATH", tmp_path / "logs" / "f.log",
        )
        assert log_recall.log_recall("query", results=1) is False
        assert not (tmp_path / "logs").exists()

    def test_log_confab_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("PA_CONFAB_LOG", raising=False)
        monkeypatch.setattr(
            log_confab_flag, "SHIPPED_LOG_PATH", tmp_path / "logs" / "c.log",
        )
        assert log_confab_flag.log_confab_flag(
            "lit-scout-verifier", checked=1, flagged=0, confab=0,
        ) is False
        assert not (tmp_path / "logs").exists()


class TestExplicitPathStillWorks:
    """The guard must not break a test that pins a path deliberately."""

    def test_fetch_memories_writes_when_pinned(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "fetch-memories.log"
        args = Namespace(tags=["ethics"], query=None, semantic=None,
                         category="decision", memory_id=None, limit=5)
        fetch_memories._log_invocation(args, [{"id": "a"}], log_path=target)
        line = target.read_text(encoding="utf-8")
        assert "selectors=tag:ethics;category:decision" in line
        assert "results=1" in line

    def test_log_recall_writes_when_pinned(self, tmp_path: Path) -> None:
        target = tmp_path / "fetch-memories.log"
        assert log_recall.log_recall("query", results=2, log_path=target)
        assert "source=recall" in target.read_text(encoding="utf-8")


class TestReaderWriterAgreement:
    """The aggregator must read the file the writer writes (lens B, RT10)."""

    def test_surfacing_stats_default_matches_the_writer(self) -> None:
        """Kills: pointing either side at a differently-named file.

        A silent divergence here reports zero earned utility for a corpus
        that is in fact being retrieved constantly.
        """
        assert surfacing_stats.DEFAULT_LOG_PATH == surfacing_log.SHIPPED_LOG_PATH

    def test_recall_and_fetch_share_one_retrieval_log(self) -> None:
        """/recall and the autonomous depth-fetch append to the same file.

        tier-2-retrieval.md's ``source=`` discriminator only works if they
        do; two files would leave the review parser reading half the data.
        """
        assert log_recall.SHIPPED_LOG_PATH == fetch_memories.SHIPPED_LOG_PATH


class TestDigestPreviewLog:
    """The dry-run harness must be distinguishable from a real session."""

    def test_preview_log_is_not_the_live_digest_log(self) -> None:
        """Kills: pointing the harness back at data/logs/digest.log."""
        assert digest_preview.SHIPPED_LOG_PATH.name == "digest-preview.log"

    def test_preview_lines_carry_the_marker(self) -> None:
        """Kills: dropping ``preview=true`` from the written line."""
        import digest

        result = digest.DigestResult(
            text="", entries=[], rendered_bytes=0, byte_budget=1200,
            verified_available=0, used_fallback=False, window_days=7,
            counter={"new": 0, "updated": 0, "forgotten": 0, "categories": {}},
        )
        from datetime import datetime, timezone

        line = digest_preview.preview_log_line(
            result, now=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )
        assert line.endswith("\tpreview=true")


class TestInvocationLogFieldsCannotForgeColumns:
    """Audit L2 — --tag and --category are free-form CLI values."""

    def test_tab_bearing_category_is_collapsed(self, tmp_path: Path) -> None:
        """Kills: interpolating args.category raw into the record.

        The forged text lands inside the selectors field instead of
        creating columns the review parser would read as real fields.
        """
        target = tmp_path / "fetch-memories.log"
        args = Namespace(
            tags=None, query=None, semantic=None,
            category="decision\tsource=fetch\tresults=999",
            memory_id=None, limit=10,
        )
        fetch_memories._log_invocation(args, [], log_path=target)
        line = target.read_text(encoding="utf-8").rstrip("\n")
        assert len(line.split("\t")) == 4
        assert "selectors=category:decision source=fetch results=999" in line

    def test_tab_bearing_tag_is_collapsed(self, tmp_path: Path) -> None:
        """--tag is repeatable, so each value is cleaned individually."""
        target = tmp_path / "fetch-memories.log"
        args = Namespace(
            tags=["survey", "grid\tspacing"], query=None, semantic=None,
            category=None, memory_id=None, limit=10,
        )
        fetch_memories._log_invocation(args, [], log_path=target)
        line = target.read_text(encoding="utf-8").rstrip("\n")
        assert len(line.split("\t")) == 4
        assert "selectors=tag:survey,grid spacing" in line

    def test_newline_in_a_selector_cannot_inject_a_record(
        self, tmp_path: Path,
    ) -> None:
        """A second line would be a wholly fabricated retrieval event."""
        target = tmp_path / "fetch-memories.log"
        args = Namespace(
            tags=None, query=None, semantic=None,
            category="decision\n2026-01-01T00:00:00+00:00\tselectors=none",
            memory_id=None, limit=10,
        )
        fetch_memories._log_invocation(args, [], log_path=target)
        assert target.read_text(encoding="utf-8").count("\n") == 1

    def test_ordinary_values_are_unchanged(self, tmp_path: Path) -> None:
        """The cleaning must not mangle the normal case."""
        target = tmp_path / "fetch-memories.log"
        args = Namespace(
            tags=["survey"], query=None, semantic=None, category="decision",
            memory_id=None, limit=10,
        )
        fetch_memories._log_invocation(args, [{"id": "a"}], log_path=target)
        line = target.read_text(encoding="utf-8").rstrip("\n")
        assert "selectors=tag:survey;category:decision" in line
        assert "limit=10" in line
        assert "results=1" in line
