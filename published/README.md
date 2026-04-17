# Published

Curation layer for external readers. Everything in the parent `personal-assistant/`
repository is already public — this directory identifies the subset that is
**polished and recommended for external reuse** (by other researchers, students,
collaborators, or anyone finding the repo).

## Conventions

Two patterns are in use, depending on origin:

### Pattern A — Public-origin content (symlinks)

For content whose canonical version already lives elsewhere in this repo
(skills, commands, agents), `published/` entries are **symlinks** pointing
to the canonical source. No drift between the working version and the
published version.

```text
published/skills/improve-prompt → ../../skills/improve-prompt/
published/agents/lit-scout.md   → ../../agents/lit-scout.md
```

Including a symlink here is a curation signal: "this one is polished enough
that I'd actively point an external reader to it."

### Pattern B — Private-origin content (copies)

For content whose canonical version lives in the private `data/` submodule
(currently just grimoire prompts), `published/` entries are **canonical copies
promoted from private scratch work**. The original stays private; only the
polished version is made public.

```text
data/notes/grimoire/some-prompt.md   (private — canonical working copy)
    │
    ▼ manual copy when polished
published/prompts/some-prompt.md     (public — canonical published copy)
```

## Directory layout

| Directory | Pattern | Contents |
|-----------|---------|----------|
| `prompts/` | B — copies | Promoted grimoire entries |
| `skills/` | A — symlinks | Skills recommended for external reuse |
| `agents/` | A — symlinks | Subagent definitions recommended for external reuse |

## What's NOT here (and why)

- **Commands** — most are tightly coupled to the task system (`/focus`,
  `/standup`, `/done`, etc.). Externalising would require a rewrite, not
  a symlink. May revisit.
- **Hooks and scripts** — infrastructure for this specific system, not
  generically reusable.
- **Global CLAUDE.md components** — personal configuration.
- **Settings** — machine/user configuration.

## Adding new entries

**For a skill or agent:** create a symlink here pointing to the canonical
file or directory.

```bash
# Skill (directory)
ln -s ../../skills/my-skill published/skills/my-skill

# Agent (file)
ln -s ../../agents/my-agent.md published/agents/my-agent.md
```

**For a prompt:** copy the polished grimoire entry from `data/notes/grimoire/`
into `published/prompts/`, strip any private context, and verify it reads
well standalone.
