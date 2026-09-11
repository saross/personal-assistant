from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "verify_ownership_policy", ROOT / "verify-ownership-policy.py"
)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class OwnershipPolicyVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = verifier.load_policy(ROOT / "ownership.toml")

    def test_enforcement_layers_separate_os_from_tool_checklists(self) -> None:
        claude = verifier.cases_for(self.policy, "claude")
        codex = verifier.cases_for(self.policy, "codex")
        self.assertTrue(claude)
        self.assertTrue(codex)
        self.assertEqual({case["enforcement"] for case in claude}, {"tool-layer"})
        self.assertEqual({case["enforcement"] for case in codex}, {"os"})

    def test_owner_first_rule_covers_an_unregistered_future_agent(self) -> None:
        rule = next(
            rule for rule in self.policy["denials"] if rule["id"] == "codex-pa-harness"
        )
        self.assertFalse(verifier.rule_denies(rule, "claude", "write"))
        self.assertTrue(verifier.rule_denies(rule, "future-agent", "write"))

    ADMISSION = """
[[admitted_clones]]
id = "codex-map-reader-llm-fixture"
agent = "codex"
repository = "~/Code/map-reader-llm"
lane_path = "~/worktrees/map-reader-llm/sol-phase2-fixture-lane"
remote = "https://github.com/saross/map-reader-llm.git"
branch_namespace = "sol/*"
storage = "independent-clone"
clone_mode = "full-single-branch"
admitted_on = "2026-09-07"
admitted_by = "shawn"
"""

    def load_with(self, extra: str) -> dict:
        """Load the live policy text plus an appended admission block."""
        text = (ROOT / "ownership.toml").read_text() + extra
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "ownership.toml"
            candidate.write_text(text)
            return verifier.load_policy(candidate)

    def test_live_policy_admits_exactly_the_first_map_reader_lane(self) -> None:
        """The first real admission (2026-09-11): one lane, every field pinned.

        Until then this test asserted an empty list. A second admission must
        extend this assertion deliberately, with its own review.
        """
        self.assertEqual(self.policy.get("admitted_clones", []), [{
            "id": "codex-map-reader-llm-phase2",
            "agent": "codex",
            "repository": "~/Code/map-reader-llm",
            "lane_path": "~/worktrees/map-reader-llm/sol-phase2-codex-entry",
            "remote": "https://github.com/saross/map-reader-llm.git",
            "branch_namespace": "sol/*",
            "storage": "independent-clone",
            "clone_mode": "full-single-branch",
            "admitted_on": "2026-09-11",
            "admitted_by": "shawn",
        }])

    LIVE_ADMISSIONS = 1   # the fixture below is appended to the live policy

    def test_well_formed_admission_is_accepted(self) -> None:
        policy = self.load_with(self.ADMISSION)
        self.assertEqual(len(policy["admitted_clones"]), self.LIVE_ADMISSIONS + 1)

    def test_consistent_upper_case_spelling_is_admissible(self) -> None:
        policy = self.load_with(self.ADMISSION.replace("map-reader-llm", "Map-Reader-LLM"))
        self.assertEqual(len(policy["admitted_clones"]), self.LIVE_ADMISSIONS + 1)

    def test_trimmed_required_fields_list_is_rejected(self) -> None:
        base = (ROOT / "ownership.toml").read_text().replace(
            '"admitted_on", "admitted_by"]', '"admitted_on"]')
        self.assertNotEqual(base, (ROOT / "ownership.toml").read_text())
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "ownership.toml"
            candidate.write_text(base + self.ADMISSION)
            with self.assertRaisesRegex(ValueError, "omits fields"):
                verifier.load_policy(candidate)

    def test_canonical_basename_accepts_aliased_remote_spellings(self) -> None:
        """Consumers key on the canonical directory name; the remote may be spelt oddly."""
        for remote in ("saross/Map-Reader-LLM.git", "saross/map%2Dreader-llm.git",
                       "saross/map-reader-llm.GIT"):
            with self.subTest(remote=remote):
                policy = self.load_with(self.ADMISSION.replace("saross/map-reader-llm.git", remote))
                self.assertEqual(len(policy["admitted_clones"]), self.LIVE_ADMISSIONS + 1)

    def test_malformed_admissions_are_rejected(self) -> None:
        variants = {
            "ssh remote": self.ADMISSION.replace(
                "https://github.com/saross/", "git@github.com:saross/"),
            "wrong lane prefix": self.ADMISSION.replace("/sol-phase2", "/claude-phase2"),
            "lane under wrong repo": self.ADMISSION.replace(
                "worktrees/map-reader-llm/", "worktrees/other-repo/"),
            "lane without workstream": self.ADMISSION.replace(
                "sol-phase2-fixture-lane", "sol-"),
            "primary checkout as lane": self.ADMISSION.replace(
                "~/worktrees/map-reader-llm/sol-phase2-fixture-lane", "~/Code/map-reader-llm"),
            "wrong namespace": self.ADMISSION.replace('"sol/*"', '"main"'),
            "unknown agent": self.ADMISSION.replace('agent = "codex"', 'agent = "astra"'),
            "home repository": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/gpt-hub").replace(
                    "worktrees/map-reader-llm/", "worktrees/gpt-hub/").replace(
                        "saross/map-reader-llm.git", "saross/gpt-hub.git"),
            "traversal in a middle segment": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/Code/other/../map-reader-llm"),
            "http remote": self.ADMISSION.replace("https://github.com", "http://github.com"),
            "fragment in remote": self.ADMISSION.replace('.git"', '.git#frag"'),
            "non-canonical date": self.ADMISSION.replace('"2026-09-07"', '"20260907"'),
            "not admitted by shawn": self.ADMISSION.replace(
                'admitted_by = "shawn"', 'admitted_by = "codex"'),
            "unsupported clone mode": self.ADMISSION.replace(
                "full-single-branch", "blobless"),
            "wrong storage": self.ADMISSION.replace("independent-clone", "linked-worktree"),
            "missing field": self.ADMISSION.replace('admitted_on = "2026-09-07"\n', ""),
            "duplicate id": self.ADMISSION + self.ADMISSION.replace(
                "sol-phase2-fixture-lane", "sol-second"),
            "duplicate lane": self.ADMISSION + self.ADMISSION.replace(
                "codex-map-reader-llm-fixture", "second-id"),
        }
        for label, text in variants.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.load_with(text)

    def test_traversal_aliases_and_invalid_remote_identity_are_rejected(self) -> None:
        """Keep lexical aliases, unusable remotes, and invalid dates out of grants."""
        variants = {
            "parent traversal": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/Code/..").replace(
                    "worktrees/map-reader-llm/", "worktrees/../"),
            "home alias": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/Code/../gpt-hub").replace(
                    "worktrees/map-reader-llm/", "worktrees/gpt-hub/"),
            "duplicate alias": self.ADMISSION + self.ADMISSION.replace(
                "codex-map-reader-llm-fixture", "second-id").replace(
                    "worktrees/map-reader-llm/", "worktrees/map-reader-llm//"),
            "empty remote": self.ADMISSION.replace(
                "https://github.com/saross/map-reader-llm.git", "https://"),
            "credential remote": self.ADMISSION.replace(
                "https://github.com/", "https://fixture:fake@github.com/"),
            "query remote": self.ADMISSION.replace('.git"', '.git?fixture=fake"'),
            "non-date": self.ADMISSION.replace('admitted_on = "2026-09-07"',
                                               'admitted_on = "tomorrow"'),
            "wrong field type": self.ADMISSION.replace('agent = "codex"', 'agent = 3'),
            "basename differs from remote name": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/Code/mrl-mirror").replace(
                    "worktrees/map-reader-llm/", "worktrees/mrl-mirror/"),
            "basename case differs from lane directory": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/Code/Map-Reader-LLM"),
            "zero-width character in path": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/Code/map\u200b-reader-llm"),
            "percent-encoded slash in remote": self.ADMISSION.replace(
                "saross/map-reader-llm.git", "saross%2Fmap-reader-llm.git"),
            "percent-encoded alias in basename and remote": self.ADMISSION.replace(
                "~/Code/map-reader-llm", "~/Code/map%2Dreader-llm").replace(
                    "worktrees/map-reader-llm/", "worktrees/map%2Dreader-llm/").replace(
                        "saross/map-reader-llm.git", "saross/map%2Dreader-llm.git"),
        }
        for label, text in variants.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.load_with(text)

    def test_attempt_distinguishes_denial_from_success(self) -> None:
        """The enforcement probe: only EACCES/EPERM/EROFS count as denials."""
        import os
        import stat
        if os.geteuid() == 0:
            self.skipTest("root ignores file modes")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "protected.txt"
            target.write_text("x\n")
            target.chmod(stat.S_IRUSR)
            passed, detail, _ = verifier.attempt(
                {"path": str(target), "operation": "open-write"})
            self.assertTrue(passed, detail)
            target.chmod(stat.S_IRUSR | stat.S_IWUSR)
            passed, detail, _ = verifier.attempt(
                {"path": str(target), "operation": "open-write"})
            self.assertFalse(passed)
            self.assertIn("unexpectedly succeeded", detail)
            scratch = root / "created.txt"
            passed, detail, _ = verifier.attempt({"path": str(scratch), "operation": "create"})
            self.assertFalse(passed)
            self.assertFalse(scratch.exists())          # success path cleans up
            passed, detail, _ = verifier.attempt(
                {"path": str(root / "absent" / "x"), "operation": "create"})
            self.assertFalse(passed)
            self.assertIn("preflight failed", detail)   # missing parent is not a denial

    def test_rule_denies_respects_the_operation(self) -> None:
        rule = {"owner": "claude", "operations": ["write"]}
        self.assertTrue(verifier.rule_denies(rule, "codex", "write"))
        self.assertFalse(verifier.rule_denies(rule, "codex", "read"))
        self.assertFalse(verifier.rule_denies(rule, "claude", "write"))

    def test_schema_and_coverage_guards(self) -> None:
        text = (ROOT / "ownership.toml").read_text()
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "ownership.toml"
            candidate.write_text(text.replace("schema_version = 2", "schema_version = 3", 1))
            with self.assertRaisesRegex(ValueError, "schema"):
                verifier.load_policy(candidate)
            # Remove every case for one rule: that rule is then untested and the
            # loader must refuse. (The earlier version tolerated no error, so the
            # guard could be deleted with the test green — re-audit finding 9.)
            rule_id = tomllib.loads(text)["verification_cases"][0]["rule_id"]
            blocks = text.split("[[verification_cases]]")
            kept = [blocks[0]] + [b for b in blocks[1:] if f'rule_id = "{rule_id}"' not in b]
            self.assertLess(len(kept), len(blocks))
            candidate.write_text("[[verification_cases]]".join(kept))
            with self.assertRaisesRegex(ValueError, "verification"):
                verifier.load_policy(candidate)

    def test_a_trailing_encoded_separator_in_a_remote_is_rejected(self) -> None:
        """A trailing %2F survived the segment-count comparison (re-audit finding 11)."""
        verifier.validate_clone_remote("https://github.com/saross/personal-assistant.git")
        verifier.validate_clone_remote("https://github.com/saross/personal-assistant/")
        for remote in (
            "https://github.com/saross/personal-assistant%2F",
            "https://github.com/saross/personal-assistant%2F%2F",
            "https://github.com/%2Fsaross/personal-assistant",
            "https://github.com/saross%2Fevil/personal-assistant",
            "https://github.com/saross/%2E%2E/personal-assistant",
        ):
            with self.assertRaises(ValueError, msg=remote):
                verifier.validate_clone_remote(remote)

    def test_glob_case_resolves_an_existing_backup_without_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / ".env.bak-20260824"
            backup.touch()
            case = {"path": f"{directory}/.env.bak-*"}
            self.assertEqual(verifier.resolve_case_path(case), backup)


if __name__ == "__main__":
    unittest.main()
