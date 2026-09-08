"""
Tests for scripts/recover_anchors.py — the item-21b corpus-correction planner.

Covers the pure planning logic (``plan_record`` with injected resolvers, and
``add_revision``). The I/O paths (corpus walk, bulk-rewrite guard, git commit,
postgres update) are not exercised here — they reuse already-tested modules.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path


def _load(name, rel):
    path = Path(__file__).parent.parent / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ra = _load("recover_anchors", "scripts/recover_anchors.py")
av_module = ra.av


def _const(v):
    """A resolver/reverify stub that always returns ``v``."""
    return lambda *a, **k: v


class TestPlanRecord:
    def test_no_anchors_returns_none(self):
        assert ra.plan_record({"id": "x"}, _const("false"),
                               lambda r: None, _const(None)) is None

    def test_all_good_no_change_returns_none(self):
        rec = {"id": "x", "verified": "true",
               "anchors": [{"type": "file", "ref": "wiki/continuity.md"}]}
        # well-formed, resolves true, no recovery needed → nothing to do.
        assert ra.plan_record(rec, _const("true"), lambda r: None,
                              _const("true")) is None

    def test_recoverable_ref_is_rewritten_and_reverified(self):
        rec = {"id": "x", "verified": "false",
               "anchors": [{"type": "file", "ref": "continuity.md"}]}
        plan = ra.plan_record(
            rec,
            resolve=_const("false"),                       # ref resolves nowhere
            recover=lambda ref: "wiki/continuity.md",       # unique recovery
            reverify=_const("true"),                        # flips after rewrite
        )
        assert plan is not None
        assert plan["ref_rewrites"] == [("continuity.md", "wiki/continuity.md")]
        assert plan["new_verified"] == "true"
        assert plan["record"]["anchors"][0]["ref"] == "wiki/continuity.md"
        # original record untouched (deep copy)
        assert rec["anchors"][0]["ref"] == "continuity.md"

    def test_no_unique_recovery_means_no_rewrite(self):
        rec = {"id": "x", "verified": "false",
               "anchors": [{"type": "file", "ref": "ghost.md"}]}
        assert ra.plan_record(rec, _const("false"),
                              lambda ref: None, _const("false")) is None

    def test_junk_anchor_is_stripped(self):
        rec = {"id": "x", "verified": "false", "anchors": [
            {"type": "file", "ref": "scoring table (7 sessions, 42 cells)"},  # junk
            {"type": "file", "ref": "scripts/anchor_verify.py"},             # good
        ]}
        plan = ra.plan_record(rec, _const("true"), lambda ref: None, _const("true"))
        assert plan is not None
        assert len(plan["stripped"]) == 1
        assert plan["stripped"][0]["ref"].startswith("scoring table")
        assert [a["ref"] for a in plan["record"]["anchors"]] == ["scripts/anchor_verify.py"]

    def test_strip_all_anchors_clears_verified(self):
        rec = {"id": "x", "verified": "false", "category": "progress", "anchors": [
            {"type": "file", "ref": "/weekly-review"},   # slash-command junk
        ]}
        plan = ra.plan_record(rec, _const("false"), lambda ref: None, _const(None))
        assert plan is not None
        assert plan["record"]["anchors"] == []
        assert plan["new_verified"] is None
        assert plan["new_confidence"] == "low"

    def test_confidence_uses_guidance_and_why(self):
        # decision is a guidance category; verified true + why + how → high.
        rec = {"id": "x", "verified": "false", "category": "decision",
               "why": "because", "how_to_apply": "do this",
               "anchors": [{"type": "file", "ref": "continuity.md"}]}
        plan = ra.plan_record(rec, _const("false"),
                              lambda ref: "wiki/continuity.md", _const("true"))
        assert plan["new_confidence"] == "high"

    def test_recover_but_still_false_keeps_rewrite(self):
        # A second hard anchor keeps the record false; we still correct the ref.
        rec = {"id": "x", "verified": "false", "anchors": [
            {"type": "file", "ref": "continuity.md"},
            {"type": "file", "ref": "gone/forever.md"},
        ]}
        plan = ra.plan_record(
            rec,
            resolve=lambda t, ref: "false",
            recover=lambda ref: "wiki/continuity.md" if ref == "continuity.md" else None,
            reverify=_const("false"),
        )
        assert plan is not None
        assert plan["ref_rewrites"] == [("continuity.md", "wiki/continuity.md")]
        assert plan["new_verified"] == "false"


class TestAddRevision:
    def test_revision_shape_matches_forget_precedent(self):
        rec = {"id": "x"}
        ra.add_revision(rec, when="2026-05-31T00:00:00+00:00",
                        ref_rewrites=[("a.md", "dir/a.md")], stripped=[])
        rev = rec["revisions"][0]
        assert set(rev) == {"revised_at", "action", "reason"}
        assert rev["revised_at"] == "2026-05-31T00:00:00+00:00"
        assert "a.md -> dir/a.md" in rev["reason"]

    def test_revision_records_strips(self):
        rec = {"id": "x"}
        ra.add_revision(rec, when="2026-05-31T00:00:00+00:00", ref_rewrites=[],
                        stripped=[{"type": "file", "ref": "junk prose here"}])
        assert "stripped 1 junk anchor" in rec["revisions"][0]["reason"]


# ===========================================================================
# _git_commit — the explicit, literal pathspec
#
# Added by the PR #114 re-audit (2026-09-08). Same class as audit finding
# S16: a bare ``git commit`` after ``git add`` publishes whatever a
# concurrent session has already staged in the shared index, under this
# script's bulk-rewrite subject and trailer; and an unqualified pathspec is a
# GLOB, so a metacharacter in the path sweeps its lookalikes.
# ===========================================================================

import subprocess  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Bot",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test Bot",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _seed_repo(data_dir, monkeypatch):
    """Initialise a throwaway data repo with a deterministic git identity."""
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    subprocess.run(["git", "-C", str(data_dir), "init", "-q", "-b", "main"],
                   check=True)
    subprocess.run(["git", "-C", str(data_dir), "commit", "-q", "--allow-empty",
                    "-m", "seed"], check=True)


def _tracked_in_head(data_dir):
    return subprocess.run(
        ["git", "-C", str(data_dir), "show", "--name-only", "--pretty=format:",
         "HEAD"], capture_output=True, text=True, check=True).stdout.split()


def _staged(data_dir):
    return subprocess.run(
        ["git", "-C", str(data_dir), "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True).stdout.split()


def test_git_commit_leaves_another_sessions_staged_file_alone(tmp_path,
                                                              monkeypatch):
    data_dir = tmp_path / "data"
    corpus = data_dir / "memories" / "memories.jsonl"
    corpus.parent.mkdir(parents=True)
    corpus.write_text("{}\n", encoding="utf-8")
    _seed_repo(data_dir, monkeypatch)
    (data_dir / "unrelated.md").write_text("half-written prose\n",
                                           encoding="utf-8")
    subprocess.run(["git", "-C", str(data_dir), "add", "unrelated.md"],
                   check=True)

    ra._git_commit(corpus, 3, lambda subject, **kw: subject)

    committed = _tracked_in_head(data_dir)
    assert "memories/memories.jsonl" in committed
    assert "unrelated.md" not in committed, (
        "the anchor-recovery commit swept another session's staged file")
    assert _staged(data_dir) == ["unrelated.md"]


def test_git_commit_pathspec_is_matched_literally(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    corpus = data_dir / "memories[1]" / "memories.jsonl"
    decoy = data_dir / "memories1" / "memories.jsonl"     # glob lookalike
    corpus.parent.mkdir(parents=True)
    decoy.parent.mkdir(parents=True)
    corpus.write_text("{}\n", encoding="utf-8")
    _seed_repo(data_dir, monkeypatch)
    decoy.write_text("another session's work\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(data_dir), "add",
                    "memories1/memories.jsonl"], check=True)

    ra._git_commit(corpus, 1, lambda subject, **kw: subject)

    committed = _tracked_in_head(data_dir)
    assert "memories[1]/memories.jsonl" in committed
    assert "memories1/memories.jsonl" not in committed, (
        "the glob pathspec swept a lookalike directory")
    assert _staged(data_dir) == ["memories1/memories.jsonl"]


# ===========================================================================
# apply_plans — the write path
#
# Added by audit round 4a (2026-09-08), findings A3, A7, A20 and B2. The
# whole path was previously untested: deleting the verbatim ``out.write``,
# the guard, the flock, the temp-and-rename, or the ``--apply`` gate all left
# the suite green.
# ===========================================================================

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402

# recover_anchors puts scripts/ on sys.path at import time, and imports the
# guard lazily inside apply_plans — so the stubs below have to be installed on
# the guard MODULE, not on a name bound into recover_anchors.
import importlib  # noqa: E402

_guard = importlib.import_module("_bulk_rewrite_guard")


def _record(rid: str, *, ref: str = "notes.md", **extra: object) -> dict:
    """A synthetic verified=false record with one recoverable file anchor."""
    rec: dict = {
        "id": rid,
        "content": "Survey grid squares are numbered from the south-west.",
        "category": "methodology",
        "verified": "false",
        "confidence": "medium",
        "anchors": [{"type": "file", "ref": ref}],
    }
    rec.update(extra)
    return rec


def _write_corpus(corpus: Path, lines: list[str]) -> None:
    """Write raw lines (each already newline-free) to the corpus."""
    corpus.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


class _Harness:
    """Stubs the guard, the commit, and PG; records the call order."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.locked: list[Path] = []
        self.renames: list[tuple[str, str]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_lock = _guard.lock_jsonl_for_rewrite

        @contextmanager
        def recording_lock(path):
            self.locked.append(Path(path))
            self.order.append("lock")
            with real_lock(path):
                yield
            self.order.append("unlock")

        real_replace = os.replace

        def recording_replace(src, dst, **kwargs):
            self.renames.append((str(src), str(dst)))
            return real_replace(src, dst, **kwargs)

        monkeypatch.setattr(
            _guard, "ensure_safe_to_rewrite",
            lambda reason: self.order.append("guard"),
        )
        monkeypatch.setattr(
            _guard, "release_lock", lambda: self.order.append("release"),
        )
        monkeypatch.setattr(_guard, "lock_jsonl_for_rewrite", recording_lock)
        monkeypatch.setattr(
            ra, "_git_commit",
            lambda *a, **k: self.order.append("commit"),
        )
        monkeypatch.setattr(
            ra, "_update_postgres", lambda plans: self.order.append("pg"),
        )
        monkeypatch.setattr(os, "replace", recording_replace)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    """Install the recording stubs for one test."""
    h = _Harness()
    h.install(monkeypatch)
    return h


def _plan_for(rec: dict) -> dict:
    """Build a real plan for ``rec`` via the production planner."""
    plan = ra.plan_record(
        rec, _const("false"), lambda ref: "wiki/notes.md", _const("true"),
    )
    assert plan is not None
    return plan


class TestApplyPlans:
    """The corpus rewrite: what is written, and under what protection."""

    def test_unplanned_lines_are_written_verbatim(
        self, tmp_path: Path, harness: _Harness,
    ) -> None:
        """Records with no plan survive byte-identically.

        Kills the B2 mutation that deletes the ``else: out.write(line)``
        branch, which would keep only the modified records.
        """
        corpus = tmp_path / "memories.jsonl"
        planned = _record("2031-05-01-aaaabbbbcccc")
        bystander = json.dumps(
            {"id": "2031-05-02-ddddeeeeffff", "content": "Untouched."}
        )
        _write_corpus(corpus, [json.dumps(planned), bystander])

        ra.apply_plans([_plan_for(planned)], corpus, do_postgres=False)

        lines = corpus.read_text(encoding="utf-8").split("\n")[:-1]
        assert len(lines) == 2
        assert lines[1] == bystander, "an unplanned line must be verbatim"

    def test_record_edited_since_planning_is_not_reverted(
        self, tmp_path: Path, harness: _Harness,
    ) -> None:
        """A /forget landing between plan and apply survives.

        Kills the A3 mutation that writes ``plan["record"]`` unconditionally:
        that reverts ``is_active`` and drops the editor's revision entry.
        """
        corpus = tmp_path / "memories.jsonl"
        original = _record("2031-05-01-aaaabbbbcccc")
        plan = _plan_for(original)
        # The edit lands after planning, before the lock.
        edited = dict(original)
        edited["is_active"] = False
        edited["revisions"] = [{"revised_at": "2031-05-01T10:00:00+00:00",
                                "action": "forget", "reason": "superseded"}]
        _write_corpus(corpus, [json.dumps(edited)])

        ra.apply_plans([plan], corpus, do_postgres=False)

        written = json.loads(corpus.read_text(encoding="utf-8").strip())
        assert written == edited, "the live edit must win over a stale plan"
        assert "commit" not in harness.order, "nothing applied, nothing to commit"

    def test_unedited_record_is_corrected_and_stamped(
        self, tmp_path: Path, harness: _Harness,
    ) -> None:
        """An untouched record gets the corrected ref, verified, and revision.

        Kills the B12 mutations: writing the stale ``verified`` field, and
        overwriting ``revisions`` instead of appending to it.
        """
        corpus = tmp_path / "memories.jsonl"
        rec = _record(
            "2031-05-01-aaaabbbbcccc",
            revisions=[{"revised_at": "2031-04-30T08:00:00+00:00",
                        "action": "update", "reason": "content corrected"}],
        )
        _write_corpus(corpus, [json.dumps(rec)])

        ra.apply_plans([_plan_for(rec)], corpus, do_postgres=False)

        written = json.loads(corpus.read_text(encoding="utf-8").strip())
        assert written["anchors"][0]["ref"] == "wiki/notes.md"
        assert written["verified"] == "true"
        assert len(written["revisions"]) == 2, "the earlier revision must survive"
        assert written["revisions"][0]["action"] == "update"
        assert written["revisions"][1]["action"].startswith("anchor-recover")

    def test_malformed_line_is_preserved_not_fatal(
        self, tmp_path: Path, harness: _Harness,
    ) -> None:
        """One bad line neither aborts the run nor orphans the temp file.

        Kills the A7 mutation that drops the ``json.JSONDecodeError`` guard:
        that raises mid-write, leaving ``memories.jsonl.tmp`` behind.
        """
        corpus = tmp_path / "memories.jsonl"
        rec = _record("2031-05-01-aaaabbbbcccc")
        _write_corpus(corpus, ["{not json at all", json.dumps(rec)])

        ra.apply_plans([_plan_for(rec)], corpus, do_postgres=False)

        lines = corpus.read_text(encoding="utf-8").split("\n")[:-1]
        assert lines[0] == "{not json at all"
        assert not (tmp_path / "memories.jsonl.tmp").exists()

    def test_guard_lock_and_atomic_rename_are_wired(
        self, tmp_path: Path, harness: _Harness,
    ) -> None:
        """The guard, the flock, and the temp-and-rename all run.

        Kills the B2 mutations that drop ``ensure_safe_to_rewrite``, swap the
        flock for a nullcontext, or write the corpus directly.
        """
        corpus = tmp_path / "memories.jsonl"
        rec = _record("2031-05-01-aaaabbbbcccc")
        _write_corpus(corpus, [json.dumps(rec)])

        ra.apply_plans([_plan_for(rec)], corpus, do_postgres=False)

        assert harness.order[0] == "guard"
        assert "lock" in harness.order
        assert harness.locked == [corpus]
        assert harness.renames == [
            (str(corpus.with_suffix(".jsonl.tmp")), str(corpus))
        ]

    def test_commit_happens_inside_the_guard_lock(
        self, tmp_path: Path, harness: _Harness,
    ) -> None:
        """The commit must precede release_lock.

        Kills the A20 mutation that moves ``_git_commit`` below
        ``release_lock``: a SessionStart daily-sync could then acquire the
        lock, see the shrunk corpus, and commit it without the
        ``Rewrite-Class: bulk`` trailer.
        """
        corpus = tmp_path / "memories.jsonl"
        rec = _record("2031-05-01-aaaabbbbcccc")
        _write_corpus(corpus, [json.dumps(rec)])

        ra.apply_plans([_plan_for(rec)], corpus, do_postgres=False)

        assert harness.order.index("commit") < harness.order.index("release")



    def test_an_abort_mid_write_leaves_no_temp_file(
        self, tmp_path: Path, harness: _Harness,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failure part-way through must not orphan memories.jsonl.tmp.

        Kills the mutation that drops ``tmp.unlink(missing_ok=True)`` from
        the abort path: the next run would inherit a stale half-file beside
        the canonical, and the run after that would silently rename it over
        the corpus. Round 4a-2 low finding.
        """
        corpus = tmp_path / "memories.jsonl"
        rec = _record("2031-05-01-aaaabbbbcccc")
        _write_corpus(corpus, [json.dumps(rec)])
        before = corpus.read_bytes()

        def explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("disk full part-way through the rewrite")

        monkeypatch.setattr(ra, "add_revision", explode)

        with pytest.raises(RuntimeError, match="disk full"):
            ra.apply_plans([_plan_for(rec)], corpus, do_postgres=False)

        assert not corpus.with_suffix(".jsonl.tmp").exists(), (
            "an aborted rewrite left its temp file behind")
        assert corpus.read_bytes() == before, "the corpus must be untouched"
        assert "commit" not in harness.order


class TestApplyGate:
    """``--apply`` is the only path that may mutate anything."""

    def test_dry_run_writes_nothing_and_does_not_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without --apply, main() reports and returns.

        Kills the B2 mutation that deletes ``if not args.apply: return 0``.
        """
        corpus = tmp_path / "memories.jsonl"
        rec = _record("2031-05-01-aaaabbbbcccc")
        _write_corpus(corpus, [json.dumps(rec)])
        before = corpus.read_bytes()
        called: list[str] = []

        monkeypatch.setattr(ra, "CORPUS", corpus)
        monkeypatch.setattr(ra.ta, "broad_repo_set", lambda: [tmp_path])
        monkeypatch.setattr(ra, "build_plans",
                            lambda corpus_path, repos, **kw: [_plan_for(rec)])
        monkeypatch.setattr(ra, "apply_plans",
                            lambda *a, **k: called.append("apply"))

        assert ra.main([]) == 0
        assert corpus.read_bytes() == before
        assert called == []

        assert ra.main(["--apply"]) == 0
        assert called == ["apply"]


class TestBuildPlans:
    """Which records the planner selects, and which refs it will rewrite."""

    def test_selects_only_verified_false_anchored_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """verified=true and unanchored records are skipped.

        Kills the B13 mutation that drops the ``verified == "false"`` filter.
        """
        corpus = tmp_path / "memories.jsonl"
        _write_corpus(corpus, [
            json.dumps(_record("2031-05-01-aaaabbbbcccc")),
            json.dumps(_record("2031-05-02-ddddeeeeffff", verified="true")),
            json.dumps({"id": "2031-05-03-999988887777",
                        "verified": "false", "anchors": []}),
            "{malformed",
        ])
        monkeypatch.setattr(ra.av, "verify_file", lambda ref, repos: "false")
        monkeypatch.setattr(ra.av, "verify_commit", lambda ref, repos: "false")
        monkeypatch.setattr(
            ra.av, "unique_suffix_match",
            lambda ref, cands, **kw: ra.av.SuffixMatch(
                "wiki/notes.md", "same-project"),
        )
        monkeypatch.setattr(ra.av, "verify_memory", lambda rec, repos: "true")
        monkeypatch.setattr(ra, "build_basename_index", lambda repos: {})

        plans = ra.build_plans(corpus, [])

        assert [p["id"] for p in plans] == ["2031-05-01-aaaabbbbcccc"]


class TestIsRelativeFileRef:
    """The ref shapes the recovery pass is allowed to touch."""

    def test_absolute_and_home_refs_are_rejected(self) -> None:
        """Kills the B13 mutation that accepts absolute refs."""
        assert ra._is_relative_file_ref({"type": "file", "ref": "wiki/a.md"})
        assert not ra._is_relative_file_ref(
            {"type": "file", "ref": "/etc/hosts"})
        assert not ra._is_relative_file_ref(
            {"type": "file", "ref": "~/notes.md"})
        assert not ra._is_relative_file_ref({"type": "commit", "ref": "abc123"})
        assert not ra._is_relative_file_ref({"type": "file", "ref": "  "})


def test_a_ref_that_already_resolves_is_left_alone() -> None:
    """A resolving ref must not be "recovered" onto another file.

    Kills the B13 mutation that removes the ``resolve(...) == "false"`` gate:
    with a recover stub that always returns a path, every anchor would be
    rewritten.
    """
    rec = _record("2031-05-01-aaaabbbbcccc", ref="wiki/notes.md")
    plan = ra.plan_record(
        rec, _const("true"), lambda ref: "somewhere/else.md", _const("true"),
    )
    assert plan is None


# ============================================================================
# Recovery stays inside the memory's own project (finding AN2)
# ============================================================================


def _seed_project_repo(root: Path, name: str, relpath: str) -> Path:
    """Create a throwaway git repository *name* tracking one file *relpath*."""
    repo = root / name
    target = repo / relpath
    target.parent.mkdir(parents=True)
    target.write_text("# seeded\n", encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "PATH": os.environ.get("PATH", ""), "HOME": str(root),
    }
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "seed"], check=True, env=env,
    )
    return repo


