# `.env` across machines — what is shared, what is not

**Established 2026-08-22** by comparing `~/personal-assistant/.env` on
zbook-ubuntu and amd-tower-ubuntu. Both files carried **26 keys** at the
end of that day. Treat the count as a rough tripwire rather than an
inventory: it moves whenever a key is added, and the point of the
fingerprint comparison is that you never need a maintained list.

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
Anthropic keys, and two distinct Cloudflare R2 token pairs.

**Confirmed by Shawn 2026-08-22: for paid services he is deliberately
maintaining separate keys per machine.** Either machine can then be
revoked without touching the other. So the divergence is the intended
posture, and **the correct response to a mismatch is to reissue, never
to copy** — copying makes one machine's compromise silently become
both.

He also flagged that **the practice is not yet rigorous and wants an
audit of it** with Claude at some later point. Two things that audit
should probably settle, noted here so they are not rediscovered:
whether every paid service is actually covered (`GEMINI_API_KEY` and
`OSF_API_KEY` are currently *identical* across machines, so they are
either unpaid, or exceptions to the rule), and whether there is a record
anywhere of which key belongs to which machine at the provider end,
since a key you cannot attribute is a key you cannot confidently
revoke.

## Machine-scoped by naming convention

`OPENAI_API_KEY_MR_ZBOOK` and `OPENAI_API_KEY_PA_ZBOOK` exist only on
zbook; `OPENAI_API_KEY_MR_AMDT` and `OPENAI_API_KEY_PA_AMDT` only on
amd-tower. The `_ZBOOK` / `_AMDT` suffix says where the key belongs, so
absence is correct rather than a gap.

**Resolution is automatic since 2026-08-22.** `scripts/_openai_key.py`
derives the suffix from the hostname, so callers ask for a role and get
the right key wherever they run:

```python
from _openai_key import resolve_openai_key
api_key = resolve_openai_key("PA")
```

Order: an unsuffixed `OPENAI_API_KEY_<ROLE>` override wins outright;
otherwise the suffix comes from `OPENAI_KEY_SUFFIX` or the hostname;
otherwise it raises. Matching is case-insensitive and substring-based,
because amd-tower's actual hostname is the mixed-case
`AMD-tower-ubuntu` whilst the network doc writes it lowercase, and an
FQDN must resolve too.

**A new machine needs no code change** — set `OPENAI_KEY_SUFFIX` in its
environment, or add one row to `_HOST_SUFFIXES`.

This fixed a real bug: `bulk-archive.py` and `bake-off-metadata.py` both
read `OPENAI_API_KEY_PA_AMDT` unconditionally and so **could not run on
zbook at all**, despite zbook holding a usable credential. The error
compounded it by naming the variable it wanted rather than the one
present, sending the reader after a missing key instead of a mis-resolved
name. The new error names the suffixes the environment actually holds,
never a key value, and will not point a missing `PA` lookup at an `MR`
credential.

Verified live on both hosts 2026-08-22: zbook resolves `ZBOOK`,
amd-tower resolves `AMDT`, both roles present on both. 26 tests in
`tests/test_openai_key.py`, each against an injected dict so none can
touch a real key or depend on its host.

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

**Zotero keys are shared, not per-machine.** All of them held identical
values on both hosts before any syncing, so the Zotero family follows
the shared convention and a new one should be copied rather than
reissued. `ZOTERO_API_KEY_SUBSTACK_AI` and
`ZOTERO_SUBSTACK_AI_COLLECTIONS` were added on zbook and copied across
on 2026-08-22 on that basis.

**Naming convention worth preserving, because it makes shape errors
visible.** Across the Zotero family the name predicts the value's form
exactly: every `*_COLLECTION` holds an 8-character upper-alphanumeric
Zotero collection key, and every `*_GROUP_ID` or `*_LIBRARY_ID` holds a
6-or-7-digit number. A variable whose value does not match the form its
name implies is worth querying before it reaches a call site, where it
surfaces as a baffling API error rather than a naming problem. See the
open question about `ZOTERO_SUBSTACK_AI_COLLECTIONS` below.

**Resolved 2026-08-22, and worth keeping as the worked example.**
`ZOTERO_SUBSTACK_AI_COLLECTIONS` held a 7-digit all-numeric value: the
shape of a group ID, not of a collection key, despite the plural
`_COLLECTIONS` name. Shawn confirmed it is a group ID, and it was
**renamed to `ZOTERO_SUBSTACK_AI_GROUP_ID` on both machines**. The value
was untouched, confirmed by its fingerprint being identical before and
after on both hosts.

Two things this is a reminder of. **The mismatch was detectable from
the value's shape alone**, without reading it and before any code
touched it; a name that misdescribes its value otherwise surfaces at the
call site as a puzzling API error rather than as a naming problem.
**And a rename is a two-machine operation** for anything in the shared
set, exactly as an addition is. Both keys are now recorded in
`global-claude-md/zotero-reference.md`, where their scope is flagged as
unverified.

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
- **amd-tower cannot reach GitHub from a non-interactive SSH session.**
  `git fetch` there over `ssh -o BatchMode=yes` fails with
  `Permission denied (publickey)`, because the GitHub key is only
  available in Shawn's interactive session. Anything that must land on
  amd-tower needs either a pull he runs himself, or a direct file copy.
  Plan around it rather than rediscovering it.
