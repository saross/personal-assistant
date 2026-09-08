"""
Tests for the shared project-id encoder (audit IC3 / C-X3 fix).

Pins two contracts:

* The encoding (resolve to an absolute path, then replace every
  non-alphanumeric character with ``-``) matches what Claude Code itself
  writes under ``~/.claude/projects/`` — the live double-dash evidence in
  ``scripts/project_id.py:encode_project_id`` (audit R4).
* The retrieval hook's ``derive_project`` is now a thin wrapper over
  the shared encoder — both writers and readers MUST agree byte-for-byte
  on the encoded form.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
HOOKS_DIR = PROJECT_ROOT / "hooks"


@pytest.fixture(scope="module")
def encode():
    """Load the shared encoder."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from project_id import encode_project_id  # noqa: WPS433
    return encode_project_id


@pytest.fixture(scope="module")
def retrieval_hook_module():
    """Load hooks/session-start-retrieval.py as a module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "session_start_retrieval", HOOKS_DIR / "session-start-retrieval.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Parity with the historical inline encoding
# ---------------------------------------------------------------------------


# Each pair is ``(cwd, expected_encoded_form)``. The first five are the
# historical parity cases (alphanumeric components only, so the pre-audit-R4
# ``/``-only rule and the corrected rule agree on them). The last two are the
# R4 cases the old rule got wrong.
PARITY_CASES = [
    ("/home/shawn/personal-assistant", "-home-shawn-personal-assistant"),
    ("/home/shawn/Code/llm-history-paper", "-home-shawn-Code-llm-history-paper"),
    ("/", "-"),
    ("/tmp/foo/bar", "-tmp-foo-bar"),
    ("/home/shawn/Code/map-reader-llm", "-home-shawn-Code-map-reader-llm"),
    # Audit R4 — the live name observed under ~/.claude/projects/ on
    # amd-tower (2026-09-08). The dot in ``.claude`` becomes its own dash,
    # so the separator and the dot together read as a DOUBLE dash. The
    # pre-fix encoder emitted ``…-.claude-worktrees-…`` and every worktree
    # session therefore matched zero same-project memories.
    (
        "/home/shawn/personal-assistant/.claude/worktrees/workstream-g-efficacy",
        "-home-shawn-personal-assistant--claude-worktrees-workstream-g-efficacy",
    ),
    # A dotted component anywhere, not just ``.claude``.
    ("/home/shawn/Code/site.example/docs", "-home-shawn-Code-site-example-docs"),
]


@pytest.mark.parametrize("cwd,expected", PARITY_CASES)
def test_encode_matches_pre_batch_inline(encode, cwd, expected):
    """The shared encoder reproduces the exact inline implementation.

    Pins the audit IC3 fix: any drift between the live writer (the
    extraction hook) and the live reader (this hook) silently breaks
    project-aware filtering.
    """
    assert encode(cwd) == expected


def test_encode_empty_cwd_returns_none(encode):
    """An empty cwd yields ``None`` — callers treat this as 'no current
    project known' and skip filtering."""
    assert encode("") is None


def test_encode_resolves_relative(encode, tmp_path):
    """Relative paths are resolved before encoding.

    The historical inline call was ``Path(cwd).resolve()`` first, so
    the encoded form does not contain ``..`` or trailing slashes.
    """
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    relative = str(nested / ".." / "b")
    expected = re.sub(r"[^A-Za-z0-9]", "-", str(nested.resolve()))
    assert encode(relative) == expected


# ---------------------------------------------------------------------------
# Wrapper contract — derive_project routes through the shared encoder.
# ---------------------------------------------------------------------------


def test_derive_project_uses_shared_encoder(encode, retrieval_hook_module):
    """``derive_project`` must produce the same value as
    ``encode_project_id`` for arbitrary cwds.

    A future refactor that reverts to inline encoding would diverge
    from the shared helper and this test would catch it.
    """
    for cwd, _ in PARITY_CASES:
        assert retrieval_hook_module.derive_project(cwd) == encode(cwd)


def test_derive_project_empty_cwd(retrieval_hook_module):
    """Empty cwd → ``None`` — same contract as the shared encoder."""
    assert retrieval_hook_module.derive_project("") is None


