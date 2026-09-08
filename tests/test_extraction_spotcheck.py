"""
Tests for ``scripts/extraction-prompt-spotcheck.py`` and the distiller shim.

Two untested surfaces, both cheap to get wrong (lens B finding 11):

* the spot-check harness is dry-run by default and its ``--run`` flag is the
  only thing between an operator and a live Haiku bill. Nothing pinned that.
* ``scripts/extract-transcript-text.py`` is a pure re-export shim over
  ``cc_session_toolkit.transcript_text``. Two other scripts importlib-load it
  by path and reach for names on it; a rename in the toolkit would break them
  at runtime, in a batch job, hours in.

Also pinned here: AR24, the spot-check's transcript glob, which used to
include flat ``agent-*.jsonl`` subagent transcripts that every other script
in the pipeline excludes.

The harness pins itself to ``~/personal-assistant``; the tests therefore
point HOME at a directory whose ``personal-assistant`` is a symlink to this
checkout. Nothing is written through it — the harness only reads the hook.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture()
def spotcheck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import the harness with HOME pointing at a link to this checkout."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "personal-assistant").symlink_to(REPO_ROOT)
    monkeypatch.setenv("HOME", str(home))

    spec = importlib.util.spec_from_file_location(
        "spotcheck_under_test",
        str(SCRIPTS_DIR / "extraction-prompt-spotcheck.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTranscriptSelection:
    """AR24 — sample sessions, not subagent transcripts."""

    def test_flat_agent_transcripts_are_excluded(
        self, spotcheck, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sampling one measured the prompt against a subagent's words."""
        root = tmp_path / "projects" / "-home-tester-Workshop"
        root.mkdir(parents=True)
        session = root / "eeeeeeee-5555-4555-8555-eeeeeeeeeeee.jsonl"
        session.write_text("{}\n", encoding="utf-8")
        (root / "agent-3d9c.jsonl").write_text("{}\n", encoding="utf-8")

        monkeypatch.setattr(
            spotcheck, "TRANSCRIPT_ROOT", tmp_path / "projects"
        )
        sampled: list[Path] = []

        def record(path, cursor):
            sampled.append(Path(path))
            return [], None, 0

        monkeypatch.setattr(spotcheck.hook, "parse_transcript", record)

        spotcheck.sample_windows(n_windows=1, max_transcripts=10)

        assert sampled == [session], (
            f"a subagent transcript was sampled: {sampled}"
        )


class TestDryRunMakesNoApiCalls:
    """--run is the only thing between an operator and a live bill."""

    def test_the_default_run_never_reaches_the_model(
        self, spotcheck, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = tmp_path / "projects" / "-home-tester-Workshop"
        root.mkdir(parents=True)
        (root / "eeeeeeee-5555-4555-8555-eeeeeeeeeeee.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            spotcheck, "TRANSCRIPT_ROOT", tmp_path / "projects"
        )
        monkeypatch.setattr(
            spotcheck, "sample_windows",
            lambda n_windows, max_transcripts: [{
                "transcript": "eeeeeeee",
                "idx": 0,
                "messages": [{"role": "user", "content": "A question."}],
                "conv_chars": 11,
            }],
        )

        def must_not_run(*args, **kwargs):
            raise AssertionError("the dry run reached extract_memories")

        monkeypatch.setattr(spotcheck.hook, "extract_memories", must_not_run)
        monkeypatch.setattr(
            spotcheck.hook, "load_env",
            lambda: (_ for _ in ()).throw(
                AssertionError("the dry run loaded API credentials")
            ),
        )
        monkeypatch.setattr(sys, "argv", ["extraction-prompt-spotcheck.py"])

        assert spotcheck.main() == 0

        report = capsys.readouterr().out
        assert "DRY-RUN" in report
        assert "EST COST" in report
        assert "no API calls made" in report


class TestDistillerShimNamesResolve:
    """Two scripts importlib-load this shim and reach for these names."""

    def test_every_re_exported_name_is_present(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "extract_transcript_text_under_test",
            str(SCRIPTS_DIR / "extract-transcript-text.py"),
        )
        assert spec is not None and spec.loader is not None
        shim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shim)

        for name in (
            "CLAUDE_MD_BLOCK_RE",
            "HOOK_OUTPUT_RE",
            "SKIP_RECORD_TYPES",
            "SYSTEM_REMINDER_RE",
            "TOOL_RESULT_MAX_CHARS",
            "TOOL_USE_INPUT_MAX_CHARS",
            "estimate_tokens",
            "extract_transcript_text",
        ):
            assert hasattr(shim, name), (
                f"{name} no longer resolves through the shim; the scripts "
                "that importlib-load it break at runtime, not at import"
            )

    def test_the_distiller_runs_on_a_synthetic_transcript(
        self, tmp_path: Path
    ) -> None:
        """The counter bulk-archive builds on top of this must work."""
        spec = importlib.util.spec_from_file_location(
            "extract_transcript_text_under_test",
            str(SCRIPTS_DIR / "extract-transcript-text.py"),
        )
        assert spec is not None and spec.loader is not None
        shim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shim)

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from archive_fixtures import substantive_records, write_transcript

        path = write_transcript(
            tmp_path / "session.jsonl", substantive_records("s1")
        )
        text = shim.extract_transcript_text(str(path))

        assert "survey grid" in text.lower()
        assert shim.estimate_tokens(text) > 0
