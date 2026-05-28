# /observe — Record an Observation in working-notes.md

Append a new Observation entry to the project's `working-notes.md` log via
the `obs-writer` agent. Auto-detects project format, picks the next free
Obs number with collision check, cross-references related entries, and
commits + pushes the change.

## Usage

```text
/observe [seed text]
/observe
/observe refs:[obs-numbers] [seed text]
```

## Arguments

- *(no arguments)* — Bare `/observe` invocation. Use when the assistant
  has just produced or discussed a paper-relevant finding and you want
  it logged. The assistant should compose the seed itself based on the
  immediate prior context, surface the proposed finding for your
  confirmation, and then dispatch obs-writer.
- `[seed text]` — A free-form description of the finding to record.
  May be a paragraph, a short note, or a pointer to a result file
  (e.g., "the Stage A pilot result + the methodology gotcha I caught").
  The assistant fleshes out the structure to match the project's Obs
  conventions before dispatching the agent.
- `refs:[obs-numbers]` — Optional explicit cross-reference list (e.g.,
  `refs:282,294,295`). The assistant should also infer cross-references
  from context; this flag forces specific ones to be cited.

## Behaviour

### With a seed text

1. **Locate** `working-notes.md` (try `wiki/working-notes.md` first, then
   `docs/notes/working-notes.md`, then the misplaced-legacy
   `docs/notes/reflections/working-notes.md`; ask if none found). This is the
   research-notes layer — never write Observations into the `reflections/`
   meta-research documents.
2. **Read** the most recent 2–3 Obs entries to establish the project's
   Obs format conventions (heading style, section structure, length).
3. **Compose a draft** Obs entry from the seed text:
   - Determine the headline (titled in the project's style)
   - Identify the substantive finding to record
   - Suggest 2–6 related Obs entries to cross-reference (search
     working-notes.md for thematically related entries)
   - Suggest a list of search terms for the "Findable later" section
4. **Surface the draft** — present the proposed Obs entry to the user
   for review BEFORE dispatching the agent. Specifically: title,
   headline numbers, cross-references, and any methodological caveats
   that should be flagged. Wait for confirmation or revision.
5. **Dispatch the obs-writer agent** with:
   - The confirmed seed/spec
   - Any specific cross-references the user added
   - Any structural overrides (sections to include/exclude)
6. **Report** the agent's output: commit hash, Obs number assigned,
   any deviations from the spec.

### With no seed text (bare `/observe`)

When the user invokes `/observe` with no arguments, they're asking the
assistant to compose an Obs entry from the immediate prior conversation:

1. **Identify** the most recent paper-relevant finding from the
   conversation context. Look for: a measured result, a methodological
   discovery, a flagged surprise, a generalisation claim — anything
   that would warrant an entry in the running observations register.
2. **Propose** the draft Obs (title, finding, suggested cross-refs)
   and surface for confirmation.
3. **Continue as above** once confirmed.

If the assistant can't identify a clear candidate finding from prior
context (e.g., the conversation has been routine task work without a
finding worth recording), say so explicitly and ask what to record.

## Inputs the obs-writer agent expects

When dispatching, provide:

- **The finding** to record — paragraph + tables/numbers if relevant
- **Cross-references** — list of related Obs numbers with one-line
  context per ref (e.g., "Obs 252 — text track ~4× lower buffer
  elasticity than image; this Obs corroborates")
- **Artefact paths** — scripts, data files, commit hashes that
  produced this Obs
- **Structural hints** (optional) — sections to include/exclude

The agent will choose the next free Obs number, match the project's
existing format, append at end-of-file, and commit + push as
`docs(reflection): Obs N — <headline>`.

## Anti-confabulation reminder

The obs-writer is bound to re-read source files before citing
specifics. If your seed mentions a number, file path, or commit hash,
the agent will verify it against the source and may correct it. The
final report flags any deviations.

## When to use this vs `/remember`

- **`/remember`** — captures a *memory* (context for the assistant in
  future sessions; lives in `memories/memories.jsonl`)
- **`/observe`** — captures an *Observation* (a paper-relevant finding
  in the project's running register; lives in
  `working-notes.md`)

The two are complementary. Memories are about how to collaborate;
Observations are about what we've discovered.

## Examples

```text
/observe
```

(Assistant proposes drafting an Obs from the immediate prior context
— e.g., the analysis result just discussed.)

```text
/observe text-MIN paired-permutation finding: BH p<0.001 vs T=0.7 at
R=50m, +0.0296 ΔF1, generalises Obs 284's diversity-dividend out-of-sample
```

(Assistant fleshes this out into a full Obs draft with cross-refs to
Obs 284 + the relevant pairwise-perm artefacts, surfaces for review,
then dispatches.)

```text
/observe refs:282,294 the failure-of-generalisation interpretation
of the GS-vs-55-map cap difference
```

(Assistant uses the explicit refs list and composes from the seed,
surfaces draft, dispatches.)