# ---------------------------------------------------------------------------
# Audit R4 — every non-alphanumeric character encodes to a dash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cwd,expected", [
    ("/a/b.c", "-a-b-c"),
    ("/a/b_c", "-a-b-c"),
    ("/a/b c", "-a-b-c"),
    ("/a/b+c", "-a-b-c"),
    ("/a/b@c", "-a-b-c"),
])
def test_encode_rewrites_every_non_alphanumeric(encode, cwd, expected):
    """Kills: narrowing the character class back to ``/`` (or to ``[/.]``).

    Only ``/`` and ``.`` are attested in the live projects directory; the
    rest are the deliberate conservative inference documented on
    ``encode_project_id``. Pinning them here means a future narrowing is a
    decision someone makes on purpose, not a silent regression.
    """
    assert encode(cwd) == expected


def test_encode_is_stable_for_alphanumeric_paths(encode):
    """A path with no special characters is unchanged but for the separators."""
    assert encode("/home/shawn/Code/inscriptions") == "-home-shawn-Code-inscriptions"


# ---------------------------------------------------------------------------
# Lens B RT15 — decode_project_id, repo_set, repo_set_for
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_id_module():
    """The whole module, not just the encoder."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    import project_id  # noqa: WPS433
    return project_id


class TestDecodeProjectId:
    """Kills: returning a constant (``Path("/")``) for every input."""

    @pytest.mark.parametrize("project_id,expected", [
        ("-tmp-foo-bar", "/tmp/foo/bar"),
        ("-home-shawn-Code-inscriptions", "/home/shawn/Code/inscriptions"),
        ("-", "/"),
    ])
    def test_round_trips_paths_without_special_characters(
        self, project_id_module, project_id: str, expected: str,
    ) -> None:
        assert str(project_id_module.decode_project_id(project_id)) == expected

    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    def test_empty_input_returns_none(self, project_id_module, value: str) -> None:
        assert project_id_module.decode_project_id(value) is None

    @pytest.mark.parametrize("project_id,candidate", [
        # A hyphenated repo name is indistinguishable from more nesting.
        ("-home-shawn-Code-cc-session-toolkit",
         "/home/shawn/Code/cc/session/toolkit"),
        # Including the hub's own id: this does NOT decode back to the hub.
        ("-home-shawn-personal-assistant", "/home/shawn/personal/assistant"),
        # A dotted component encodes to a dash, so it decodes to nesting
        # too -- and Path collapses the resulting double separator, so the
        # dot is not merely ambiguous but wholly unrecoverable.
        ("-home-shawn-personal-assistant--claude-worktrees-wg",
         "/home/shawn/personal/assistant/claude/worktrees/wg"),
    ])
    def test_intrinsic_hyphens_are_the_documented_lossy_case(
        self, project_id_module, project_id: str, candidate: str,
    ) -> None:
        """The encoding is many-to-one; decode returns a candidate, not truth.

        Pinned so the caveat in the docstring stays honest: callers must
        check the candidate against the filesystem.
        """
        assert str(project_id_module.decode_project_id(project_id)) == candidate


class TestRepoSet:
    """Discovery walks the configured roots to their documented depth."""

    @staticmethod
    def _make_repo(path: Path, *, as_file: bool = False) -> Path:
        """Create a directory that looks like a git repo (dir or file .git)."""
        path.mkdir(parents=True, exist_ok=True)
        if as_file:
            (path / ".git").write_text("gitdir: ../.git/modules/x\n", encoding="utf-8")
        else:
            (path / ".git").mkdir()
        return path

    def test_finds_repos_at_each_documented_depth(
        self, project_id_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: collapsing the depth to 1 (every ~/Code repo disappears)."""
        code_repo = self._make_repo(tmp_path / "Code" / "inscriptions")
        hub = self._make_repo(tmp_path / "personal-assistant")
        submodule = self._make_repo(
            tmp_path / "personal-assistant" / "data", as_file=True,
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        found = set(project_id_module.repo_set())
        assert {code_repo, hub, submodule} <= found

    def test_a_directory_without_git_is_not_a_repo(
        self, project_id_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "Code" / "not-a-repo").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert project_id_module.repo_set() == []

    def test_missing_roots_yield_an_empty_list(
        self, project_id_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A fresh machine before any clone must not raise."""
        monkeypatch.setattr(
            Path, "home", classmethod(lambda cls: tmp_path / "nowhere"),
        )
        assert project_id_module.repo_set() == []

    def test_roots_are_re_read_from_the_current_home(
        self, project_id_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The roots are computed per call, not pinned at import."""
        first = self._make_repo(tmp_path / "a" / "personal-assistant")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "a"))
        assert project_id_module.repo_set() == [first]
        second = self._make_repo(tmp_path / "b" / "personal-assistant")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "b"))
        assert project_id_module.repo_set() == [second]


