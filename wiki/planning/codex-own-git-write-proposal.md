# Proposal — grant Codex write to its own repository's Git directory

**Status:** proposed by Sol, verified and patched by Claude 2026-08-25.
Awaiting application by Sol or Shawn — `~/gpt-hub/` is Sol-owned and
write-denied to Claude, so this is the proposal route, not an applied change.

## Problem

`git add` in `gpt-hub` fails read-only for Sol, under both normal and
escalated permissions. The underlying filesystem permissions are `rw`; the
`personal-trusted` profile extends `:workspace`, and that preset marks `.git`
inside a writable workspace root read-only so an agent cannot rewrite hooks or
history. It is not a lock-file problem.

## Verification of the diagnosis

- **Confirmed:** the OpenAI Codex configuration reference states that a named
  profile's `permissions.<name>.filesystem.<path-or-glob>` accepts
  `"read" | "write" | "deny"`, so an exact absolute path may be granted write.
  <https://learn.chatgpt.com/docs/config-file/config-reference>
- **Confirmed:** `.git` and `.codex` inside writable roots are automatically
  read-only sub-paths in workspace-write mode. This is deliberate sandbox
  policy, not a bug.
- **Not resolved by this change — see "Known limitation" below.**

## Change

Derive the grant from `ownership.toml` rather than hand-editing
`~/.codex/config.toml`. `render_ownership_config.py` gains
`owned_git_metadata()`, which reads the agent's declared `home_repository`
and grants that repository's whole `.git` directory. The whole directory,
not just the index: a commit writes locks, objects, refs, and logs.

Rendered output changes by exactly one line in
`[permissions.personal-trusted.filesystem]`:

```toml
"/home/shawn/gpt-hub/.git" = "write"
```

`personal-assistant/.git` stays read-only by inheritance from `":root" = "read"`,
`restricted-input` is untouched, and arbitrary repositories are unaffected.

## Ownership assessment

**No `ownership.toml` loosening PR is required, and Claude concurs.** `gpt-hub`
is Sol's `home_repository` under the active policy, and staging and committing
are writes to a surface Sol already owns. The change makes the machine profile
match the policy rather than extending it. It touches no Claude-owned path.

## Known limitation — this probably does not fix the reported symptom

Sol's own integration record
(`gpt-hub/integration-records/2026-08-25-agent-mail.md`) locates the failure in
**linked worktrees**, not the main checkout: "its workspace roots do not grant
the parent repositories' linked-worktree Git metadata. Exact-path staging
therefore fails read-only."

Two consequences:

