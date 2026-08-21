# `.env` across machines — what is shared, what is not

**Established 2026-08-22** by comparing `~/personal-assistant/.env` on
zbook-ubuntu and amd-tower-ubuntu. Both files then carried **24 keys**.

**Read this before syncing `.env` between machines.** Three keys hold
deliberately different values on each host, and a straight copy in
either direction destroys them.

## The comparison method

`.env` is gitignored on purpose, so the two copies drift silently and
nothing detects it. To compare without reading secrets into a session,
fingerprint each assignment as `KEY <salted-sha256-prefix> <length>` and
diff the fingerprints. The script is
`scratchpad/env-fingerprint.sh` in the 2026-08-22 session; it is short
enough to rewrite from this description, and the salt only needs to be
identical across the two hosts in a single comparison.

Run it on both hosts, then compare three things separately: keys only on
A, keys only on B, and keys on both whose hashes differ. **The third
category is the one that matters** and the one a naive `scp` silently
destroys.

## Three keys differ by design — never copy these

| Key | Shape |
| --- | --- |
| `ANTHROPIC_API_KEY` | 108 chars on both, different values |
| `RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID` | 32 chars on both, different values |
| `RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY` | 64 chars on both, different values |

Equal lengths with different values is the signature of **separately
issued per-machine credentials** rather than drift: two distinct
Anthropic keys, and two distinct Cloudflare R2 token pairs. That is good
practice — either machine can be revoked without touching the other — so
the divergence is a feature. **Shawn has not confirmed this reading**
(flagged to him 2026-08-22); if he ever says they should match, reissue
rather than copy, so one machine's compromise cannot silently become
both.

## Machine-scoped by naming convention

`OPENAI_API_KEY_MR_ZBOOK` and `OPENAI_API_KEY_PA_ZBOOK` exist only on
zbook; `OPENAI_API_KEY_MR_AMDT` and `OPENAI_API_KEY_PA_AMDT` only on
amd-tower. The `_ZBOOK` / `_AMDT` suffix says where the key belongs, so
absence is correct rather than a gap.

**Latent bug, unfixed as of 2026-08-22.**
`scripts/bulk-archive.py:1399` and `scripts/bake-off-metadata.py:718`
both read `OPENAI_API_KEY_PA_AMDT` unconditionally. **Those two scripts
therefore cannot run on zbook**, which has the equivalent credential
under `OPENAI_API_KEY_PA_ZBOOK`. Either resolve the suffix from the
hostname or fall back across both spellings. Left alone deliberately:
copying the `_AMDT` value onto zbook would paper over it whilst
duplicating a credential across machines, which is a posture decision
for Shawn, not a bug fix.

## Everything else should match

The remaining keys are machine-agnostic: the Zotero family, `OSF_API_KEY`,
`GEMINI_API_KEY`, `OPENALEX_API_KEY`, and
`GITHUB_API_PUBLIC_REPOS_TOKEN`. Five were out of step on 2026-08-22 and
were synced by piping the matching lines host to host over SSH, so no
value passed through a model context:

- to amd-tower: `OPENALEX_API_KEY` (registered by Shawn that day),
  `ZOTERO_API_KEY_TRAP`, `ZOTERO_TRAP_COLLECTION`, `ZOTERO_TRAP_GROUP_ID`
- to zbook: `GITHUB_API_PUBLIC_REPOS_TOKEN`

`GITHUB_API_PUBLIC_REPOS_TOKEN` has **no consumer anywhere in this
repository**. It is carried on both machines because it is harmless to
hold and expensive to rediscover, not because anything reads it.

## Two operational notes

- **Check the file mode.** amd-tower's `.env` was `664` until 2026-08-22,
  meaning group and others could read every credential in it. Both are
  now `600`. Check this whenever a `.env` is created or restored; a
  restore from backup can quietly reinstate the old mode.
- **Back up before appending, and confirm the trailing newline.** A file
  not ending in `\n` will have its last assignment corrupted by an
  append. Both files were verified before the 2026-08-22 sync, and
  timestamped `.env.bak-YYYYmmdd-HHMMSS` copies were taken on each host
  first.
