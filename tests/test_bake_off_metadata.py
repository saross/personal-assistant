"""
Tests for ``scripts/bake-off-metadata.py`` — the provider bake-off runner.

The runner is the only script in this tranche that can spend money, so the
tests are arranged around two questions: does it refuse when refusing is the
safe answer, and does it call a provider only after the operator has seen the
model, the mode, the request count, and the cost?

Nothing here reaches a network: an autouse fixture refuses every socket
operation, and each provider boundary (``anthropic.Anthropic``,
``google.genai.Client``, ``urllib.request.urlopen``, ``resolve_openai_key``)
is replaced with a recording stub that the tests then assert on.

Every fixture is synthetic — see ``tests/fixtures``.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SCRIPT = PROJECT_ROOT / "scripts" / "bake-off-metadata.py"

sys.path.insert(0, str(TESTS_DIR))
from fixtures import bake_off as fx  # noqa: E402

_spec = importlib.util.spec_from_file_location("bake_off_metadata", SCRIPT)
assert _spec is not None and _spec.loader is not None
bom = importlib.util.module_from_spec(_spec)
# Registered before execution: the module defines a ``@dataclass``, and
# ``dataclasses`` resolves the defining module out of ``sys.modules``.
sys.modules[_spec.name] = bom
_spec.loader.exec_module(bom)


# ---------------------------------------------------------------------------
# Hermeticity
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def refuse_sockets(monkeypatch):
    """Fail loudly if any test in this module opens a socket."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a bake-off test opened a network socket. Provider adapters must "
            "be stubbed at the boundary, never exercised against a live API."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def no_operator_env(monkeypatch, tmp_path):
    """Point ``ENV_FILE`` at an empty tmp path so no real ``.env`` is read."""
    monkeypatch.setattr(bom, "ENV_FILE", tmp_path / "absent.env")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _one_session_manifest(tmp_path: Path, session_id: str = "aaaa1111-2222-3333") -> Path:
    """Write a one-row manifest whose transcript is synthetic and real-shaped."""
    transcript = fx.write_session_transcript(
        tmp_path / "transcripts" / f"{session_id}.jsonl", n_records=20
    )
    return fx.write_manifest(
        tmp_path / "manifest.json", [fx.manifest_row(session_id, transcript)]
    )


def _prompt_file(tmp_path: Path) -> Path:
    """Write an invented system prompt file."""
    path = tmp_path / "prompt.md"
    path.write_text(
        "You summarise an archaeological work session. Return one JSON object.\n",
        encoding="utf-8",
    )
    return path


RUBRIC_TEMPLATE = (
    "# Review rubric\n\n"
    "| # | session | project | bin | tokens |\n"
    "|---|---------|---------|-----|--------|\n"
    "| 1 | <!--SESSION-ID-1--> | <!--PROJECT-1--> | <!--BIN-1--> "
    "| <!--TOKENS-1--> |\n\n"
    "<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->\n"
)


