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

import hashlib
import importlib.util
import json
import shlex
import socket
import sys
from datetime import datetime
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

    @pytest.mark.parametrize("supplied", ["neither", "rubric_in", "rubric_out"])
    def test_build_rubric_without_paths_exits_2(self, tmp_path, supplied):
        """``--build-rubric`` needs BOTH rubric paths before it does anything.

        Parametrised over one-of-two because the fence is an ``and``: with
        only one path supplied an ``or`` there passes the check and
        build_rubric is handed a None, crashing on an attribute of it
        instead of exiting 2.
        """
        argv = [
            "--build-rubric",
            "--manifest", str(_one_session_manifest(tmp_path)),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(tmp_path / "out"),
        ]
        if supplied == "rubric_in":
            argv += ["--rubric-in", str(tmp_path / "template.md")]
        elif supplied == "rubric_out":
            argv += ["--rubric-out", str(tmp_path / "populated.md")]
        assert bom.main(argv) == 2
        assert not (tmp_path / "out").exists()
        assert not (tmp_path / "populated.md").exists()


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

    def test_declining_makes_no_call_and_exits_3(
        self, tmp_path, monkeypatch, capsys, gemini_boundary
    ):
        """The negative: a 'no' must reach the provider adapter never.

        The exit code is 3, not 0: a wrapper that reads 0 as success would
        record a refused run as a completed bake-off.
        """
        manifest = _one_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        monkeypatch.setattr("builtins.input", lambda _prompt="": "no")
        code = bom.main(_live_argv(manifest, prompt, out_dir))
        assert code == bom.EXIT_REFUSED_AT_GATE == 3
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
        assert code == bom.EXIT_REFUSED_AT_GATE == 3
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

    def test_hashed_custom_id_keeps_the_whole_digest_prefix(self):
        """Pin the digest length: a short prefix reintroduces collisions."""
        long_id = "subagent-explore-" + "x" * 80
        custom_id = bom.build_custom_id(long_id)
        assert custom_id.startswith("sess-")
        digest = custom_id[len("sess-"):]
        assert len(digest) == 40
        assert digest == hashlib.sha256(long_id.encode("utf-8")).hexdigest()[:40]
        assert len(custom_id) <= bom.CUSTOM_ID_MAX_CHARS

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


class TestEmptyManifest:
    """An empty manifest is an upstream mistake, not a zero-cost run."""

    def test_dry_run_on_empty_manifest_exits_cleanly(self, tmp_path, capsys):
        """The finding: requests[0] raised IndexError after writing a file."""
        manifest = fx.write_manifest(tmp_path / "manifest.json", [])
        out_dir = tmp_path / "out"
        code = bom.main([
            "--provider", "gemini",
            "--manifest", str(manifest),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(out_dir),
            "--dry-run",
        ])
        assert code == 0
        assert "no sessions" in capsys.readouterr().out
        assert not out_dir.exists()

    def test_live_run_on_empty_manifest_calls_nothing(
        self, tmp_path, monkeypatch, gemini_boundary
    ):
        manifest = fx.write_manifest(tmp_path / "manifest.json", [])

        def refuse_input(_prompt=""):
            raise AssertionError("an empty manifest must not reach the gate")

        monkeypatch.setattr("builtins.input", refuse_input)
        code = bom.main([
            "--provider", "gemini",
            "--manifest", str(manifest),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(tmp_path / "out"),
        ])
        assert code == 0
        assert gemini_boundary == []


class TestOpenAiBoundary:
    """The Luna/Terra arm speaks HTTP directly, so the boundary is urlopen."""

    @pytest.fixture
    def urlopen_stub(self, monkeypatch):
        """Replace ``urlopen`` with a recorder returning a canned payload."""
        import urllib.request

        calls: list[dict] = []

        class FakeResponse:
            def __init__(self, payload):
                self._payload = json.dumps(payload).encode("utf-8")

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        def fake_urlopen(request, timeout=None):
            body = json.loads(request.data.decode("utf-8"))
            calls.append(body)
            return FakeResponse({
                "output_text": fx.RESPONSE_BARE,
                "usage": {"input_tokens": 1234, "output_tokens": 56},
                "service_tier": "default",
            })

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(bom, "resolve_openai_key", lambda _scope: "invented-key")
        return calls

    def test_service_tier_actually_used_is_recorded(self, tmp_path, urlopen_stub):
        """A silent Flex-to-default fallback changes the price; record it."""
        manifest = _one_session_manifest(tmp_path, "7777bbbb-cccc-dddd")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        out_dir = tmp_path / "luna"
        out_dir.mkdir()
        bom.luna_run(requests, out_dir, "system prompt")
        rows = json.loads((out_dir / "_usage.json").read_text())
        assert rows[0]["service_tier"] == "default"
        assert rows[0]["input_tokens"] == 1234

    def test_the_request_never_leaves_the_stub(self, tmp_path, urlopen_stub):
        manifest = _one_session_manifest(tmp_path, "8888bbbb-cccc-dddd")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        out_dir = tmp_path / "luna"
        out_dir.mkdir()
        bom.luna_run(requests, out_dir, "system prompt")
        assert len(urlopen_stub) == 1
        assert urlopen_stub[0]["model"] == bom.LUNA_MODEL
        assert urlopen_stub[0]["store"] is False


class TestInterpreterHint:
    """The dependency lives only in the repository virtual environment."""

    def test_extractor_import_failure_names_the_venv(self, tmp_path, monkeypatch):
        """A bare "No module named cc_session_toolkit" helps nobody."""
        real_exec = importlib.util.module_from_spec

        def boom(spec):
            module = real_exec(spec)

            class Loader:
                def exec_module(self, _module):
                    raise ImportError("No module named 'cc_session_toolkit'")

            spec.loader = Loader()
            return module

        monkeypatch.setattr(importlib.util, "module_from_spec", boom)
        with pytest.raises(RuntimeError, match="venv/bin/python3"):
            bom._load_extractor()


class TestParseResponseJson:
    """Models wrap JSON in fences intermittently; prose is a real failure."""

    def test_bare_json_round_trips(self):
        assert bom.parse_response_json(fx.RESPONSE_BARE) == fx.RESPONSE_OBJECT

    def test_fenced_json_round_trips(self):
        assert bom.parse_response_json(fx.RESPONSE_FENCED) == fx.RESPONSE_OBJECT

    def test_leading_and_trailing_whitespace_is_tolerated(self):
        padded = f"\n\n  {fx.RESPONSE_BARE}  \n"
        assert bom.parse_response_json(padded) == fx.RESPONSE_OBJECT

    def test_fence_with_trailing_prose_is_a_value_error(self):
        """Only a single enclosing fence is stripped; prose after it is not."""
        with pytest.raises(ValueError):
            bom.parse_response_json(fx.RESPONSE_FENCED_WITH_PROSE)

    def test_prose_only_is_a_value_error(self):
        with pytest.raises(ValueError):
            bom.parse_response_json(fx.RESPONSE_PROSE_ONLY)


