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

        def fake_apply(batch_id, out_dir, *, force=False):
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


class TestBlinding:
    """Every arm gets a letter, and the permutation is stable but not binary."""

    FIVE_ARMS = ["alpha", "beta", "delta", "epsilon", "gamma"]

    def test_every_arm_is_labelled(self):
        """The finding: zip against ("A","B","C","D") dropped a fifth arm."""
        labelled = bom.blind_order("session-1", self.FIVE_ARMS)
        assert len(labelled) == len(self.FIVE_ARMS)
        assert sorted(arm for _letter, arm in labelled) == sorted(self.FIVE_ARMS)
        assert [letter for letter, _arm in labelled] == list("ABCDE")

    def test_permutation_is_stable_for_a_session(self):
        assert bom.blind_order("session-1", self.FIVE_ARMS) == bom.blind_order(
            "session-1", list(reversed(self.FIVE_ARMS))
        )

    def test_more_than_two_permutations_occur(self):
        """A reverse-only flip yields exactly two orderings; this must not."""
        seen = {
            tuple(arm for _letter, arm in bom.blind_order(f"session-{n}", self.FIVE_ARMS))
            for n in range(40)
        }
        assert len(seen) > 2

    def test_too_many_arms_is_an_error_not_a_truncation(self):
        with pytest.raises(ValueError):
            bom.blind_order("session-1", [f"arm{n}" for n in range(30)])

    def test_rubric_lists_five_arms_and_the_key_is_byte_identical(self, tmp_path):
        """Five arms in, five blocks out, and a re-run reproduces the key."""
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, RUBRIC_TEMPLATE, providers=tuple(self.FIVE_ARMS)
        )
        bom.build_rubric(manifest, prompt, out_dir, rubric_in, rubric_out)
        first_key = rubric_out.with_name(rubric_out.stem + ".blind-key.json")
        key_bytes = first_key.read_bytes()
        rubric_text = rubric_out.read_text(encoding="utf-8")
        for letter in "ABCDE":
            assert f"#### Model {letter} output" in rubric_text
        # The mapping must not leak into the body a scorer reads.
        for arm in self.FIVE_ARMS:
            assert arm not in rubric_text

        second_out = tmp_path / "rubric-out-again.md"
        bom.build_rubric(manifest, prompt, out_dir, rubric_in, second_out)
        second_key = second_out.with_name(second_out.stem + ".blind-key.json")
        assert second_key.read_bytes() == key_bytes
        mapping = json.loads(key_bytes)["mapping"]
        assert sorted(next(iter(mapping.values())).values()) == sorted(self.FIVE_ARMS)

    def test_error_responses_are_redacted_in_the_rubric_and_kept_in_the_key(
        self, tmp_path
    ):
        """A vendor error string unblinds an arm; the fact of failure does not."""
        manifest, prompt, out_dir, rubric_in, rubric_out = _rubric_inputs(
            tmp_path, RUBRIC_TEMPLATE, providers=("alpha", "beta")
        )
        session_id = "bbbb2222-3333-4444"
        (out_dir / "beta" / f"{session_id}.json").write_text(
            json.dumps(fx.RESPONSE_ERROR, indent=2) + "\n", encoding="utf-8"
        )
        bom.build_rubric(manifest, prompt, out_dir, rubric_in, rubric_out)
        rubric_text = rubric_out.read_text(encoding="utf-8")
        assert "200000 maximum" not in rubric_text
        assert "redacted to preserve blinding" in rubric_text
        key = json.loads(
            rubric_out.with_name(rubric_out.stem + ".blind-key.json").read_text()
        )
        assert key["redacted_errors"]["beta"][session_id] == fx.RESPONSE_ERROR["error"]


class TestPricingConstants:
    """Stale prices produce estimates the operator approves in good faith."""

    def test_sonnet_uses_post_introductory_list_prices(self):
        """The intro 2.00/10.00 rate expired on 2026-08-31."""
        assert bom.SONNET_INPUT_PRICE_PER_MTOK == 3.00
        assert bom.SONNET_OUTPUT_PRICE_PER_MTOK == 15.00

    def test_provider_specs_track_the_constants(self):
        model, in_rate, out_rate = bom.PROVIDER_SPECS["sonnet-5"]
        assert model == bom.SONNET_MODEL
        assert in_rate == bom.SONNET_INPUT_PRICE_PER_MTOK
        assert out_rate == bom.SONNET_OUTPUT_PRICE_PER_MTOK

    def test_estimate_uses_the_provider_rate(self, tmp_path):
        manifest = _one_session_manifest(tmp_path)
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        cost = bom.estimate_cost_usd(requests, provider="sonnet-5")
        assert cost["input_rate_per_mtok"] == 3.00
        assert cost["output_rate_per_mtok"] == 15.00