def _rubric_inputs(tmp_path: Path, template_text: str, *, providers=("alpha", "beta")):
    """Build a manifest, provider response dirs, and a rubric template.

    Returns ``(manifest_path, prompt_path, out_dir, rubric_in, rubric_out)``.
    """
    session_id = "bbbb2222-3333-4444"
    manifest_path = _one_session_manifest(tmp_path, session_id)
    out_dir = tmp_path / "out"
    for provider in providers:
        provider_dir = out_dir / provider
        provider_dir.mkdir(parents=True)
        (provider_dir / f"{session_id}.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )
    rubric_in = tmp_path / "rubric-template.md"
    rubric_in.write_bytes(template_text.encode("utf-8"))
    return (
        manifest_path,
        _prompt_file(tmp_path),
        out_dir,
        rubric_in,
        tmp_path / "rubric-out.md",
    )


# ---------------------------------------------------------------------------
# --build-rubric: the populate step must refuse rather than mislabel
# ---------------------------------------------------------------------------


class TestRubricTemplateValidation:
    """``--build-rubric`` refuses any template it cannot populate safely."""

    def test_blank_line_between_markers_still_populates(self, tmp_path):
        """A blank line between the markers is whitespace, not content."""
        template = RUBRIC_TEMPLATE.replace(
            "<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->",
            "<!--BEGIN-SESSIONS-->\n\n<!--END-SESSIONS-->",
        )
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, template
        )
        bom.build_rubric(manifest, prompt, out_dir, rubric_in, rubric_out)
        written = rubric_out.read_text(encoding="utf-8")
        assert "#### Model A output" in written
        assert "### Session 1:" in written

    def test_crlf_template_populates(self, tmp_path):
        """A CRLF template is a Windows-edited template, not a broken one.

        ``Path.read_text`` translates CRLF to LF on the way in, so the ``\\r``
        never reaches the matcher; the blank line inserted here is what makes
        the case bite, and pinning both together documents the assumption.
        """
        template = RUBRIC_TEMPLATE.replace(
            "<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->",
            "<!--BEGIN-SESSIONS-->\n\n<!--END-SESSIONS-->",
        ).replace("\n", "\r\n")
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, template
        )
        bom.build_rubric(manifest, prompt, out_dir, rubric_in, rubric_out)
        assert "#### Model A output" in rubric_out.read_text(encoding="utf-8")

    def test_already_populated_template_is_refused(self, tmp_path):
        """The finding: a populated rubric must never be silently re-keyed."""
        template = RUBRIC_TEMPLATE.replace(
            "<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->",
            "<!--BEGIN-SESSIONS-->\n### Session 1: `old-arms`\n"
            "<!--END-SESSIONS-->",
        )
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, template
        )
        with pytest.raises(bom.RubricTemplateError):
            bom.build_rubric(manifest, prompt, out_dir, rubric_in, rubric_out)

    def test_missing_marker_is_refused(self, tmp_path):
        """No marker pair at all is a malformed template, not an empty one."""
        template = RUBRIC_TEMPLATE.replace(
            "<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->\n", ""
        )
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, template
        )
        with pytest.raises(bom.RubricTemplateError):
            bom.build_rubric(manifest, prompt, out_dir, rubric_in, rubric_out)

    def test_duplicated_markers_are_refused(self, tmp_path):
        """Two marker pairs: which one carries the sessions is ambiguous."""
        template = RUBRIC_TEMPLATE + "\n<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->\n"
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, template
        )
        with pytest.raises(bom.RubricTemplateError):
            bom.build_rubric(manifest, prompt, out_dir, rubric_in, rubric_out)


class TestRubricRefusalWritesNothing:
    """A refusal must leave the filesystem exactly as it found it."""

    def test_entry_point_exits_2_and_writes_neither_rubric_nor_key(self, tmp_path):
        """The blind key is the dangerous artefact: it must not appear."""
        template = RUBRIC_TEMPLATE.replace(
            "<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->",
            "<!--BEGIN-SESSIONS-->\n### Session 1: `old-arms`\n"
            "<!--END-SESSIONS-->",
        )
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, template
        )
        code = bom.main([
            "--build-rubric",
            "--manifest", str(manifest),
            "--prompt", str(prompt),
            "--out-dir", str(out_dir),
            "--rubric-in", str(rubric_in),
            "--rubric-out", str(rubric_out),
        ])
        assert code == 2
        assert not rubric_out.exists()
        key_path = rubric_out.with_name(rubric_out.stem + ".blind-key.json")
        assert not key_path.exists()

    def test_successful_build_writes_both_artefacts(self, tmp_path):
        """The positive case, so the refusal above is not vacuous."""
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, RUBRIC_TEMPLATE
        )
        code = bom.main([
            "--build-rubric",
            "--manifest", str(manifest),
            "--prompt", str(prompt),
            "--out-dir", str(out_dir),
            "--rubric-in", str(rubric_in),
            "--rubric-out", str(rubric_out),
        ])
        assert code == 0
        assert rubric_out.exists()
        assert rubric_out.with_name(rubric_out.stem + ".blind-key.json").exists()

    def test_build_rubric_without_paths_exits_2(self, tmp_path):
        """``--build-rubric`` needs both rubric paths before it does anything."""
        manifest = _one_session_manifest(tmp_path)
        code = bom.main([
            "--build-rubric",
            "--manifest", str(manifest),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(tmp_path / "out"),
        ])
        assert code == 2
        assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# Provider boundary stubs