class TestCostEstimate:
    """The system prompt is billed on every call and must be counted once."""

    def test_system_prompt_tokens_appear_once_per_request(self, tmp_path):
        rows = []
        for index in range(3):
            session_id = f"cost{index}-1111-2222"
            transcript = fx.write_session_transcript(
                tmp_path / "transcripts" / f"{session_id}.jsonl", n_records=6
            )
            rows.append(fx.manifest_row(session_id, transcript))
        manifest = fx.write_manifest(tmp_path / "manifest.json", rows)
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        cost = bom.estimate_cost_usd(requests, provider="gemini")
        user_tokens = sum(max(1, len(r.user_message) // 4) for r in requests)
        assert cost["input_tokens"] == (
            user_tokens + 3 * bom.SYSTEM_PROMPT_TOKENS_APPROX
        )

    def test_per_session_rows_match_the_aggregate(self, tmp_path):
        manifest = _one_session_manifest(tmp_path, "cost-single-1111")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        cost = bom.estimate_cost_usd(requests, provider="gemini")
        rows = cost["per_session_cost_usd"]
        assert sum(row["input_tokens"] for row in rows) == cost["input_tokens"]
        assert rows[0]["input_tokens"] > bom.SYSTEM_PROMPT_TOKENS_APPROX

    def test_unknown_provider_is_an_error(self, tmp_path):
        manifest = _one_session_manifest(tmp_path, "cost-unknown-1111")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        with pytest.raises(ValueError):
            bom.estimate_cost_usd(requests, provider="not-a-provider")


class TestDryRunFootprint:
    """A dry run writes one file and constructs nothing."""

    def test_only_the_cost_file_is_written(self, tmp_path, gemini_boundary):
        manifest = _one_session_manifest(tmp_path, "dry-run-1111-2222")
        out_dir = tmp_path / "out"
        assert bom.main(_live_argv(
            manifest, _prompt_file(tmp_path), out_dir, "--dry-run"
        )) == 0
        written = sorted(p.relative_to(out_dir) for p in out_dir.rglob("*") if p.is_file())
        assert written == [Path("gemini") / "dry-run-cost.json"]
        assert gemini_boundary == []


class TestHaikuApplyBoundary:
    """Retrieval maps custom ids back to sessions; an unknown id writes nothing."""

    @pytest.fixture
    def anthropic_stub(self, monkeypatch):
        """Install a fake ``anthropic`` module returning canned batch results."""
        results: list = []

        class FakeBatches:
            def retrieve(self, _batch_id):
                return type("Batch", (), {"processing_status": "ended"})()

            def results(self, _batch_id):
                return list(results)

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = type("Messages", (), {"batches": FakeBatches()})()

        fake_module = type(sys)("anthropic")
        fake_module.Anthropic = FakeAnthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)
        return results

    @staticmethod
    def _result(custom_id: str, text: str):
        """Build one batch result object shaped like the SDK's."""
        block = type("Block", (), {"type": "text", "text": text})()
        message = type("Message", (), {"content": [block]})()
        inner = type("Inner", (), {"type": "succeeded", "message": message})()
        return type("Result", (), {"custom_id": custom_id, "result": inner})()

    def test_unknown_custom_id_writes_nothing(self, tmp_path, anthropic_stub, capsys):
        """The negative: an id absent from batch-state.json is not a session."""
        out_dir = tmp_path / "haiku"
        out_dir.mkdir(parents=True)
        (out_dir / "batch-state.json").write_text(
            json.dumps({
                "batch_id": "batch_invented",
                "custom_id_to_session": {"sess-known": "known-session"},
            }),
            encoding="utf-8",
        )
        anthropic_stub.append(self._result("sess-stranger", fx.RESPONSE_BARE))
        bom.haiku_apply("batch_invented", out_dir)
        written = sorted(p.name for p in out_dir.iterdir())
        assert written == ["batch-state.json"]
        printed = capsys.readouterr().out
        assert "no session mapped to custom_id sess-stranger" in printed
        assert "ALREADY PAID FOR" in printed

    def test_known_custom_id_writes_its_session(self, tmp_path, anthropic_stub):
        out_dir = tmp_path / "haiku"
        out_dir.mkdir(parents=True)
        (out_dir / "batch-state.json").write_text(
            json.dumps({
                "batch_id": "batch_invented",
                "custom_id_to_session": {"sess-known": "known-session"},
            }),
            encoding="utf-8",
        )
        anthropic_stub.append(self._result("sess-known", fx.RESPONSE_BARE))
        bom.haiku_apply("batch_invented", out_dir)
        written = json.loads((out_dir / "known-session.json").read_text())
        assert written == fx.RESPONSE_OBJECT
        assert (out_dir / "known-session.raw.txt").exists()


class TestGateQuotesWhatWillBeSent:
    """A resumed run must be priced on the calls it is about to make."""

    def _two_session_manifest(self, tmp_path):
        rows = []
        for session_id in ("resume-aaaa-1111", "resume-bbbb-2222"):
            transcript = fx.write_session_transcript(
                tmp_path / "transcripts" / f"{session_id}.jsonl", n_records=10
            )
            rows.append(fx.manifest_row(session_id, transcript))
        return fx.write_manifest(tmp_path / "manifest.json", rows)

    def test_count_excludes_sessions_already_answered(
        self, tmp_path, capsys, gemini_boundary
    ):
        manifest = self._two_session_manifest(tmp_path)
        out_dir = tmp_path / "out"
        (out_dir / "gemini").mkdir(parents=True)
        (out_dir / "gemini" / "resume-aaaa-1111.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )
        assert bom.main(_live_argv(
            manifest, _prompt_file(tmp_path), out_dir, "--yes"
        )) == 0
        printed = capsys.readouterr().out
        assert "requests:       1" in printed
        assert len([c for c in gemini_boundary if c["event"] == "generate"]) == 1

    def test_all_answered_exits_before_the_gate(
        self, tmp_path, monkeypatch, capsys, gemini_boundary
    ):
        manifest = self._two_session_manifest(tmp_path)
        out_dir = tmp_path / "out"
        (out_dir / "gemini").mkdir(parents=True)
        for session_id in ("resume-aaaa-1111", "resume-bbbb-2222"):
            (out_dir / "gemini" / f"{session_id}.json").write_text(
                fx.RESPONSE_BARE + "\n", encoding="utf-8"
            )

        def refuse_input(_prompt=""):
            raise AssertionError("nothing to send must not reach the prompt")

        monkeypatch.setattr("builtins.input", refuse_input)
        assert bom.main(_live_argv(
            manifest, _prompt_file(tmp_path), out_dir
        )) == 0
        assert gemini_boundary == []
        assert "nothing to send" in capsys.readouterr().out


class TestBatchSubmitIsNotRepeatable:
    """A Message Batch is billed at creation and its id lives in one file."""

    @pytest.fixture
    def submit_stub(self, monkeypatch):
        """Fake ``anthropic`` that records submissions and replays results.

        ``.created`` is one entry per ``batches.create`` call; ``.results``
        is what the next ``--haiku-apply`` will retrieve, so a test can run
        the real submit -> partial apply -> top-up sequence rather than
        hand-building a state the code could never have produced.
        """
        stub = type("SubmitStub", (), {})()
        stub.created = []
        stub.results = []

        class FakeBatches:
            def create(self, requests):
                stub.created.append(requests)
                return type("Batch", (), {"id": f"batch_{len(stub.created):03d}"})()

            def retrieve(self, _batch_id):
                return type("Batch", (), {"processing_status": "ended"})()

            def results(self, _batch_id):
                return list(stub.results)

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = type("Messages", (), {"batches": FakeBatches()})()

        fake_module = type(sys)("anthropic")
        fake_module.Anthropic = FakeAnthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)
        return stub

    def _argv(self, manifest, prompt, out_dir, *extra):
        return [
            "--provider", "haiku",
            "--manifest", str(manifest),
            "--prompt", str(prompt),
            "--out-dir", str(out_dir),
            "--yes",
            *extra,
        ]

    def test_second_submit_is_refused_and_names_the_stored_batch(
        self, tmp_path, capsys, submit_stub
    ):
        """The finding: a re-run paid twice and orphaned the first batch."""
        manifest = _one_session_manifest(tmp_path, "batch-aaaa-1111")
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        assert len(submit_stub.created) == 1
        capsys.readouterr()

        assert bom.main(self._argv(manifest, prompt, out_dir)) == 2
        assert len(submit_stub.created) == 1  # nothing created the second time
        message = capsys.readouterr().err
        assert "batch_001" in message
        assert "--haiku-apply batch_001" in message
        assert f"--out-dir {out_dir}" in message
        assert "the SAME manifest" in message

    @staticmethod
    def _expected_retrieve_command(batch_id: str, root_out_dir: Path) -> str:
        """The recovery line, spelled out rather than pattern-matched.

        Substring assertions let both halves of this command rot: naming
        the provider subdirectory instead of its parent, or the wrong
        --provider, still "contains" the fragments a loose test checks.
        The operator copy-pastes this line, so it is pinned exactly.
        """
        return (
            "venv/bin/python3 scripts/bake-off-metadata.py "
            f"--provider haiku --haiku-apply {shlex.quote(batch_id)} "
            f"--out-dir {shlex.quote(str(root_out_dir))}"
        )

    def test_retrieve_command_is_exact(self, tmp_path):
        provider_dir = tmp_path / "out" / "haiku"
        assert bom.haiku_retrieve_command("batch_007", provider_dir) == (
            self._expected_retrieve_command("batch_007", tmp_path / "out")
        )

    def test_retrieve_command_quotes_a_directory_with_a_space(self, tmp_path):
        """Pin the literal text, not a mirror of the implementation.

        _expected_retrieve_command calls shlex.quote itself, so it would
        follow the implementation wherever it went. This spells the quoted
        form out.
        """
        provider_dir = tmp_path / "bake off runs" / "haiku"
        expected = (
            "venv/bin/python3 scripts/bake-off-metadata.py --provider haiku "
            f"--haiku-apply batch_007 --out-dir '{tmp_path}/bake off runs'"
        )
        assert bom.haiku_retrieve_command("batch_007", provider_dir) == expected

    def test_retrieve_command_quotes_a_hostile_batch_id(self):
        """A batch id never needs quoting today; quote it anyway.

        Anthropic's ids are msgbatch_ plus base62, so the quote is
        defensive. It is kept rather than dropped because the value is
        interpolated into a line an operator pastes into a shell, and the
        cost of being wrong later is a command that does something other
        than it reads. Pinned so the defence cannot be removed silently.
        """
        assert bom.haiku_retrieve_command(
            "batch 007; rm -rf /", Path("/tmp/out/haiku")
        ) == (
            "venv/bin/python3 scripts/bake-off-metadata.py --provider haiku "
            "--haiku-apply 'batch 007; rm -rf /' --out-dir /tmp/out"
        )

    def test_the_printed_recovery_line_is_exact(
        self, tmp_path, capsys, submit_stub
    ):
        manifest = _one_session_manifest(tmp_path, "recovery-aaaa-1111")
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, _prompt_file(tmp_path), out_dir)) == 0
        printed = capsys.readouterr().out
        line = next(
            line for line in printed.splitlines()
            if line.startswith("[haiku] retrieve with: ")
        )
        assert line == "[haiku] retrieve with: " + self._expected_retrieve_command(
            "batch_001", out_dir
        )

    def test_the_emitted_line_actually_runs(
        self, tmp_path, capsys, submit_stub
    ):
        """Execute the recovery line rather than matching a string.

        The three equality tests above compare against a hand-written
        expectation, so they pinned a line that could not be run: --manifest
        and --prompt used to be required at the parser level, and feeding
        the printed command back in exited 2 with "the following arguments
        are required". This test splits the emitted line and hands the real
        argument vector to main(), which must reach the retrieval path.
        """
        manifest = _one_session_manifest(tmp_path, "roundtrip-aaaa-1111")
        prompt = _prompt_file(tmp_path)
        # A directory whose name contains a space: unquoted interpolation
        # splits it into separate arguments and the pasted line exits 2.
        out_dir = tmp_path / "bake off runs"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        line = next(
            line for line in capsys.readouterr().out.splitlines()
            if line.startswith("[haiku] retrieve with: ")
        )
        command = shlex.split(line[len("[haiku] retrieve with: "):])
        assert command[0].endswith("python3")
        assert command[1].endswith("bake-off-metadata.py")

        # The batch comes back with the one session it carried.
        submit_stub.results = [
            self._succeeded(
                bom.build_custom_id("roundtrip-aaaa-1111"), fx.RESPONSE_BARE
            )
        ]
        assert command[2:] == [
            "--provider", "haiku", "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir),
        ]
        assert bom.main(command[2:]) == 0
        written = out_dir / "haiku" / "roundtrip-aaaa-1111.json"
        assert json.loads(written.read_text()) == fx.RESPONSE_OBJECT

    def test_apply_needs_neither_manifest_nor_prompt(
        self, tmp_path, submit_stub
    ):
        """The retrieval path reads neither, so it must not demand them."""
        manifest = _one_session_manifest(tmp_path, "noargs-aaaa-1111")
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, _prompt_file(tmp_path), out_dir)) == 0
        submit_stub.results = [
            self._succeeded(
                bom.build_custom_id("noargs-aaaa-1111"), fx.RESPONSE_BARE
            )
        ]
        assert bom.main([
            "--provider", "haiku",
            "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir),
        ]) == 0
        assert (out_dir / "haiku" / "noargs-aaaa-1111.json").exists()

    @pytest.mark.parametrize("supplied", ["neither", "manifest", "prompt"])
    def test_a_live_run_still_demands_manifest_and_prompt(
        self, tmp_path, capsys, supplied
    ):
        """Relaxing the parser must not let a billed run start without them.

        All three shapes are exercised because the fence is an ``and``:
        with only one of the two supplied, an ``or`` there passes the check
        and the run crashes further in with an AttributeError on None
        instead of exiting 2.
        """
        argv = ["--provider", "gemini", "--out-dir", str(tmp_path / "out"), "--yes"]
        if supplied == "manifest":
            argv += ["--manifest", str(_one_session_manifest(tmp_path))]
        elif supplied == "prompt":
            argv += ["--prompt", str(_prompt_file(tmp_path))]
        assert bom.main(argv) == 2
        assert "requires --manifest and --prompt" in capsys.readouterr().err

    @pytest.mark.parametrize("supplied", ["neither", "manifest", "prompt"])
    def test_build_rubric_still_demands_manifest_and_prompt(
        self, tmp_path, capsys, supplied
    ):
        """Same ``and`` fence, same three shapes — see the live-run test."""
        argv = [
            "--build-rubric",
            "--out-dir", str(tmp_path / "out"),
            "--rubric-in", str(tmp_path / "in.md"),
            "--rubric-out", str(tmp_path / "out.md"),
        ]
        if supplied == "manifest":
            argv += ["--manifest", str(_one_session_manifest(tmp_path))]
        elif supplied == "prompt":
            argv += ["--prompt", str(_prompt_file(tmp_path))]
        assert bom.main(argv) == 2
        assert "requires --manifest and --prompt" in capsys.readouterr().err

    def test_the_refusal_repeats_that_exact_line(
        self, tmp_path, capsys, submit_stub
    ):
        manifest = _one_session_manifest(tmp_path, "recovery-bbbb-1111")
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        capsys.readouterr()
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 2
        message = capsys.readouterr().err
        assert self._expected_retrieve_command("batch_001", out_dir) in [
            line.strip() for line in message.splitlines()
        ]

    def test_a_different_manifest_is_still_refused_but_says_so(
        self, tmp_path, capsys, submit_stub
    ):
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        first = _one_session_manifest(tmp_path, "batch-bbbb-1111")
        assert bom.main(self._argv(first, prompt, out_dir)) == 0
        second_transcript = fx.write_session_transcript(
            tmp_path / "transcripts" / "other.jsonl", n_records=8
        )
        second = fx.write_manifest(
            tmp_path / "other-manifest.json",
            [fx.manifest_row("batch-cccc-2222", second_transcript)],
        )
        capsys.readouterr()
        assert bom.main(self._argv(second, prompt, out_dir)) == 2
        assert "a DIFFERENT manifest" in capsys.readouterr().err

    def test_force_resubmits_and_keeps_the_old_id(
        self, tmp_path, submit_stub
    ):
        manifest = _one_session_manifest(tmp_path, "batch-dddd-1111")
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        assert bom.main(self._argv(manifest, prompt, out_dir, "--force")) == 0
        state = json.loads((out_dir / "haiku" / "batch-state.json").read_text())
        assert state["batch_id"] == "batch_002"
        assert state["superseded_batches"] == ["batch_001"]

    @staticmethod
    def _succeeded(custom_id: str, text: str):
        """One batch result object shaped like the SDK's."""
        block = type("Block", (), {"type": "text", "text": text})()
        message = type("Message", (), {"content": [block]})()
        inner = type("Inner", (), {"type": "succeeded", "message": message})()
        return type("Result", (), {"custom_id": custom_id, "result": inner})()

    def _three_session_manifest(self, tmp_path):
        rows = []
        for index in range(3):
            session_id = f"topup-{index}-aaaa-bbbb"
            transcript = fx.write_session_transcript(
                tmp_path / "transcripts" / f"{session_id}.jsonl", n_records=8
            )
            rows.append(fx.manifest_row(session_id, transcript))
        return fx.write_manifest(tmp_path / "manifest.json", rows)

    def test_resubmit_tops_up_only_the_missing_sessions(
        self, tmp_path, capsys, submit_stub
    ):
        """The reachable sequence: submit, partial apply, top up.

        The previous version of this test hand-built a response file with no
        batch-state.json beside it — a state a real run cannot produce,
        because a submit always writes the state first. That hid the fact
        that the only way past the state check (--force) also re-sent
        everything, making the advertised top-up unreachable.
        """
        manifest = self._three_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"

        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        assert len(submit_stub.created[0]) == 3

        # A partial retrieval: the batch came back with two of the three.
        submit_stub.results = [
            self._succeeded(bom.build_custom_id(f"topup-{index}-aaaa-bbbb"),
                            fx.RESPONSE_BARE)
            for index in (0, 1)
        ]
        assert bom.main([
            "--provider", "haiku", "--haiku-apply", "batch_001",
            "--manifest", str(manifest), "--prompt", str(prompt),
            "--out-dir", str(out_dir),
        ]) == 0
        provider_dir = out_dir / "haiku"
        assert (provider_dir / "topup-0-aaaa-bbbb.json").exists()
        assert not (provider_dir / "topup-2-aaaa-bbbb.json").exists()
        capsys.readouterr()

        # The top-up: permitted to submit again, still filtered to the gap.
        assert bom.main(self._argv(manifest, prompt, out_dir, "--resubmit")) == 0
        assert len(submit_stub.created) == 2
        assert len(submit_stub.created[1]) == 1
        assert submit_stub.created[1][0]["custom_id"] == bom.build_custom_id(
            "topup-2-aaaa-bbbb"
        )
        assert "requests:       1" in capsys.readouterr().out
        state = json.loads((provider_dir / "batch-state.json").read_text())
        assert state["batch_id"] == "batch_002"
        assert state["superseded_batches"] == ["batch_001"]
        # n_requests describes THIS batch, not the cumulative map. Since the
        # map now accumulates across submissions (so a superseded batch stays
        # retrievable), len(custom_id_to_session) is 3 here while the batch
        # actually submitted carried 1; reporting the map size would overstate
        # what the top-up cost.
        assert state["n_requests"] == 1
        assert len(state["custom_id_to_session"]) == 3

    def test_the_superseded_batch_is_still_retrievable(
        self, tmp_path, capsys, submit_stub
    ):
        """A top-up must not strand the sessions of the batch it supersedes.

        The state file holds one custom_id map. A top-up carries only the
        missing sessions, so replacing that map left --haiku-apply on the
        earlier batch id skipping every session it had paid for, with the
        "no session mapped to custom_id ..." diagnostic.
        """
        manifest = self._three_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        provider_dir = out_dir / "haiku"

        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        submit_stub.results = [
            self._succeeded(bom.build_custom_id("topup-0-aaaa-bbbb"),
                            fx.RESPONSE_BARE)
        ]
        assert bom.main([
            "--provider", "haiku", "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir),
        ]) == 0
        assert bom.main(self._argv(manifest, prompt, out_dir, "--resubmit")) == 0
        capsys.readouterr()

        # batch_001 is now superseded — and still holds two paid results.
        submit_stub.results = [
            self._succeeded(bom.build_custom_id(f"topup-{index}-aaaa-bbbb"),
                            fx.RESPONSE_BARE)
            for index in (0, 1)
        ]
        assert bom.main([
            "--provider", "haiku", "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir),
        ]) == 0
        printed = capsys.readouterr().out
        # The live wording, not a retired one: a stale phrase here can never
        # appear, so the assertion would hold however badly the code broke.
        assert "no session mapped to custom_id" not in printed
        assert "skipping a result that was ALREADY PAID FOR" not in printed
        assert (provider_dir / "topup-1-aaaa-bbbb.json").exists()

        state = json.loads((provider_dir / "batch-state.json").read_text())
        assert set(state["custom_id_to_session"].values()) == {
            f"topup-{index}-aaaa-bbbb" for index in range(3)
        }

    def test_the_superseded_chain_survives_two_top_ups(
        self, tmp_path, capsys, submit_stub
    ):
        """Each superseded id must stay in the trail, not just the last one."""
        manifest = self._three_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        for index in (0, 1):
            submit_stub.results = [
                self._succeeded(bom.build_custom_id(f"topup-{index}-aaaa-bbbb"),
                                fx.RESPONSE_BARE)
            ]
            assert bom.main([
                "--provider", "haiku",
                "--haiku-apply", f"batch_{index + 1:03d}",
                "--out-dir", str(out_dir),
            ]) == 0
            assert bom.main(
                self._argv(manifest, prompt, out_dir, "--resubmit")
            ) == 0
        capsys.readouterr()
        state = json.loads((out_dir / "haiku" / "batch-state.json").read_text())
        assert state["batch_id"] == "batch_003"
        assert state["superseded_batches"] == ["batch_001", "batch_002"]

    def test_force_sends_the_whole_manifest_again(
        self, tmp_path, capsys, submit_stub
    ):
        """--force keeps its meaning: everything, not just the gap."""
        manifest = self._three_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        submit_stub.results = [
            self._succeeded(bom.build_custom_id(f"topup-{index}-aaaa-bbbb"),
                            fx.RESPONSE_BARE)
            for index in (0, 1)
        ]
        assert bom.main([
            "--provider", "haiku", "--haiku-apply", "batch_001",
            "--manifest", str(manifest), "--prompt", str(prompt),
            "--out-dir", str(out_dir),
        ]) == 0
        capsys.readouterr()
        assert bom.main(self._argv(manifest, prompt, out_dir, "--force")) == 0
        assert len(submit_stub.created[1]) == 3

    def test_resubmit_is_rejected_off_the_batch_arm(self, tmp_path, capsys):
        """The other arms have no batch state, so the flag would be a no-op."""
        manifest = self._three_session_manifest(tmp_path)
        code = bom.main([
            "--provider", "gemini",
            "--manifest", str(manifest),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(tmp_path / "out"),
            "--resubmit", "--yes",
        ])
        assert code == 2
        assert "--resubmit is only valid with --provider haiku" in (
            capsys.readouterr().err
        )

    def test_resubmit_cannot_be_combined_with_apply(self, tmp_path, capsys):
        """Retrieval submits nothing, so there is no top-up to permit."""
        code = bom.main([
            "--provider", "haiku",
            "--haiku-apply", "batch_invented",
            "--out-dir", str(tmp_path / "out"),
            "--resubmit",
        ])
        assert code == 2
        assert "cannot be combined with --haiku-apply" in capsys.readouterr().err
        assert not (tmp_path / "out").exists()

    def test_resubmit_still_refuses_when_nothing_is_missing(
        self, tmp_path, capsys, submit_stub
    ):
        """A top-up with no gap must not create an empty second batch."""
        manifest = self._three_session_manifest(tmp_path)
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        submit_stub.results = [
            self._succeeded(bom.build_custom_id(f"topup-{index}-aaaa-bbbb"),
                            fx.RESPONSE_BARE)
            for index in range(3)
        ]
        assert bom.main([
            "--provider", "haiku", "--haiku-apply", "batch_001",
            "--manifest", str(manifest), "--prompt", str(prompt),
            "--out-dir", str(out_dir),
        ]) == 0
        capsys.readouterr()
        assert bom.main(self._argv(manifest, prompt, out_dir, "--resubmit")) == 0
        assert len(submit_stub.created) == 1
        assert "nothing to send" in capsys.readouterr().out

    def test_the_state_check_fires_before_the_gate(
        self, tmp_path, capsys, monkeypatch, submit_stub
    ):
        """Pin the main-level check independently of the adapter backstop.

        Both layers refuse, so deleting the one in main() left every
        existing test green -- the adapter simply raised instead. What
        distinguishes them is WHEN: main refuses before the API Call
        Review Gate, so an operator is never asked to approve a run that
        cannot happen. Assert on that, not merely on the exit code.
        """
        manifest = _one_session_manifest(tmp_path, "gateorder-aaaa-1111")
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        capsys.readouterr()

        def refuse_input(_prompt=""):
            raise AssertionError(
                "an already-submitted directory must be refused before the "
                "gate, not after it"
            )

        monkeypatch.setattr("builtins.input", refuse_input)
        # No --yes: reaching the gate at all would call input().
        code = bom.main([
            "--provider", "haiku",
            "--manifest", str(manifest),
            "--prompt", str(prompt),
            "--out-dir", str(out_dir),
        ])
        assert code == 2
        captured = capsys.readouterr()
        assert "API Call Review Gate" not in captured.out
        assert len(submit_stub.created) == 1

    def test_the_adapter_refuses_on_its_own(self, tmp_path, submit_stub):
        """Pin the backstop independently of main's check.

        main passes allow_resubmit=args.force or args.resubmit; hardcoding
        that to True is invisible through main, because main's own check
        fires first in every case that would differ. The guard is real
        defence for any other caller, so it is exercised directly.
        """
        manifest = _one_session_manifest(tmp_path, "adapter-aaaa-1111")
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        provider_dir = out_dir / "haiku"
        state_path = provider_dir / "batch-state.json"
        before = state_path.read_bytes()
        submitted = len(submit_stub.created)

        requests = bom.assemble_requests(manifest, prompt)
        with pytest.raises(bom.BatchStateExistsError):
            bom.haiku_submit(
                requests, provider_dir, "system prompt",
                manifest_path=manifest, allow_resubmit=False,
            )
        # Nothing sent, nothing written.
        assert len(submit_stub.created) == submitted
        assert state_path.read_bytes() == before

    def test_three_colliding_sessions_are_all_reported(
        self, tmp_path, submit_stub, monkeypatch
    ):
        """Truncating the clash list hides a session from the operator."""
        monkeypatch.setattr(bom, "build_custom_id", lambda _session_id: "sess-same")
        rows = []
        for name in ("clash-first", "clash-second", "clash-third"):
            transcript = fx.write_session_transcript(
                tmp_path / "transcripts" / f"{name}.jsonl", n_records=6
            )
            rows.append(fx.manifest_row(name, transcript))
        manifest = fx.write_manifest(tmp_path / "manifest.json", rows)
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        out_dir = tmp_path / "haiku"
        out_dir.mkdir()
        with pytest.raises(ValueError) as excinfo:
            bom.haiku_submit(
                requests, out_dir, "system prompt", manifest_path=manifest
            )
        message = str(excinfo.value)
        for name in ("clash-first", "clash-second", "clash-third"):
            assert name in message, name
        assert submit_stub.created == []

    def test_state_records_the_manifest_fingerprint(self, tmp_path, submit_stub):
        manifest = _one_session_manifest(tmp_path, "batch-gggg-1111")
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, _prompt_file(tmp_path), out_dir)) == 0
        state = json.loads((out_dir / "haiku" / "batch-state.json").read_text())
        assert state["manifest_sha256"] == bom.file_sha256(manifest)
        assert state["manifest_path"] == str(manifest)

    def test_the_refusal_names_the_real_submission_time(
        self, tmp_path, capsys, submit_stub
    ):
        """A placeholder "unknown" would survive a loose assertion.

        The timestamp is how an operator decides whether the stored batch is
        this morning's job or last month's, so the refusal must repeat the
        value actually recorded, not a default.
        """
        manifest = _one_session_manifest(tmp_path, "stamp-aaaa-1111")
        prompt = _prompt_file(tmp_path)
        out_dir = tmp_path / "out"
        assert bom.main(self._argv(manifest, prompt, out_dir)) == 0
        state = json.loads((out_dir / "haiku" / "batch-state.json").read_text())
        submitted_at = state["submitted_at"]
        # A real, parseable stamp -- not "unknown", not the empty string.
        datetime.strptime(submitted_at, "%Y-%m-%dT%H:%M:%S%z")
        capsys.readouterr()

        assert bom.main(self._argv(manifest, prompt, out_dir)) == 2
        message = capsys.readouterr().err
        assert f"submitted: {submitted_at}" in message
        assert "unknown" not in message

    def test_colliding_custom_ids_are_refused_before_the_billed_call(
        self, tmp_path, submit_stub, monkeypatch
    ):
        """Injectivity is checked before batches.create, not after."""
        monkeypatch.setattr(bom, "build_custom_id", lambda _session_id: "sess-same")
        rows = []
        for session_id in ("clash-aaaa", "clash-bbbb"):
            transcript = fx.write_session_transcript(
                tmp_path / "transcripts" / f"{session_id}.jsonl", n_records=6
            )
            rows.append(fx.manifest_row(session_id, transcript))
        manifest = fx.write_manifest(tmp_path / "manifest.json", rows)
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        out_dir = tmp_path / "haiku"
        out_dir.mkdir()
        with pytest.raises(ValueError, match="custom_id collision") as excinfo:
            bom.haiku_submit(
                requests, out_dir, "system prompt", manifest_path=manifest
            )
        # The message must name BOTH sessions and the id they collapsed
        # onto: "a collision happened" is not actionable, and the operator
        # has to know which two transcripts to look at.
        message = str(excinfo.value)
        assert "clash-aaaa" in message
        assert "clash-bbbb" in message
        assert "sess-same" in message
        assert submit_stub.created == []
        assert not (out_dir / "batch-state.json").exists()


