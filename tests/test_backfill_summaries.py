"""
Tests for ``scripts/backfill-summaries.py`` — the memory summary backfill.

Two defect classes are pinned here, both found in the 2026-09-08 audit:

* **AR4** — the script made live API calls with no cost gate at all. Every
  sibling gates its spend; this one went from argument parsing straight to
  ``client.messages.create``.
* **AR5** — the apply path wrote a summary for ANY id the model's reply
  contained, so a hallucinated or out-of-batch id silently overwrote an
  unrelated memory's summary with a summary of something else.

Plus the write-path invariants (ART10): the temp-and-rename staging and the
post-write line-count check, neither of which any test held down.

No network client is ever constructed: ``anthropic.Anthropic`` is replaced
with a stub that records its calls, and the tests assert on whether it was
called. Every memory record here is invented.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def _load_backfill():
    """Import the hyphenated script by path."""
    spec = importlib.util.spec_from_file_location(
        "backfill_summaries_under_test", str(SCRIPTS_DIR / "backfill-summaries.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backfill = _load_backfill()

LOGGER = logging.getLogger("backfill-summaries-test")


def _memory(mem_id: str, content: str, *, summary: str | None = None) -> dict:
    """One invented memory record in the canonical JSONL shape."""
    record = {
        "id": mem_id,
        "session_id": "0f0f0f0f-1111-4111-8111-0f0f0f0f0f0f",
        "project": "lantern-survey",
        "source": "extraction",
        "category": "decision",
        "content": content,
        "confidence": "medium",
        "research_tags": ["survey-design"],
        "source_context": "Planning the terrace grid",
        "created_at": "2026-03-02T09:30:00+00:00",
    }
    if summary is not None:
        record["summary"] = summary
    return record


class StubAnthropic:
    """A stand-in for ``anthropic.Anthropic`` that records every call."""

    instances: list["StubAnthropic"] = []
    calls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        StubAnthropic.instances.append(self)
        self.messages = types.SimpleNamespace(
            create=self._create,
            batches=types.SimpleNamespace(create=self._batch_create),
        )

    def _create(self, **kwargs):
        StubAnthropic.calls.append("messages.create")
        block = types.SimpleNamespace(text="[]")
        return types.SimpleNamespace(content=[block])

    def _batch_create(self, **kwargs):
        StubAnthropic.calls.append("batches.create")
        return types.SimpleNamespace(
            id="msgbatch_stub",
            processing_status="in_progress",
            request_counts=types.SimpleNamespace(processing=1),
        )


@pytest.fixture()
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A synthetic canonical, a stubbed API client, and no real logging."""
    StubAnthropic.instances = []
    StubAnthropic.calls = []

    memories = tmp_path / "memories.jsonl"
    memories.write_text(
        "".join(
            json.dumps(_memory(f"2026-03-02-{n:06d}", f"Decision number {n}."))
            + "\n"
            for n in range(3)
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(backfill, "MEMORIES_FILE", memories)
    monkeypatch.setattr(backfill, "BATCH_STATE_FILE", tmp_path / "batch.json")
    monkeypatch.setattr(backfill, "setup_logging", lambda: LOGGER)
    monkeypatch.setattr(backfill, "load_env", lambda: None)
    monkeypatch.setattr(
        backfill, "ensure_safe_to_rewrite", lambda reason: None
    )
    monkeypatch.setattr(backfill, "release_lock", lambda: None)

    stub_module = types.ModuleType("anthropic")
    stub_module.Anthropic = StubAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", stub_module)
    return types.SimpleNamespace(memories=memories, tmp_path=tmp_path)


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    """Invoke the script's ``main()`` with the given command line."""
    monkeypatch.setattr(sys, "argv", ["backfill-summaries.py", *argv])
    backfill.main()


class TestApiCostGate:
    """AR4 — no live call without a stated cost and an explicit yes."""

    def test_no_confirmation_means_no_api_call_and_a_non_zero_exit(
        self, harness, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Stdin closed: an unanswered gate is a refusal, never a default yes."""
        def closed_stdin(prompt: str = "") -> str:
            raise EOFError("stdin is closed")

        monkeypatch.setattr("builtins.input", closed_stdin)

        with pytest.raises(SystemExit) as exit_info:
            _run_main(monkeypatch)

        assert exit_info.value.code != 0
        assert StubAnthropic.calls == [], (
            "the API was called without the operator confirming the spend"
        )
        gate = capsys.readouterr().out
        assert "API COST GATE" in gate
        assert backfill.HAIKU_MODEL in gate
        assert "Est. cost" in gate

    def test_declining_the_gate_makes_no_api_call(
        self, harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typed 'n' is a refusal too."""
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        with pytest.raises(SystemExit) as exit_info:
            _run_main(monkeypatch)

        assert exit_info.value.code != 0
        assert StubAnthropic.calls == []

    def test_yes_flag_proceeds_to_the_api(
        self, harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``--yes`` is the scripted path, and it does reach the client."""
        def refuse(prompt: str = "") -> str:
            raise AssertionError("--yes must not prompt")

        monkeypatch.setattr("builtins.input", refuse)

        _run_main(monkeypatch, "--yes")

        assert StubAnthropic.calls == ["messages.create"]

    def test_batch_mode_is_gated_too(
        self, harness, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The batch submit path spends money as surely as the sync path."""
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        with pytest.raises(SystemExit):
            _run_main(monkeypatch, "--batch-api")

        assert StubAnthropic.calls == []
        assert "Batch API" in capsys.readouterr().out

    def test_dry_run_still_makes_no_call_and_does_not_prompt(
        self, harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--dry-run returns before the gate; it was never a spending path."""
        def refuse(prompt: str = "") -> str:
            raise AssertionError("--dry-run must not reach the gate")

        monkeypatch.setattr("builtins.input", refuse)

        _run_main(monkeypatch, "--dry-run")

        assert StubAnthropic.calls == []

    def test_the_estimate_counts_every_request(self, harness) -> None:
        """The call count in the gate is the call count that will be made."""
        to_backfill = [
            (i, _memory(f"2026-03-02-{i:06d}", "x" * 400)) for i in range(7)
        ]
        requests, input_tokens, output_tokens = backfill.estimate_prompt_tokens(
            to_backfill, batch_size=3
        )
        assert requests == 3
        assert input_tokens > 0
        assert output_tokens == 7 * backfill.EST_OUTPUT_TOKENS_PER_MEMORY