# ---------------------------------------------------------------------------


class RecordingGeminiClient:
    """Stand-in for ``google.genai.Client`` that records every call."""

    #: Shared across instances so a test can assert "never constructed".
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        RecordingGeminiClient.calls.append({"event": "client"})
        self.models = self

    def generate_content(self, *, model, contents, config):
        """Return a canned response object with a ``.text`` attribute."""
        RecordingGeminiClient.calls.append({"event": "generate", "model": model})
        return type("FakeResponse", (), {"text": fx.RESPONSE_BARE})()


@pytest.fixture
def gemini_boundary(monkeypatch):
    """Install a fake ``google.genai`` and return its call log."""
    RecordingGeminiClient.calls = []
    fake_genai = type(sys)("google.genai")
    fake_genai.Client = RecordingGeminiClient
    fake_google = type(sys)("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    return RecordingGeminiClient.calls


def _live_argv(manifest: Path, prompt: Path, out_dir: Path, *extra: str) -> list[str]:
    """Argument vector for a live (non-dry-run) gemini invocation."""
    return [
        "--provider", "gemini",
        "--manifest", str(manifest),
        "--prompt", str(prompt),
        "--out-dir", str(out_dir),
        *extra,
    ]


# ---------------------------------------------------------------------------
# The API Call Review Gate
# ---------------------------------------------------------------------------


class TestApiCallReviewGate:
    """No billed call without the four figures and an explicit approval."""

    def test_summary_names_model_mode_count_and_cost(self, tmp_path):
        manifest = _one_session_manifest(tmp_path)
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        lines = "\n".join(bom.gate_summary_lines(requests, "gemini"))
        assert bom.GEMINI_MODEL in lines
        assert "real-time" in lines
        assert "requests:       1" in lines
        assert "estimated cost: $" in lines

    def test_batch_provider_is_labelled_batch(self, tmp_path):
        manifest = _one_session_manifest(tmp_path)
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        lines = "\n".join(bom.gate_summary_lines(requests, "haiku"))
        assert bom.HAIKU_MODEL in lines
        assert "mode:           batch" in lines

    def test_declining_makes_no_call_and_exits_0(
        self, tmp_path, monkeypatch, capsys, gemini_boundary
    ):
        """The negative: a 'no' must reach the provider adapter never."""
        manifest = _one_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        monkeypatch.setattr("builtins.input", lambda _prompt="": "no")
        code = bom.main(_live_argv(manifest, prompt, out_dir))
        assert code == 0
        assert gemini_boundary == []
        printed = capsys.readouterr().out
        assert bom.GEMINI_MODEL in printed  # the figures were shown first
        assert not list((out_dir / "gemini").glob("*.json"))

    def test_closed_stdin_refuses_cleanly(
        self, tmp_path, monkeypatch, capsys, gemini_boundary
    ):
        """A closed stdin is 'nobody is here', not an EOFError traceback."""
        manifest = _one_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)

        def raise_eof(_prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        code = bom.main(_live_argv(manifest, prompt, tmp_path / "out"))
        assert code == 0
        assert gemini_boundary == []
        assert "stdin is closed" in capsys.readouterr().out

    def test_yes_flag_prints_the_figures_and_proceeds(
        self, tmp_path, monkeypatch, capsys, gemini_boundary
    ):
        """--yes is not a way to skip the disclosure, only the prompt."""
        manifest = _one_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"

        def refuse_input(_prompt=""):
            raise AssertionError("--yes must not reach input()")

        monkeypatch.setattr("builtins.input", refuse_input)
        code = bom.main(_live_argv(manifest, prompt, out_dir, "--yes"))
        assert code == 0
        printed = capsys.readouterr().out
        assert bom.GEMINI_MODEL in printed
        assert "estimated cost: $" in printed
        assert any(call["event"] == "generate" for call in gemini_boundary)
        assert list((out_dir / "gemini").glob("*.json"))

    def test_typed_yes_proceeds(
        self, tmp_path, monkeypatch, gemini_boundary
    ):
        manifest = _one_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        monkeypatch.setattr("builtins.input", lambda _prompt="": " YES \n")
        assert bom.main(_live_argv(manifest, prompt, tmp_path / "out")) == 0
        assert any(call["event"] == "generate" for call in gemini_boundary)

    def test_dry_run_never_reaches_the_gate(
        self, tmp_path, monkeypatch, gemini_boundary
    ):
        manifest = _one_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"

        def refuse_input(_prompt=""):
            raise AssertionError("--dry-run must not prompt")

        monkeypatch.setattr("builtins.input", refuse_input)
        code = bom.main(_live_argv(manifest, prompt, out_dir, "--dry-run"))
        assert code == 0
        assert gemini_boundary == []
        assert (out_dir / "gemini" / "dry-run-cost.json").exists()


class TestUngatedRetrieval:
    """``--haiku-apply`` is free, so it does not prompt — but it does speak."""

    def test_haiku_apply_announces_what_it_retrieves(
        self, tmp_path, monkeypatch, capsys
    ):
        state_dir = tmp_path / "out" / "haiku"
        state_dir.mkdir(parents=True)
        (state_dir / "batch-state.json").write_text(
            json.dumps({"batch_id": "batch_invented", "custom_id_to_session": {}}),
            encoding="utf-8",
        )
        retrieved: list[str] = []

        def fake_apply(batch_id, out_dir):
            retrieved.append(batch_id)

        monkeypatch.setattr(bom, "haiku_apply", fake_apply)

        def refuse_input(_prompt=""):
            raise AssertionError("retrieval is free; it must not prompt")

        monkeypatch.setattr("builtins.input", refuse_input)
        code = bom.main([
            "--provider", "haiku",
            "--haiku-apply", "batch_invented",
            "--manifest", str(_one_session_manifest(tmp_path)),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(tmp_path / "out"),
        ])
        assert code == 0
        assert retrieved == ["batch_invented"]
        printed = capsys.readouterr().out
        assert "batch_invented" in printed
        assert "ungated" in printed

    def test_haiku_apply_with_wrong_provider_exits_2(self, tmp_path):
        code = bom.main([
            "--provider", "gemini",
            "--haiku-apply", "batch_invented",
            "--manifest", str(_one_session_manifest(tmp_path)),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(tmp_path / "out"),
        ])
        assert code == 2
        assert not (tmp_path / "out").exists()


class TestCustomIdUniqueness:
    """A batch custom_id must identify exactly one session."""

    def test_ids_sharing_an_eight_char_prefix_stay_distinct(self):
        """The finding: sess-{id[:8]} collapsed sub-agent stems together."""
        first = "subagent-explore-2026-01-05T09-15-00-alpha"
        second = "subagent-explore-2026-01-05T09-15-00-beta"
        assert first[:8] == second[:8]
        assert bom.build_custom_id(first) != bom.build_custom_id(second)

    def test_custom_ids_satisfy_the_api_constraints(self):
        ids = [
            "aaaa1111-2222-3333-4444-555566667777",
            "subagent-explore-2026-01-05T09-15-00-alpha",  # colons, too long
            "short",
        ]
        for session_id in ids:
            custom_id = bom.build_custom_id(session_id)
            assert 1 <= len(custom_id) <= bom.CUSTOM_ID_MAX_CHARS
            assert bom.CUSTOM_ID_SAFE_RE.match(custom_id)

    def test_a_manifest_of_similar_ids_round_trips(self, tmp_path):
        """assemble_requests + the batch-state map must not lose a session."""
        session_ids = [
            "subagent-explore-2026-01-05T09-15-00-alpha",
            "subagent-explore-2026-01-05T09-15-00-beta",
        ]
        rows = []
        for session_id in session_ids:
            transcript = fx.write_session_transcript(
                tmp_path / "transcripts" / f"{session_id}.jsonl", n_records=8
            )
            rows.append(fx.manifest_row(session_id, transcript))
        manifest = fx.write_manifest(tmp_path / "manifest.json", rows)
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        mapping = {r.custom_id: r.session_id for r in requests}
        assert len(mapping) == len(session_ids)
        assert sorted(mapping.values()) == sorted(session_ids)