class TestResponsePersistence:
    """Each response cost money: never lose one, never half-write one."""

    def test_complete_response_survives_a_later_failure(self, tmp_path):
        """The finding: a re-run overwrote a good response with an error."""
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)
        session_id = "cccc3333-4444-5555"
        target = out_dir / f"{session_id}.json"
        target.write_text(fx.RESPONSE_BARE + "\n", encoding="utf-8")
        bom.record_failure(
            out_dir, session_id, {"error": "503 Service Unavailable"}, tag="gemini"
        )
        assert json.loads(target.read_text())["title"] == fx.RESPONSE_OBJECT["title"]

    def test_error_is_recorded_when_no_response_exists(self, tmp_path):
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)
        bom.record_failure(out_dir, "dddd", {"error": "boom"}, tag="gemini")
        assert json.loads((out_dir / "dddd.json").read_text()) == {"error": "boom"}

    def test_an_error_record_is_replaceable(self, tmp_path):
        """An earlier failure is not a result; a retry may overwrite it."""
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)
        (out_dir / "eeee.json").write_text('{"error": "first"}\n', encoding="utf-8")
        bom.record_failure(out_dir, "eeee", {"error": "second"}, tag="gemini")
        assert json.loads((out_dir / "eeee.json").read_text()) == {"error": "second"}

    def test_atomic_write_leaves_the_old_file_on_a_crash(self, tmp_path):
        """Crash injection: serialisation fails part-way through the write."""
        target = tmp_path / "response.json"
        target.write_text('{"keep": true}\n', encoding="utf-8")

        class Unserialisable:
            """json.dumps refuses this."""

        with pytest.raises(TypeError):
            bom.write_json_atomic(target, {"boom": Unserialisable()})
        assert json.loads(target.read_text()) == {"keep": True}
        assert list(tmp_path.iterdir()) == [target]

    def test_rerun_skips_completed_sessions(self, tmp_path):
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)
        manifest = _one_session_manifest(tmp_path, "ffff4444-5555-6666")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        (out_dir / "ffff4444-5555-6666.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )
        assert bom.pending_requests(
            requests, out_dir, force=False, tag="gemini"
        ) == []
        assert len(bom.pending_requests(
            requests, out_dir, force=True, tag="gemini"
        )) == 1

    def test_rerun_does_not_skip_an_error_record(self, tmp_path):
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)
        manifest = _one_session_manifest(tmp_path, "9999aaaa-bbbb-cccc")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        (out_dir / "9999aaaa-bbbb-cccc.json").write_text(
            json.dumps(fx.RESPONSE_ERROR), encoding="utf-8"
        )
        assert len(bom.pending_requests(
            requests, out_dir, force=False, tag="gemini"
        )) == 1

    def test_live_rerun_makes_no_call_for_a_completed_session(
        self, tmp_path, monkeypatch, gemini_boundary
    ):
        """End to end: a resumed run must not pay for the same session twice."""
        manifest = _one_session_manifest(tmp_path, "aaaa1111-2222-3333")
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        (out_dir / "gemini").mkdir(parents=True)
        (out_dir / "gemini" / "aaaa1111-2222-3333.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )
        assert bom.main(_live_argv(manifest, prompt, out_dir, "--yes")) == 0
        assert not any(call["event"] == "generate" for call in gemini_boundary)

    def test_usage_log_is_merged_not_replaced(self, tmp_path):
        """A resumed run must not discard the earlier run's billed figures."""
        out_dir = tmp_path / "luna"
        out_dir.mkdir(parents=True)
        bom.merge_usage_log(
            out_dir, [{"session_id": "one", "input_tokens": 10}]
        )
        bom.merge_usage_log(
            out_dir, [{"session_id": "two", "input_tokens": 20}]
        )
        rows = json.loads((out_dir / "_usage.json").read_text())
        assert {row["session_id"] for row in rows} == {"one", "two"}

    def test_usage_log_updates_a_repeated_session(self, tmp_path):
        out_dir = tmp_path / "luna"
        out_dir.mkdir(parents=True)
        bom.merge_usage_log(out_dir, [{"session_id": "one", "input_tokens": 10}])
        bom.merge_usage_log(out_dir, [{"session_id": "one", "input_tokens": 99}])
        rows = json.loads((out_dir / "_usage.json").read_text())
        assert rows == [{"session_id": "one", "input_tokens": 99}]
