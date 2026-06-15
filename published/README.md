# Published

Curation layer for external readers. Everything in the parent `personal-assistant/`
repository is already public — this directory identifies the subset that is
**polished, sanitised, and recommended for external reuse** (by other researchers,
students, collaborators, or anyone finding the repo).

## Convention — intentional, sanitised copies only

Every entry here is a **deliberately copied and sanitised artefact**. The
canonical working version stays where it lives (`skills/`, `agents/`, or the
private `data/notes/grimoire/`); the `published/` entry is a frozen, reviewed,
privacy-checked **copy**.

> **Why not symlinks?** An earlier version of this directory symlinked live
> skills and agents. That approach was retired on **2026-06-15**: a live symlink
> republishes whatever happens to be in the working file, so hardcoded paths,
> internal instrumentation, persona lines, infra coupling — and, in one teaching
> case, potentially identifiable material — were exposed with no review gate.
> Copies force an explicit sanitisation step before anything is recommended for
> reuse.

The trade-off is that copies can **drift** from their sources. The monthly
`/retro` includes a *review published artefacts* step that re-checks each copy
against its source and re-sanitises or refreshes it as needed.

```text
skills/review-implementation/SKILL.md          (canonical working version)
    │
    ▼ deliberate copy + sanitise when polished
published/skills/review-implementation.md       (public — frozen, reviewed copy)
```

## Directory layout

| Directory | Contents |
|-----------|----------|
| `prompts/` | Promoted, sanitised grimoire prompts |
| `skills/`  | Sanitised copies of skills recommended for external reuse |
| `agents/`  | Sanitised copies of agent definitions recommended for external reuse |

## What's NOT here (and why)

- **Most commands** — tightly coupled to the task/memory system (`/focus`,
  `/standup`, `/recall`, etc.). Externalising would require a rewrite, not a copy.
- **Hooks and scripts** — infrastructure for this specific system.
- **Global CLAUDE.md components and settings** — personal/machine configuration.
- **Anything not yet sanitised** — e.g. the `lit-scout` / `prior-art-scout`
  agent pairs (hardcoded paths + instrumentation) and several skills, pending a
  deliberate stripping pass before they can be copied here.

## Adding or updating an entry

1. Copy the polished source file into the matching `published/` subdirectory.
2. **Sanitise**: strip absolute / `~` paths, machine names, client / project /
   collaborator names, internal instrumentation, unshipped plans, and anything
   identifying a third party.
3. Verify it reads standalone, then commit.
4. At each `/retro`, re-check existing copies against their sources for drift and
   refresh as needed.
