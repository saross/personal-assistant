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
| `~/personal-assistant/reports/weekly/` | All weekly reviews from the month — scorecards, patterns, hard questions |
| `~/personal-assistant/tasks/done/YYYY-MM.md` | All completions for the month |
| `~/personal-assistant/tasks/FOCUS.md` | Current state (for context) |
| `~/personal-assistant/tasks/SYSTEM.md` | Current parameters + adjustment history |
| `~/personal-assistant/memories/memories.jsonl` | Memories in period, especially: `system_evolution`, `system_friction`, `system_success`, `slip`, `completion`, `blocker_real`, `blocker_excuse` |
| `~/personal-assistant/standups/` | All standups from the month |

### 3. Calculate System Metrics

| Metric | Calculation |
|--------|-------------|
| **Completion rate** | Items completed / items that entered focus during the month. Track "entered focus" from git log of FOCUS.md or from weekly reviews. |
| **Focus churn** | Number of add/remove/swap operations on FOCUS.md (from git log). |
| **Avg days in focus** | Mean of "Days in Focus" column from done/YYYY-MM.md for completed items. |
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

```text
# System Retrospective — [Month] [Year]

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
