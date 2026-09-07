from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
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
id = "codex-map-reader-llm-phase2"
agent = "codex"
repository = "~/Code/map-reader-llm"
lane_path = "~/worktrees/map-reader-llm/sol-phase2-codex-entry"
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

    def test_live_policy_admits_no_clones_yet(self) -> None:
        self.assertEqual(self.policy.get("admitted_clones", []), [])

    def test_well_formed_admission_is_accepted(self) -> None:
        policy = self.load_with(self.ADMISSION)
        self.assertEqual(len(policy["admitted_clones"]), 1)

    def test_malformed_admissions_are_rejected(self) -> None:
        variants = {
            "ssh remote": self.ADMISSION.replace(
                "https://github.com/saross/", "git@github.com:saross/"),
            "wrong lane prefix": self.ADMISSION.replace("/sol-phase2", "/claude-phase2"),
            "lane under wrong repo": self.ADMISSION.replace(
                "worktrees/map-reader-llm/", "worktrees/other-repo/"),
            "lane without workstream": self.ADMISSION.replace(
                "sol-phase2-codex-entry", "sol-"),
            "primary checkout as lane": self.ADMISSION.replace(
                "~/worktrees/map-reader-llm/sol-phase2-codex-entry", "~/Code/map-reader-llm"),
            "wrong namespace": self.ADMISSION.replace('"sol/*"', '"main"'),
            "unknown agent": self.ADMISSION.replace('agent = "codex"', 'agent = "astra"'),
            "home repository": self.ADMISSION.replace("~/Code/map-reader-llm", "~/gpt-hub"),
            "not admitted by shawn": self.ADMISSION.replace(
                'admitted_by = "shawn"', 'admitted_by = "codex"'),
            "unsupported clone mode": self.ADMISSION.replace(
                "full-single-branch", "blobless"),
            "wrong storage": self.ADMISSION.replace("independent-clone", "linked-worktree"),
            "missing field": self.ADMISSION.replace('admitted_on = "2026-09-07"\n', ""),
            "duplicate id": self.ADMISSION + self.ADMISSION.replace(
                "sol-phase2-codex-entry", "sol-second"),
            "duplicate lane": self.ADMISSION + self.ADMISSION.replace(
                "codex-map-reader-llm-phase2", "second-id"),
        }
        for label, text in variants.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.load_with(text)

    def test_glob_case_resolves_an_existing_backup_without_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / ".env.bak-20260824"
            backup.touch()
            case = {"path": f"{directory}/.env.bak-*"}
            self.assertEqual(verifier.resolve_case_path(case), backup)


if __name__ == "__main__":
    unittest.main()