class TestRefusalExitCodesAreDistinct:
    """A wrapper must be able to tell refusal from success and from misuse."""

    def test_nothing_to_do_is_still_success(self, tmp_path, gemini_boundary):
        """An empty manifest is not a refusal: there was nothing to approve."""
        manifest = fx.write_manifest(tmp_path / "manifest.json", [])
        code = bom.main(_live_argv(
            manifest, _prompt_file(tmp_path), tmp_path / "out"
        ))
        assert code == 0

    def test_usage_error_is_two_not_three(self, tmp_path):
        code = bom.main([
            "--build-rubric",
            "--manifest", str(_one_session_manifest(tmp_path)),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(tmp_path / "out"),
        ])
        assert code == 2


class TestAtomicWriteStaysOnOneFilesystem:
    """``os.replace`` cannot cross a filesystem boundary."""

    def test_temp_file_is_created_in_the_target_directory(self, tmp_path, monkeypatch):
        """The finding: dropping dir= survived every test on one filesystem.

        In production the responses live under data/experiments while the
        default temp directory is /tmp — different filesystems here — so a
        temp file made in the default location would make os.replace raise
        EXDEV on every write.
        """
        import tempfile as tempfile_module

        recorded: list = []
        real_mkstemp = tempfile_module.mkstemp

        def recording_mkstemp(*args, **kwargs):
            recorded.append(kwargs.get("dir"))
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(tempfile_module, "mkstemp", recording_mkstemp)
        target = tmp_path / "responses" / "session.json"
        bom.write_json_atomic(target, {"ok": True})
        assert recorded == [str(target.parent)]

    def test_write_survives_a_cross_device_rename_barrier(self, tmp_path, monkeypatch):
        """Simulate EXDEV: a rename between directories must never be needed."""
        import errno
        import os as os_module

        real_replace = os_module.replace

        def replace_refusing_cross_directory(src, dst):
            if Path(src).parent != Path(dst).parent:
                raise OSError(
                    errno.EXDEV, "Invalid cross-device link", str(src), None, str(dst)
                )
            return real_replace(src, dst)

        monkeypatch.setattr(os_module, "replace", replace_refusing_cross_directory)
        target = tmp_path / "responses" / "session.json"
        bom.write_json_atomic(target, {"ok": True})
        assert json.loads(target.read_text()) == {"ok": True}


