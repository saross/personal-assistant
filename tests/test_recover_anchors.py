"""
Tests for scripts/recover_anchors.py — the item-21b corpus-correction planner.

Covers the pure planning logic (``plan_record`` with injected resolvers, and
``add_revision``). The I/O paths (corpus walk, bulk-rewrite guard, git commit,
postgres update) are not exercised here — they reuse already-tested modules.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load(name, rel):
    path = Path(__file__).parent.parent / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ra = _load("recover_anchors", "scripts/recover_anchors.py")


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