@pytest.fixture()
def roundtrip_home(project_id_module):
    """A temporary HOME whose absolute path survives encode -> decode.

    ``tmp_path`` cannot be used for the prioritisation test: pytest's
    directory names contain hyphens, the encoder maps every non-alphanumeric
    character to ``-``, and ``decode_project_id`` cannot tell those apart. So
    the decoded candidate never matched a discovered repo, ``primary`` was
    always empty, and the test passed under ``return primary or rest`` just
    as it did under ``primary + rest`` -- it was asserting nothing (audit
    M4). This root is named from a uuid hex, which is alphanumeric by
    construction, so the round trip is exact and prioritisation is reachable.
    """
    import shutil
    import tempfile
    import uuid

    root = Path(tempfile.gettempdir()) / f"pa{uuid.uuid4().hex}"
    root.mkdir()
    try:
        # If TMPDIR itself carries a hyphen or underscore the premise fails;
        # say so rather than passing vacuously all over again.
        encoded = project_id_module.encode_project_id(str(root))
        if project_id_module.decode_project_id(encoded) != root:
            pytest.skip(f"temp root {root} does not round-trip through the encoder")
        yield root
    finally:
        # Created by this fixture, inside the system temp directory, and
        # never anything the operator owns.
        shutil.rmtree(root, ignore_errors=True)


class TestRepoSetFor:
    """The memory's own project is checked first, when it can be identified."""

    def test_decoded_project_is_ordered_first(
        self, project_id_module, roundtrip_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: ``return primary + rest`` -> ``primary or rest``, and any
        other way of dropping the prioritisation (anchor_verify's fast path).

        Two repos are discovered and the decoded one must come first, so the
        assertion fails both if prioritisation is skipped and if the other
        repo is dropped from the result.
        """
        other = TestRepoSet._make_repo(roundtrip_home / "Code" / "alpha")
        target = TestRepoSet._make_repo(roundtrip_home / "Code" / "zulu")
        monkeypatch.setattr(
            Path, "home", classmethod(lambda cls: roundtrip_home),
        )
        encoded = project_id_module.encode_project_id(str(target))
        # The premise: the id really does decode back to the repo.
        assert project_id_module.decode_project_id(encoded) == target
        ordered = project_id_module.repo_set_for(encoded)
        assert ordered[0] == target
        assert set(ordered) == {target, other}

    def test_discovery_order_alone_would_not_pass(
        self, project_id_module, roundtrip_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Prioritisation must reorder, not merely agree with the walk.

        Checks the unprioritised order for both repos and then asserts the
        prioritised call puts the decoded one first regardless.
        """
        TestRepoSet._make_repo(roundtrip_home / "Code" / "alpha")
        TestRepoSet._make_repo(roundtrip_home / "Code" / "zulu")
        monkeypatch.setattr(
            Path, "home", classmethod(lambda cls: roundtrip_home),
        )
        discovered = project_id_module.repo_set()
        assert len(discovered) == 2
        for repo in discovered:
            encoded = project_id_module.encode_project_id(str(repo))
            assert project_id_module.repo_set_for(encoded)[0] == repo

    def test_none_project_returns_discovery_order(
        self, project_id_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        TestRepoSet._make_repo(tmp_path / "Code" / "alpha")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert project_id_module.repo_set_for(None) == project_id_module.repo_set()

    def test_undecodable_project_falls_back_gracefully(
        self, project_id_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hyphenated repo name decodes to a path that does not exist."""
        TestRepoSet._make_repo(tmp_path / "Code" / "cc-session-toolkit")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        ordered = project_id_module.repo_set_for("-home-shawn-Code-cc-session-toolkit")
        assert ordered == project_id_module.repo_set()