class TestHaikuApplyResume:
    """A resumed retrieval must not overwrite what an earlier one wrote."""

    @staticmethod
    def _state(out_dir: Path, mapping: dict[str, str]) -> None:
        (out_dir / "batch-state.json").write_text(
            json.dumps({"batch_id": "batch_invented", "custom_id_to_session": mapping}),
            encoding="utf-8",
        )

    def test_complete_response_is_not_refetched(
        self, tmp_path, capsys, monkeypatch
    ):
        """The finding: the resume branch was untested and could be deleted."""
        stub = TestHaikuApplyBoundary()
        results: list = []

        class FakeBatches:
            def retrieve(self, _batch_id):
                return type("Batch", (), {"processing_status": "ended"})()

            def results(self, _batch_id):
                return list(results)

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = type("Messages", (), {"batches": FakeBatches()})()

        fake_module = type(sys)("anthropic")
        fake_module.Anthropic = FakeAnthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)

        out_dir = tmp_path / "haiku"
        out_dir.mkdir(parents=True)
        self._state(out_dir, {"sess-known": "known-session"})
        target = out_dir / "known-session.json"
        target.write_text(fx.RESPONSE_BARE + "\n", encoding="utf-8")
        before = target.stat().st_mtime_ns, target.stat().st_size

        replacement = json.dumps({"title": "a different, later answer"})
        results.append(stub._result("sess-known", replacement))
        bom.haiku_apply("batch_invented", out_dir)

        assert (target.stat().st_mtime_ns, target.stat().st_size) == before
        assert json.loads(target.read_text()) == fx.RESPONSE_OBJECT
        assert not (out_dir / "known-session.raw.txt").exists()
        assert "already complete — skipping" in capsys.readouterr().out

    def test_force_refetches_the_same_session(self, tmp_path, monkeypatch):
        """--force is the deliberate way to replace a stored answer."""
        stub = TestHaikuApplyBoundary()
        results: list = []

        class FakeBatches:
            def retrieve(self, _batch_id):
                return type("Batch", (), {"processing_status": "ended"})()

            def results(self, _batch_id):
                return list(results)

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = type("Messages", (), {"batches": FakeBatches()})()

        fake_module = type(sys)("anthropic")
        fake_module.Anthropic = FakeAnthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)

        out_dir = tmp_path / "haiku"
        out_dir.mkdir(parents=True)
        self._state(out_dir, {"sess-known": "known-session"})
        (out_dir / "known-session.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )
        replacement = json.dumps({"title": "a different, later answer"})
        results.append(stub._result("sess-known", replacement))
        bom.haiku_apply("batch_invented", out_dir, force=True)
        assert json.loads((out_dir / "known-session.json").read_text()) == {
            "title": "a different, later answer"
        }


class TestFailureCountsOnlyCountFilesWritten:
    """The summary must describe what landed on disk, not what was attempted."""

    def test_record_failure_reports_whether_it_wrote(self, tmp_path):
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)
        assert bom.record_failure(out_dir, "fresh", {"error": "x"}, tag="gemini") is True
        (out_dir / "kept.json").write_text(fx.RESPONSE_BARE + "\n", encoding="utf-8")
        assert bom.record_failure(out_dir, "kept", {"error": "x"}, tag="gemini") is False

    def test_a_kept_response_is_not_counted_as_a_failure_written(
        self, tmp_path, capsys, monkeypatch, gemini_boundary
    ):
        """The finding: a refused write still incremented the failure count."""
        manifest = _one_session_manifest(tmp_path, "kept-aaaa-1111")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)
        (out_dir / "kept-aaaa-1111.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )

        def always_fails(*args, **kwargs):
            raise RuntimeError("503 Service Unavailable")

        monkeypatch.setattr(bom, "gemini_call_with_retry", always_fails)
        # force=True so the completed session is attempted at all.
        bom.gemini_run(requests, out_dir, "system prompt", force=True)
        printed = capsys.readouterr().out
        assert "wrote 0 successes and 0 failures" in printed
        assert "kept 1 earlier complete response(s)" in printed
        assert json.loads((out_dir / "kept-aaaa-1111.json").read_text()) == (
            fx.RESPONSE_OBJECT
        )

    def test_a_real_failure_is_still_counted(
        self, tmp_path, capsys, monkeypatch, gemini_boundary
    ):
        manifest = _one_session_manifest(tmp_path, "failed-aaaa-1111")
        requests = bom.assemble_requests(manifest, _prompt_file(tmp_path))
        out_dir = tmp_path / "gemini"
        out_dir.mkdir(parents=True)

        def always_fails(*args, **kwargs):
            raise RuntimeError("503 Service Unavailable")

        monkeypatch.setattr(bom, "gemini_call_with_retry", always_fails)
        bom.gemini_run(requests, out_dir, "system prompt")
        printed = capsys.readouterr().out
        assert "wrote 0 successes and 1 failures" in printed
        assert "kept" not in printed


class TestEmptyContentBranchCounts:
    """A succeeded result with no text blocks is one failure, counted once."""

    @pytest.fixture
    def apply_stub(self, monkeypatch):
        """Fake ``anthropic`` returning whatever results a test appends."""
        results: list = []

        class FakeBatches:
            def retrieve(self, _batch_id):
                return type("Batch", (), {"processing_status": "ended"})()

            def results(self, _batch_id):
                return list(results)

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = type("Messages", (), {"batches": FakeBatches()})()

        fake_module = type(sys)("anthropic")
        fake_module.Anthropic = FakeAnthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)
        return results

    @staticmethod
    def _empty_content(custom_id: str):
        """A result the API reports as succeeded but with no content blocks."""
        message = type("Message", (), {"content": []})()
        inner = type("Inner", (), {"type": "succeeded", "message": message})()
        return type("Result", (), {"custom_id": custom_id, "result": inner})()

    def _out_dir(self, tmp_path: Path) -> Path:
        out_dir = tmp_path / "haiku"
        out_dir.mkdir(parents=True)
        (out_dir / "batch-state.json").write_text(
            json.dumps({
                "batch_id": "batch_invented",
                "custom_id_to_session": {"sess-empty": "empty-session"},
            }),
            encoding="utf-8",
        )
        return out_dir

    def test_it_counts_exactly_one_failure(self, tmp_path, capsys, apply_stub):
        """The finding: this branch incremented n_fail twice."""
        out_dir = self._out_dir(tmp_path)
        apply_stub.append(self._empty_content("sess-empty"))
        bom.haiku_apply("batch_invented", out_dir)
        printed = capsys.readouterr().out
        assert "wrote 0 successes and 1 failures" in printed
        assert "kept" not in printed
        # The diagnostic is the only thing that tells an operator WHY a
        # session the API called "succeeded" produced an error record.
        assert (
            "[haiku] succeeded result for empty-session carried no content "
            "blocks — recording empty-content error"
        ) in printed
        assert json.loads((out_dir / "empty-session.json").read_text()) == {
            "error": "succeeded result had empty content list"
        }

    def test_a_kept_response_counts_as_kept_not_failed(
        self, tmp_path, capsys, apply_stub
    ):
        """With an answer already on disk the branch must keep, not overwrite."""
        out_dir = self._out_dir(tmp_path)
        (out_dir / "empty-session.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )
        apply_stub.append(self._empty_content("sess-empty"))
        # force=True so the earlier skip does not short-circuit the branch.
        bom.haiku_apply("batch_invented", out_dir, force=True)
        printed = capsys.readouterr().out
        assert "wrote 0 successes and 0 failures" in printed
        assert "kept 1 earlier complete response(s)" in printed
        assert json.loads((out_dir / "empty-session.json").read_text()) == (
            fx.RESPONSE_OBJECT
        )


class TestStrandedResults:
    """An unmatched result is money already spent; say so, and offer a fix."""

    @pytest.fixture
    def anthropic_stub(self, monkeypatch):
        """Fake ``anthropic`` returning whatever results a test appends."""
        results: list = []

        class FakeBatches:
            def retrieve(self, _batch_id):
                return type("Batch", (), {"processing_status": "ended"})()

            def results(self, _batch_id):
                return list(results)

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = type("Messages", (), {"batches": FakeBatches()})()

        fake_module = type(sys)("anthropic")
        fake_module.Anthropic = FakeAnthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)
        return results

    @staticmethod
    def _succeeded(custom_id: str, text: str):
        block = type("Block", (), {"type": "text", "text": text})()
        message = type("Message", (), {"content": [block]})()
        inner = type("Inner", (), {"type": "succeeded", "message": message})()
        return type("Result", (), {"custom_id": custom_id, "result": inner})()

    def _old_format_state(self, tmp_path: Path, *, record_manifest: bool = True):
        """A state file whose map lost a superseded batch's entries.

        This is what a pre-accumulation top-up left behind: the map covers
        only the sessions of the LAST submission, so retrieving the earlier
        batch finds results it cannot place.
        """
        out_dir = tmp_path / "out" / "haiku"
        out_dir.mkdir(parents=True)
        rows = []
        for index in range(3):
            session_id = f"stranded-{index}"
            transcript = fx.write_session_transcript(
                tmp_path / "transcripts" / f"{session_id}.jsonl", n_records=6
            )
            rows.append(fx.manifest_row(session_id, transcript))
        manifest = fx.write_manifest(tmp_path / "manifest.json", rows)
        state = {
            "batch_id": "batch_002",
            "custom_id_to_session": {
                bom.build_custom_id("stranded-2"): "stranded-2",
            },
        }
        if record_manifest:
            state["manifest_path"] = str(manifest)
        (out_dir / "batch-state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
        return out_dir, manifest

    def test_recover_session_id_reads_a_verbatim_custom_id(self):
        assert bom.recover_session_id_from_custom_id("sess-abc-123") == "abc-123"
        assert bom.recover_session_id_from_custom_id("sess-" + "a" * 40) is None
        assert bom.recover_session_id_from_custom_id("nonsense") is None

    def test_a_forty_hex_session_id_is_recovered_not_called_a_digest(self):
        """The shape test alone gets this exactly backwards.

        A session id can itself be 40 hex characters. build_custom_id emits
        it verbatim -- the same shape a digest has -- so deciding on shape
        told the operator the id was unrecoverable while it sat in plain
        sight. The manifest settles it.
        """
        session_id = "0123456789abcdef" * 2 + "01234567"
        assert len(session_id) == 40
        custom_id = bom.build_custom_id(session_id)
        assert custom_id == f"sess-{session_id}"
        assert bom.recover_session_id_from_custom_id(custom_id) is None
        assert bom.recover_session_id_from_custom_id(
            custom_id, {session_id}
        ) == session_id

    def test_a_hashed_custom_id_is_reversed_through_the_manifest(self):
        """build_custom_id is pure, so the digest form is reversible too."""
        session_id = "subagent-explore-" + "x" * 80
        custom_id = bom.build_custom_id(session_id)
        assert custom_id != f"sess-{session_id}"
        assert bom.recover_session_id_from_custom_id(custom_id) is None
        assert bom.recover_session_id_from_custom_id(
            custom_id, {session_id, "an-unrelated-session"}
        ) == session_id

    def test_known_session_ids_survives_a_missing_or_broken_manifest(self, tmp_path):
        assert bom.known_session_ids({}) == set()
        assert bom.known_session_ids({"manifest_path": str(tmp_path / "gone")}) == set()
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert bom.known_session_ids({"manifest_path": str(broken)}) == set()
        shapeless = tmp_path / "shapeless.json"
        shapeless.write_text('{"sessions": "not a list"}', encoding="utf-8")
        assert bom.known_session_ids({"manifest_path": str(shapeless)}) == set()

    def test_the_diagnostic_confirms_the_session_from_the_manifest(
        self, tmp_path, capsys, anthropic_stub
    ):
        """End to end: a 40-hex session id must be named, not written off."""
        out_dir = tmp_path / "out" / "haiku"
        out_dir.mkdir(parents=True)
        session_id = "abcdef0123456789" * 2 + "abcdef01"
        transcript = fx.write_session_transcript(
            tmp_path / "transcripts" / "hexid.jsonl", n_records=6
        )
        manifest = fx.write_manifest(
            tmp_path / "manifest.json", [fx.manifest_row(session_id, transcript)]
        )
        (out_dir / "batch-state.json").write_text(
            json.dumps({
                "batch_id": "batch_002",
                "manifest_path": str(manifest),
                "custom_id_to_session": {},
            }),
            encoding="utf-8",
        )
        anthropic_stub.append(
            self._succeeded(bom.build_custom_id(session_id), fx.RESPONSE_BARE)
        )
        bom.haiku_apply("batch_001", out_dir)
        printed = capsys.readouterr().out
        assert f"probably session {session_id}" in printed
        assert "not recoverable" not in printed

    def test_the_diagnostic_names_the_session_and_the_remedy(
        self, tmp_path, capsys, anthropic_stub
    ):
        """The finding: a bare custom_id, no session, no remedy, no count."""
        out_dir, _manifest = self._old_format_state(tmp_path)
        anthropic_stub.append(
            self._succeeded(bom.build_custom_id("stranded-0"), fx.RESPONSE_BARE)
        )
        bom.haiku_apply("batch_001", out_dir)
        printed = capsys.readouterr().out
        assert "probably session stranded-0" in printed
        assert "ALREADY PAID FOR" in printed
        assert "--rebuild-map" in printed
        # And it is counted, rather than vanishing from both tallies.
        assert "skipped 0 already-complete and 1 unmapped result(s)" in printed
        assert not (out_dir / "stranded-0.json").exists()

    def test_already_complete_skips_are_counted_too(
        self, tmp_path, capsys, anthropic_stub
    ):
        out_dir, _manifest = self._old_format_state(tmp_path)
        (out_dir / "stranded-2.json").write_text(
            fx.RESPONSE_BARE + "\n", encoding="utf-8"
        )
        anthropic_stub.append(
            self._succeeded(bom.build_custom_id("stranded-2"), fx.RESPONSE_BARE)
        )
        bom.haiku_apply("batch_002", out_dir)
        assert "skipped 1 already-complete and 0 unmapped result(s)" in (
            capsys.readouterr().out
        )

    def test_rebuild_map_restores_the_entries(self, tmp_path, capsys):
        out_dir, manifest = self._old_format_state(tmp_path)
        added = bom.rebuild_custom_id_map(out_dir, manifest)
        assert added == 2
        state = json.loads((out_dir / "batch-state.json").read_text())
        assert set(state["custom_id_to_session"].values()) == {
            "stranded-0", "stranded-1", "stranded-2",
        }
        # The existing entry is untouched: it came from a real submission.
        assert state["custom_id_to_session"][bom.build_custom_id("stranded-2")] == (
            "stranded-2"
        )

    def test_the_remedy_actually_recovers_the_result(
        self, tmp_path, capsys, anthropic_stub
    ):
        """Run the suggested command and the stranded result lands."""
        out_dir, manifest = self._old_format_state(tmp_path)
        anthropic_stub.append(
            self._succeeded(bom.build_custom_id("stranded-0"), fx.RESPONSE_BARE)
        )
        assert bom.main([
            "--provider", "haiku",
            "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir.parent),
            "--manifest", str(manifest),
            "--rebuild-map",
        ]) == 0
        printed = capsys.readouterr().out
        assert "restored 2 custom_id mapping(s)" in printed
        assert json.loads((out_dir / "stranded-0.json").read_text()) == (
            fx.RESPONSE_OBJECT
        )

    def test_the_remedy_line_splits_and_runs(
        self, tmp_path, capsys, anthropic_stub
    ):
        """Paste the printed remedy back in and it must repair and retrieve.

        The placeholder used to be ``<manifest>``, which a shell reads as a
        redirection: pasting the line produced "bash: manifest: No such file
        or directory" and did nothing. The state records the manifest it was
        submitted against, so the line now names it.
        """
        out_dir, manifest = self._old_format_state(tmp_path)
        anthropic_stub.append(
            self._succeeded(bom.build_custom_id("stranded-0"), fx.RESPONSE_BARE)
        )
        bom.haiku_apply("batch_001", out_dir)
        printed = capsys.readouterr().out
        line = next(
            line.strip() for line in printed.splitlines()
            if "--rebuild-map" in line
        )
        assert "<" not in line and ">" not in line  # nothing a shell redirects
        command = shlex.split(line)
        assert command[2:] == [
            "--provider", "haiku",
            "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir.parent),
            "--manifest", str(manifest),
            "--rebuild-map",
        ]

        anthropic_stub.append(
            self._succeeded(bom.build_custom_id("stranded-0"), fx.RESPONSE_BARE)
        )
        assert bom.main(command[2:]) == 0
        assert json.loads((out_dir / "stranded-0.json").read_text()) == (
            fx.RESPONSE_OBJECT
        )

    def test_the_placeholder_is_paste_safe_without_a_recorded_manifest(
        self, tmp_path, capsys, anthropic_stub
    ):
        """An older state file records no manifest; the line must still paste."""
        out_dir, _manifest = self._old_format_state(tmp_path, record_manifest=False)
        anthropic_stub.append(
            self._succeeded(bom.build_custom_id("stranded-0"), fx.RESPONSE_BARE)
        )
        bom.haiku_apply("batch_001", out_dir)
        line = next(
            line.strip() for line in capsys.readouterr().out.splitlines()
            if "--rebuild-map" in line
        )
        command = shlex.split(line)
        assert command[-3:] == [
            "--manifest", bom.MANIFEST_PLACEHOLDER, "--rebuild-map"
        ]
        assert "<" not in line and ">" not in line

    def test_a_placeholder_manifest_is_refused_not_crashed(self, tmp_path, capsys):
        """Running the line unedited must fail cleanly, not traceback."""
        out_dir, _manifest = self._old_format_state(tmp_path, record_manifest=False)
        assert bom.main([
            "--provider", "haiku",
            "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir.parent),
            "--manifest", bom.MANIFEST_PLACEHOLDER,
            "--rebuild-map",
        ]) == 2

    def test_rebuild_map_needs_a_manifest(self, tmp_path, capsys):
        out_dir, _manifest = self._old_format_state(tmp_path)
        assert bom.main([
            "--provider", "haiku",
            "--haiku-apply", "batch_001",
            "--out-dir", str(out_dir.parent),
            "--rebuild-map",
        ]) == 2
        assert "--rebuild-map needs --manifest" in capsys.readouterr().err

    def test_rebuild_map_needs_haiku_apply(self, tmp_path, capsys):
        out_dir, manifest = self._old_format_state(tmp_path)
        assert bom.main([
            "--provider", "haiku",
            "--manifest", str(manifest),
            "--prompt", str(_prompt_file(tmp_path)),
            "--out-dir", str(out_dir.parent),
            "--rebuild-map", "--dry-run",
        ]) == 2
        assert "use it with --haiku-apply" in capsys.readouterr().err

    def test_rebuild_map_refuses_without_a_state_file(self, tmp_path, capsys):
        manifest = fx.write_manifest(tmp_path / "manifest.json", [])
        assert bom.main([
            "--provider", "haiku",
            "--haiku-apply", "batch_001",
            "--out-dir", str(tmp_path / "empty"),
            "--manifest", str(manifest),
            "--rebuild-map",
        ]) == 2
        assert "nothing to rebuild" in capsys.readouterr().err


class TestRebuildMapIsConservative:
    """Repairing a map must not overwrite it, or destroy it on failure."""

    def _state_with_conflicting_entry(self, tmp_path: Path):
        """A state whose recorded mapping disagrees with the reconstruction.

        Only a real submission knows which session a custom_id was sent
        under. A reconstruction is a good guess from the manifest, so where
        the two differ the stored value must survive -- otherwise repairing
        the map could point an existing, correct entry at the wrong session
        and write one session's answer under another's name.
        """
        out_dir = tmp_path / "out" / "haiku"
        out_dir.mkdir(parents=True)
        transcript = fx.write_session_transcript(
            tmp_path / "transcripts" / "conflict.jsonl", n_records=6
        )
        manifest = fx.write_manifest(
            tmp_path / "manifest.json",
            [fx.manifest_row("session-from-manifest", transcript)],
        )
        custom_id = bom.build_custom_id("session-from-manifest")
        (out_dir / "batch-state.json").write_text(
            json.dumps({
                "batch_id": "batch_001",
                "custom_id_to_session": {custom_id: "session-as-submitted"},
            }),
            encoding="utf-8",
        )
        return out_dir, manifest, custom_id

    def test_an_existing_entry_wins_over_the_reconstruction(self, tmp_path):
        out_dir, manifest, custom_id = self._state_with_conflicting_entry(tmp_path)
        added = bom.rebuild_custom_id_map(out_dir, manifest)
        assert added == 0
        state = json.loads((out_dir / "batch-state.json").read_text())
        assert state["custom_id_to_session"][custom_id] == "session-as-submitted"

    def test_a_failed_rebuild_leaves_the_state_intact(self, tmp_path, monkeypatch):
        """Crash injection: the state file is the only handle on the batch."""
        out_dir, manifest, _custom_id = self._state_with_conflicting_entry(tmp_path)
        state_path = out_dir / "batch-state.json"
        before = state_path.read_bytes()

        import os as os_module

        def refuse_replace(_src, _dst):
            raise OSError("disk full")

        monkeypatch.setattr(os_module, "replace", refuse_replace)
        with pytest.raises(OSError):
            bom.rebuild_custom_id_map(out_dir, manifest)
        assert state_path.read_bytes() == before
        # And no debris beside it.
        assert sorted(p.name for p in out_dir.iterdir()) == ["batch-state.json"]
