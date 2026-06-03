## Scratchpad — Full Reference

Claude's running learning log. Two layers:

- **Global scratchpad** — `~/personal-assistant/data/scratchpad.md`.
  Loaded every session. Generally-applicable rules, preferences, and
  patterns that apply across projects (API gate discipline, PR workflow,
  Sapphire-for-compute, planning discipline, etc.).
- **Per-project scratchpads** — `~/personal-assistant/data/scratchpads/<project-name>.md`.
  Loaded only when `Path(cwd).name` matches the file stem (e.g.,
  `map-reader-llm.md` loads when cwd is `~/Code/map-reader-llm/`).
  Project-specific identifiers, config values, experiment-specific
  conventions, and the like. This keeps specifics out of every
  session's context — critical for Opus-class models, which confabulate by
  welding together plausible fragments from pre-loaded context.

### Deciding which layer

Ask: *would this rule make sense in a completely different project?*
If yes → global. If it names a specific file path, config key, model
version, threshold number, or project-specific workflow → per-project.

When in doubt, prefer per-project. Global is for principles.

### When to Write

- **Constraint articulated**: Shawn corrects your output, approach, or
  assumption. Record the *rule or principle* he articulated, not just
  the error. Highest-value entries — they compound across sessions.
  Frame as "the rule is X" not "I got Y wrong."
- **Preference discovered**: Something about how Shawn works that isn't
  in CLAUDE.md yet.
- **Approach succeeded or failed**: A technique that produced notably
  good or poor results.
- **Pattern noticed**: Recurring observation about session dynamics.

### When NOT to Write

- Things that belong in CLAUDE.md (permanent system rules).
- Things already captured by `/remember` or extraction (project
  decisions, research methodology, commitments).
- Routine exchanges or acknowledgements.
- Entries longer than 2–3 lines — the scratchpad is terse.

### Format

Append under the relevant section heading. Each entry is a dated bullet:

```text
- 2026-03-14: Shawn corrected X to Y — reason Z
```

### Maintenance

Reviewed at every monthly `/retro` (both layers — global and any
per-project scratchpads touched that month). At each review:

- **Promote** → durable principle → memory via `/remember`
- **Graduate** → permanent rule → propose addition to CLAUDE.md
- **Consolidate** → merge related entries into one sharper entry
- **Prune** → entries older than 30 days get explicit review for
  stale identifiers / obsolete workflows; remove if superseded
- **Keep** → recent and actively useful; leave it

Age threshold: **30 days**. Entries older than 30 days MUST be
reviewed at the next retro (classification above). Younger entries
can be left alone.

Target lengths: global ≤80 lines, per-project ≤60 lines.

### Anti-confabulation caveat

Scratchpad entries are **pointers, not authorities**. A scratchpad
entry claiming a specific number, file path, threshold, or config
value is frozen at write-time. Before citing any such specific
to Shawn, re-read the actual source file. Do not quote scratchpad
specifics as current fact.
