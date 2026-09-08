"""
Tests for ``scripts/_log_dir.py`` — a readable failure, not a traceback.

``logs/`` is a symlink into the private ``data`` submodule. In a fresh
clone, a linked worktree, or a machine where the submodule has not been
initialised, the link dangles — and ``mkdir(parents=True, exist_ok=True)``
raises ``FileExistsError`` on a dangling symlink, because the link exists
and its target does not.

Every long-running script in the pipeline calls ``setup_logging()`` as its
first act, so this arrived as an unhandled traceback from inside a logging
helper: a diagnosis three frames from the actual problem, which is one
command long to fix (audit 2026-09-08, finding AR20).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from _log_dir import ensure_log_dir  # noqa: E402


class TestEnsureLogDir:
    """The three states a log directory can be in."""

    def test_an_ordinary_directory_is_created(self, tmp_path: Path) -> None:
        target = tmp_path / "logs"

        assert ensure_log_dir(target) == target
        assert target.is_dir()

    def test_an_existing_directory_is_accepted(self, tmp_path: Path) -> None:
        target = tmp_path / "logs"
        target.mkdir()

        assert ensure_log_dir(target) == target

    def test_a_live_symlink_is_accepted(self, tmp_path: Path) -> None:
        """The normal checkout: logs -> data/logs, and data/logs exists."""
        real = tmp_path / "data" / "logs"
        real.mkdir(parents=True)
        link = tmp_path / "logs"
        link.symlink_to("data/logs")

        assert ensure_log_dir(link) == link

    def test_a_dangling_symlink_exits_with_the_remedy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The uninitialised submodule: a message, not a FileExistsError."""
        link = tmp_path / "logs"
        link.symlink_to("data/logs")

        with pytest.raises(SystemExit) as exit_info:
            ensure_log_dir(link)

        assert exit_info.value.code == 2
        message = capsys.readouterr().err
        assert "git submodule update --init data" in message, (
            "the failure must name the one command that fixes it"
        )
        assert "data/logs" in message
