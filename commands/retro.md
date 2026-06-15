# /retro — Monthly System Retrospective

Step back from the work and examine the system itself. Are the parameters right?
Is the system serving you, or are you serving the system?

## Usage

```text
/retro
/retro this-month
```

## Arguments

- *(no arguments)* — Retrospective for the previous calendar month
- `this-month` — Retrospective for the current month so far (with a note that it's partial)

## Behaviour

### 1. Determine Period

- Default: first day to last day of the previous calendar month
- `this-month`: first day of current month to today
- Display the month and year prominently in the output header

### 2. Gather Data

Read these sources:

| Source | What to extract |
|--------|----------------|
| `~/personal-assistant/reports/weekly/` | All weekly reviews from the month — scorecards, patterns, hard questions, **and Completions sections (the canonical closure record per week — aggregate these for the month-level closure roll-up)** |
| `~/personal-assistant/tasks/FOCUS.md` | Current state (for context) |
| `~/personal-assistant/tasks/SYSTEM.md` | Current parameters + adjustment history |
| `~/personal-assistant/memories/memories.jsonl` | Memories in period, especially: `system_evolution`, `system_friction`, `system_success`, `slip`, `completion`, `blocker_real`, `blocker_excuse` |
| `~/personal-assistant/standups/` | All standups from the month (for back-fill if a weekly review is missing — same closure-source-of-truth as weekly reviews use) |
| `~/personal-assistant/data/scratchpad.md` | Global scratchpad entries |
| `~/personal-assistant/data/scratchpads/*.md` | Per-project scratchpads (all files in this directory) |

**Note:** `tasks/done/YYYY-MM.md` retired 2026-05-24 as a data source. Closures
now live in weekly-review Completions sections. If a weekly review for any
ISO-week of the retro period is missing, fall back to scanning that week's
standup recaps directly (same reconciliation logic the weekly review uses —
see `/weekly-review` step 2).

### 3. Calculate System Metrics

| Metric | Calculation |
|--------|-------------|
| **Completion rate** | Items completed / items that entered focus during the month. Track "entered focus" from git log of FOCUS.md and weekly-review Completions sections. |
| **Focus churn** | Number of add/remove/swap operations on FOCUS.md (from git log). |
| **Avg days in focus** | Mean days-in-focus across slot-task closes in the month, drawn from weekly-review Completions sections. |
| **Longest-running focus item** | Max days in focus across completed AND current items. |
| **Inbox throughput** | Items added to inbox vs items processed (marked [x] or moved to focus). |
| **Commitment accuracy** | Count commitment memories with deadlines. How many were met vs missed? Cross-reference with completions and slip memories. |
| **Standup consistency** | Number of standups generated vs days in the month. |

### 4. Analyse Patterns

For each of these, cite specific evidence:

**System friction** (from `system_friction` memories):
- What keeps causing friction?
- Are the same friction points recurring?
- Did any friction points get resolved?

**System success** (from `system_success` memories):
- What's clearly working?
- What should be preserved or strengthened?

**Slip patterns** (from `slip` memories):
- What commitments weren't met?
- Is there a pattern (same project? same type of work? same time of week?)

**Weekly review trends:**
- Compare scorecard metrics across the month's weekly reviews
- Note improving or degrading trends
- Look for inflection points (week where something changed)

**Parameter overrides:**
- Were any overrides logged in SYSTEM.md?
- What does the override pattern suggest?

### 5. Generate Retrospective

The retro is **the canonical multi-week closure roll-up.** It aggregates the
month's weekly-review Completions sections into a single index — answering
"what did I get done last month?" without needing to open four weekly review
files. Closures roll-up sits between Metrics and What Worked.

```text
# System Retrospective — [Month] [Year]

## Closures Roll-Up

Aggregated from the month's weekly-review Completions sections.

### By project

| Project | Slot-task closes | Commitments met | Inbox-direct | Total |
|---------|-----------------:|----------------:|-------------:|------:|
| [project-a] | N | N | N | N |
| [project-b] | N | N | N | N |
| **Total** | **N** | **N** | **N** | **N** |

### Notable closures (slot-task level)

[One line per closure, week-tagged. E.g.,
"W20: Inscriptions preregistration lodged (research/inscriptions, 6 days in focus)"
"W21: RAC-TRAC talk delivered via Adela (research/inscriptions, 4 days)"
"W21: Final HUMN8031 class delivered (anu-digital-humanities, rotation slot)"
Sort by week, then by significance.]

### Weekly trajectory

| Week | Slot closes | Commitments | Inbox-direct | Hours |
|------|-----------:|------------:|------------:|------:|
| W20 | N | N | N | N.NN |
| W21 | N | N | N | N.NN |
| ... | | | | |

## Metrics

| Metric | Value | Assessment |
|--------|-------|------------|
| Completion rate | N/M (X%) | [good/concerning/poor] |
| Avg days in focus | N.N | [vs target — faster or slower?] |
| Focus churn | N changes | [stable/moderate/churning] |
| Longest in focus | N days ([item]) | [acceptable/concerning] |
| Inbox throughput | +N / -N | [keeping up/falling behind] |
| Commitment accuracy | N/M met (X%) | [reliable/mixed/unreliable] |
| Standup consistency | N/M days (X%) | [consistent/gaps] |

Assessment guidelines:
- Completion rate: >70% good, 40-70% concerning, <40% poor
- Avg days in focus: <7 good, 7-14 acceptable, >14 concerning
- Focus churn: <5 stable, 5-10 moderate, >10 churning
- Standup consistency: >80% consistent, 50-80% gaps, <50% absent

## What Worked

[Evidence-based. Cite specific system_success memories, completion data,
or weekly review patterns.
- "Single-threading on [item] led to completion in N days"
- "Standup pattern detection caught avoidance early on [date]"
- "Inbox processing stayed current all month"
Don't fabricate successes. If nothing stood out, say so.]

## What Didn't

[Evidence-based. Cite system_friction memories, slip patterns.
- "Focus churn of N suggests difficulty committing to priorities"
- "Paper deadline was mentioned in every standup but no completions recorded"
- "Inbox grew from N to M — processing cadence broke down"
Don't soften failures. The retro is for honesty.]

## Parameter Review

| Parameter | Current | Proposed | Evidence |
|-----------|---------|----------|----------|
| focus_limit | [N] | [same/change] | [why — cite data] |
| escalation_question_day | [N] | [same/change] | [why] |
| escalation_confront_day | [N] | [same/change] | [why] |
| escalation_abandon_day | [N] | [same/change] | [why] |
| standup_tone | [tone] | [same/change] | [why] |
| review_cadence | [cadence] | [same/change] | [why] |

Rules for proposals:
- Only propose changes backed by evidence from the month's data
- "No change needed" is a valid and valuable conclusion
- Small adjustments are better than big swings
- If a parameter was overridden multiple times, that's evidence it needs changing

## Adjustments

[Specific changes to make, with rationale. Format as actionable items.
If proposing changes:
- "Reduce focus_limit from 3 to 2: evidence shows completion rate dropped
  when 3 slots were active. Items averaged N days longer in focus."
- "Increase escalation_question_day from 3 to 5: most items take 4-5 days
  naturally; current setting creates noise."

If no changes:
- "No parameter adjustments this month. System is operating within expected
  ranges. Review again next month."]

## Hard Question

[One strategic question about the system itself — not about tasks or projects.
This is meta-level: is the system doing what it's supposed to?
Examples:
- "Is the system serving you, or are you serving the system?"
- "The focus limit went from 2 to 3. Did that help or fragment attention?"
- "You bypassed tracking N times this month. What does that tell you?"
- "Standup consistency was X%. If the system isn't being used, is it the
  right system?"
- "The retro is generating proposals. Are you acting on them?"]
```

### 5b. Scratchpad Distillation

Review the scratchpad layers at **every** retro (not only when size
thresholds are hit). Process both the global scratchpad and every
per-project scratchpad file.

1. **Read** `~/personal-assistant/data/scratchpad.md` and every
   `*.md` file under `~/personal-assistant/data/scratchpads/`.
2. **Count lines** for each file and report current size vs target
   (global ≤80, per-project ≤60).
3. **Flag entries older than 30 days** in each file — these MUST be
   reviewed, not skipped. Younger entries may be left alone.
4. **Review each flagged entry** and classify:
   - **Promote** → durable pattern → create memory via `/remember`
   - **Graduate** → permanent rule → propose addition to CLAUDE.md
   - **Consolidate** → merge related entries into one sharper entry
   - **Prune** → stale, superseded, or captured elsewhere; remove
   - **Keep** → still actively useful; leave it with a refresh note
5. **Promote-to-per-project** check: scan the global scratchpad for
   entries that carry a concrete path, config value, model version,
   or project name — these may have drifted and belong in a
   per-project scratchpad. Propose the move.
6. **Present plan** to user for approval before making any edits.
7. **Update** `Last distilled:` date in each reviewed file's header.

### 5c. Published-Artefacts Review (publish new + audit existing)

Curate `published/` — the subset of the repo recommended for external reuse.
This covers **all three** kinds of published artefact: grimoire prompts
(`published/prompts/`), skills (`published/skills/`), and agents
(`published/agents/`). Like 5b and the `/weekly-review` cluster-and-carry,
this is a periodic, draft-only, human-ratified curation.

**Policy (since 2026-06-15): copies only, no symlinks.** Every published
entry is a deliberately copied and *sanitised* snapshot; the canonical
working version stays in place (`skills/`, `agents/`, `data/notes/grimoire/`).
The retired symlink approach republished live files un-sanitised — see
`published/README.md` for why. The cost of copies is **drift**, which is why
this step audits existing copies, not just new candidates.

**Part A — audit existing copies for drift (do this first):**

1. **List** every published copy (`published/{prompts,skills,agents}/*.md`)
   and pair each with its source (the grimoire entry, `skills/<name>/SKILL.md`,
   or `agents/<name>.md`).
2. **Diff** each copy against its source. Flag any copy where the source has
   **materially changed** since the copy was made (needs a refresh), or where
   the source has since **gained private context** the copy doesn't reflect
   (the copy may now mislead, or the source may no longer be publishable).
3. **Re-sanitise check**: confirm each existing copy still meets the
   `published/README.md` bar (no absolute/`~` paths, machine names, client/
   project/collaborator names, instrumentation, identifiable third parties).
   Flag any that slipped through a prior pass for **refresh or un-publish**.

**Part B — identify new candidates:**

4. **Scan** grimoire entries, `skills/`, and `agents/` for artefacts that are
   (a) NOT yet published, AND (b) matured/stabilised over the period (reused,
   referenced across projects, or explicitly mature). New or churning entries
   are not candidates.
5. **Assess publish-readiness** against the `published/README.md` bar:
   generically reusable (not welded to one project's infra/specifics), free of
   private context, reads standalone. Note exactly what would need stripping.

**Part C — present and act (human-ratified):**

6. **Present** to the user, in one list: drift/re-sanitise findings from Part A
   and new candidates from Part B. For each, give the source path, a one-line
   rationale, and any context needing stripping. The user chooses **publish /
   refresh / un-publish / defer / decline** per entry. Do nothing without
   per-entry approval.
7. **On publish or refresh**, create/update the sanitised **copy**: copy the
   source into the matching `published/` subdirectory, strip the flagged
   private context, verify it reads standalone, and confirm the source stays
   in place. **Copies only — do not symlink.** On **un-publish**, remove the
   copy (the source is unaffected).
8. **Empty is a valid outcome.** A month with no drift and nothing newly ripe
   changes nothing here.

### 6. Apply Parameter Changes

After displaying the retrospective:

1. **Present** proposed adjustments as a clear list
2. **Ask** the user to approve, modify, or reject each proposal
3. **If approved**, update `~/personal-assistant/tasks/SYSTEM.md`:
   - Change the parameter value in the Parameters table
   - Add a row to the Adjustment History table with today's date and evidence-based reason
   - Update `Last retro: [date]`
4. **If rejected**, note the decision (it's useful data for next retro)

### 7. Save and Display

1. **Save** to `~/personal-assistant/reports/retros/YYYY-MM.md`
2. **Display** the full retrospective
3. **Ask:** "Any system observations worth capturing?" — route to `/remember`
   with `system_evolution` category if yes

## Notes

- The first retro will have limited data. That's expected — it establishes the baseline.
- If no weekly reviews exist for the month, note that as a data gap and work directly
  from raw sources (standups, memories, done archive).
- Metrics that can't be calculated due to missing data should show "N/A" with a note
  about what data is missing.
- The retro should be run once per month, ideally in the first few days of the new month.
- Parameter changes take effect immediately — they'll be used by the next standup.
- Don't propose changes for the sake of change. Stability is a feature.
- The Hard Question should make the user uncomfortable if the data warrants it.
  A month of system working well gets a lighter question like "What would break this?"
- Steps 5b (scratchpad distillation) and 5c (grimoire publishing review) are
  both **draft-only and human-ratified** — propose, then act only on approval.
  Both can validly produce no changes in a quiet month.
