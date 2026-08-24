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

    def test_glob_case_resolves_an_existing_backup_without_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / ".env.bak-20260824"
            backup.touch()
            case = {"path": f"{directory}/.env.bak-*"}
            self.assertEqual(verifier.resolve_case_path(case), backup)


if __name__ == "__main__":
    unittest.main()