def _false_record(project: str, ref: str) -> dict:
    """A verified=false anchored record attributed to *project*."""
    return {
        "id": "2031-07-04-aaaabbbbcccc",
        "category": "progress",
        "project": project,
        "verified": "false",
        "confidence": "low",
        "anchors": [{"type": "file", "ref": ref}],
    }


class TestRecoveryIsScopedToTheMemorysProject:
    """A dead ref must not recover onto a same-named file elsewhere.

    Two throwaway repositories, each tracking a file whose path ends
    ``util.py``. A memory written in project A carries the dead ref
    ``util.py``. Before the fix, the basename index pooled both repositories
    into one namespace and the match in B was "unique", so the memory was
    re-anchored onto a file it was never about — and then verified true.

    The mutation these kill: dropping ``project_repos=`` from the
    ``unique_suffix_match`` call in ``build_plans`` (the union match in B is
    then written), and returning the cross-repo match without the
    ``allow_cross_repo`` gate.
    """

    def _corpus(self, tmp_path: Path, record: dict) -> Path:
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return corpus

    def test_a_match_in_another_project_is_not_recovered(
        self, tmp_path, monkeypatch,
    ) -> None:
        repo_a = _seed_project_repo(tmp_path, "project-a", "src/other.py")
        repo_b = _seed_project_repo(tmp_path, "project-b", "pkg/src/util.py")
        monkeypatch.setattr(ra.av, "verify_file", lambda ref, repos: "false")
        monkeypatch.setattr(ra.av, "verify_memory", lambda rec, repos: "false")
        record = _false_record(
            ra.project_id.encode_project_id(str(repo_a)), "src/util.py",
        )
        plans = ra.build_plans(
            self._corpus(tmp_path, record), [repo_a, repo_b],
        )
        assert plans == [], "a same-named file in project B is not a recovery"

    def test_a_match_inside_the_memorys_own_project_is_recovered(
        self, tmp_path, monkeypatch,
    ) -> None:
        """The control: the same shape, with the file in the right project."""
        repo_a = _seed_project_repo(tmp_path, "project-a", "wiki/util.py")
        _seed_project_repo(tmp_path, "project-b", "pkg/other.py")
        repos = [repo_a, tmp_path / "project-b"]
        monkeypatch.setattr(ra.av, "verify_file", lambda ref, repos_: "false")
        monkeypatch.setattr(ra.av, "verify_memory", lambda rec, repos_: "true")
        record = _false_record(
            ra.project_id.encode_project_id(str(repo_a)), "util.py",
        )
        plans = ra.build_plans(self._corpus(tmp_path, record), repos)
        assert [p["ref_rewrites"] for p in plans] == [
            [("util.py", "wiki/util.py")]
        ]

    def test_the_cross_repo_flag_opens_the_union_back_up(
        self, tmp_path, monkeypatch,
    ) -> None:
        """An unattributed memory recovers only under --allow-cross-repo."""
        _seed_project_repo(tmp_path, "project-a", "src/other.py")
        _seed_project_repo(tmp_path, "project-b", "pkg/src/util.py")
        repos = [tmp_path / "project-a", tmp_path / "project-b"]
        monkeypatch.setattr(ra.av, "verify_file", lambda ref, repos_: "false")
        monkeypatch.setattr(ra.av, "verify_memory", lambda rec, repos_: "true")
        record = _false_record("", "src/util.py")
        corpus = self._corpus(tmp_path, record)
        assert ra.build_plans(corpus, repos) == []
        opened = ra.build_plans(corpus, repos, allow_cross_repo=True)
        assert [p["ref_rewrites"] for p in opened] == [
            [("src/util.py", "pkg/src/util.py")]
        ]