1. `~/worktrees/gpt-hub/sol-agent-mail-codex` keeps its metadata at
   `/home/shawn/gpt-hub/.git/worktrees/sol-agent-mail-codex`, which **is**
   inside the grant. But open upstream issue
   [openai/codex#27418](https://github.com/openai/codex/issues/27418) reports
   that the Linux sandbox "remounts the resolved worktree gitdir read-only even
   when the Codex permission profile explicitly grants write access to the
   repository `.git` directory". Reported against codex-cli 0.139.0 and still
   open; this machine runs **0.149.1**. So the grant may not take effect there.
2. `~/worktrees/personal-assistant/sol-agent-mail-policy` keeps its metadata at
   `/home/shawn/personal-assistant/.git/worktrees/...`, which is **outside** the
   grant by design — that is Claude's repository, and granting it would be a
   real ownership loosening needing Shawn's sign-off. This half remains the
   "separate adjudication" Sol's record already flagged.

**Test order therefore matters:** verify `git add` in `~/gpt-hub` first (this
should work), then in `~/worktrees/gpt-hub/sol-agent-mail-codex` (this is the
one at risk from #27418). If the worktree case still fails, the fix is not the
profile — it is upstream, and the fallback options Sol already named stand: an
isolated clone, or a mediated Git operation that enforces the active worktree,
branch, and staged-path census.

## Testing already done

Applied to a scratch copy of the renderer, not to `gpt-hub`:

- the existing renderer suite plus two new tests pass (15 total);
- rendered output diffs by exactly the one line above;
- output still parses as TOML, with `gpt-hub/.git = write`,
  `personal-assistant/.git` absent, and the path absent from
  `restricted-input`;
- `git -C ~/gpt-hub apply --check` on the patch below reports clean.

## Patch

Apply from the `gpt-hub` root with `git apply`:

```diff
--- a/config/render_ownership_config.py
+++ b/config/render_ownership_config.py
@@ -132,6 +132,28 @@
     raise ValueError(f"ownership policy has no agent entry for {agent}")
 
 
+def owned_git_metadata(policy: dict, agent: str = "codex") -> list[Path]:
+    """Return the agent's own repository Git directory, which needs an explicit grant.
+
+    The `:workspace` preset this profile extends marks `.git` inside a writable
+    workspace root read-only, so staging and committing fail even in a
+    repository the agent owns outright. The grant is derived from the agent's
+    declared `home_repository`, so it tracks policy rather than a hard-coded
+    path, and it covers the whole Git directory: a commit writes locks,
+    objects, refs, and logs, not only the index. No other repository is
+    touched — in particular the other agent's `.git` stays read-only.
+    """
+    for entry in policy.get("agents", []):
+        if entry.get("id") != agent:
+            continue
+        home = Path(os.path.expandvars(os.path.expanduser(entry["home_repository"])))
+        if not home.is_absolute():
+            raise ValueError("home repository must be absolute after expansion")
+        git_dir = home / ".git"
+        return [git_dir] if git_dir.is_dir() else []
+    raise ValueError(f"ownership policy has no agent entry for {agent}")
+
+
 def protected_paths(policy: dict) -> tuple[list[Path], list[str]]:
     absolute: set[Path] = set()
     workspace_relative: set[str] = set()
@@ -211,6 +233,9 @@
     absolute_rules = {
         path.as_posix(): "write" for path in additional_owned_write_roots(policy)
     }
+    absolute_rules.update(
+        {path.as_posix(): "write" for path in owned_git_metadata(policy)}
+    )
     absolute_rules.update({path.as_posix(): "read" for path in absolute})
     absolute_rules.update({path: "deny" for path in denied_absolute})
     workspace_rules = {path: "read" for path in workspace_relative}
--- a/tests/test_render_ownership_config.py
+++ b/tests/test_render_ownership_config.py
@@ -94,6 +94,33 @@
         self.assertNotIn(codex_mail, restricted_filesystem)
         self.assertEqual(restricted_filesystem[":root"], "deny")
 
+    def test_trusted_profile_grants_write_to_the_agents_own_git_directory(self) -> None:
+        """The :workspace preset marks .git read-only; the owner needs it back.
+
+        Scoped to the agent's own home repository: the other agent's Git
+        directory, and every other repository on the machine, stay read-only,
+        and restricted-input is untouched.
+        """
+        import tomllib
+
+        own_git = Path.home() / "gpt-hub/.git"
+        if not own_git.is_dir():
+            self.skipTest(f"not a git checkout on this machine: {own_git}")
+        rendered = tomllib.loads(renderer.render_profile(self.policy, self.policy_path))
+        personal = rendered["permissions"]["personal-trusted"]["filesystem"]
+        restricted = rendered["permissions"]["restricted-input"]["filesystem"]
+        self.assertEqual(personal[str(own_git)], "write")
+        self.assertNotIn(str(Path.home() / "personal-assistant/.git"), personal)
+        self.assertNotIn(str(own_git), restricted)
+
+    def test_own_git_grant_fails_closed_without_an_agent_entry(self) -> None:
+        policy = dict(self.policy)
+        policy["agents"] = [
+            entry for entry in self.policy["agents"] if entry.get("id") != "codex"
+        ]
+        with self.assertRaisesRegex(ValueError, "no agent entry for codex"):
+            renderer.owned_git_metadata(policy)
+
     def test_owned_root_extension_fails_closed_on_unknown_semantics(self) -> None:
         policy = dict(self.policy)
         policy["semantics"] = dict(self.policy["semantics"])
```

## After applying

Re-render and reload the profile, then run the two `git add` tests in the
order given above and record the results in
`gpt-hub/integration-records/`.