class TestProjectReposFor:
    """Mapping an encoded project id back onto discovered repositories."""

    def test_exact_and_subdirectory_projects_match(self, tmp_path) -> None:
        repo = tmp_path / "Code" / "widget"
        repo.mkdir(parents=True)
        encoded = ra.project_id.encode_project_id(str(repo))
        assert ra.project_repos_for(encoded, [repo]) == [repo]
        assert ra.project_repos_for(encoded + "-src", [repo]) == [repo]

    def test_the_innermost_repository_wins(self, tmp_path) -> None:
        """A nested checkout must not be attributed to its parent."""
        outer = tmp_path / "Code" / "widget"
        inner = outer / "vendor" / "thing"
        inner.mkdir(parents=True)
        encoded = ra.project_id.encode_project_id(str(inner))
        assert ra.project_repos_for(encoded, [outer, inner]) == [inner]

    def test_an_unknown_project_is_unattributed(self, tmp_path) -> None:
        repo = tmp_path / "Code" / "widget"
        repo.mkdir(parents=True)
        assert ra.project_repos_for("-home-someone-else", [repo]) is None
        assert ra.project_repos_for(None, [repo]) is None


class TestTheCrossRepoFlagDoesWhatItSays:
    """--allow-cross-repo was a no-op for an attributable memory (L3)."""

    def _fixture(self, tmp_path):
        """Project A holds no candidate; project B holds exactly one."""
        repo_a = _seed_project_repo(tmp_path, "project-a", "src/other.py")
        repo_b = _seed_project_repo(tmp_path, "project-b", "pkg/src/util.py")
        record = _false_record(
            ra.project_id.encode_project_id(str(repo_a)), "src/util.py",
        )
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return corpus, [repo_a, repo_b]

    def test_off_by_default_for_an_attributable_memory(
        self, tmp_path, monkeypatch,
    ) -> None:
        """The AN2 guarantee is unchanged: no silent cross-repo rewrite."""
        corpus, repos = self._fixture(tmp_path)
        monkeypatch.setattr(ra.av, "verify_file", lambda ref, r: "false")
        monkeypatch.setattr(ra.av, "verify_memory", lambda rec, r: "true")
        assert ra.build_plans(corpus, repos) == []

    def test_the_flag_reaches_a_memory_that_names_its_project(
        self, tmp_path, monkeypatch,
    ) -> None:
        """Kills the mutation dropping allow_union_fallback.

        Before this the scoped search returned None and never fell back, so
        the flag changed nothing for any memory carrying a project — which
        is most of them, and exactly the population an operator running
        --allow-cross-repo is trying to reach.
        """
        corpus, repos = self._fixture(tmp_path)
        monkeypatch.setattr(ra.av, "verify_file", lambda ref, r: "false")
        monkeypatch.setattr(ra.av, "verify_memory", lambda rec, r: "true")
        plans = ra.build_plans(corpus, repos, allow_cross_repo=True)
        assert [p["ref_rewrites"] for p in plans] == [
            [("src/util.py", "pkg/src/util.py")]
        ]

    def test_ambiguity_inside_the_project_is_not_widened(self) -> None:
        """Two candidates at home is not solved by looking further afield."""
        home = Path("/repo-a")
        tracked = [
            av_module.TrackedPath(str(home), "one/util.py"),
            av_module.TrackedPath(str(home), "two/util.py"),
            av_module.TrackedPath("/repo-b", "pkg/util.py"),
        ]
        assert av_module.unique_suffix_match(
            "util.py", tracked, project_repos=[home],
            allow_union_fallback=True,
        ) is None


class TestMainUsesGuardedDiscovery:
    """A degraded machine must not drive a corpus rewrite (finding L4)."""

    def test_an_empty_repo_set_refuses(
        self, tmp_path, monkeypatch, capsys,
    ) -> None:
        """Kills the mutation calling project_id.repo_set() directly.

        With no repositories every anchor resolves nowhere, and this script
        writes the recomputed verdict and confidence back — so an unguarded
        run marks the corpus pending/medium wholesale.
        """
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(
            json.dumps(_record("2031-05-01-aaaabbbbcccc")) + "\n",
            encoding="utf-8",
        )
        before = corpus.read_bytes()
        monkeypatch.setattr(ra, "CORPUS", corpus)

        def _raise() -> list:
            raise ra.ta.RepoSetUnavailable("no git repositories discovered")

        monkeypatch.setattr(ra.ta, "broad_repo_set", _raise)
        assert ra.main([]) == 2
        assert corpus.read_bytes() == before
        assert "refusing to plan" in capsys.readouterr().err


def test_the_recovery_memo_is_keyed_on_the_project_too(
    tmp_path, monkeypatch,
) -> None:
    """Two projects, one dead ref, different answers (memo-key mutation).

    Project A holds ``wiki/util.py``; project B holds nothing that matches.
    Both memories carry the bare ref ``util.py``. With the memo keyed on the
    ref alone, whichever record is planned first decides for both — so B
    either recovers onto A's file or A stops recovering at all.
    """
    repo_a = _seed_project_repo(tmp_path, "project-a", "wiki/util.py")
    repo_b = _seed_project_repo(tmp_path, "project-b", "pkg/other.py")
    repos = [repo_a, repo_b]
    records = [
        _false_record(ra.project_id.encode_project_id(str(repo_a)), "util.py"),
        _false_record(ra.project_id.encode_project_id(str(repo_b)), "util.py"),
    ]
    records[1]["id"] = "2031-07-05-ddddeeeeffff"
    corpus = tmp_path / "memories.jsonl"
    corpus.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8",
    )
    monkeypatch.setattr(ra.av, "verify_file", lambda ref, r: "false")
    monkeypatch.setattr(ra.av, "verify_memory", lambda rec, r: "true")

    plans = ra.build_plans(corpus, repos)
    assert [p["id"] for p in plans] == ["2031-07-04-aaaabbbbcccc"]
    assert plans[0]["ref_rewrites"] == [("util.py", "wiki/util.py")]
