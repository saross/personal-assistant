# Travel Resume Notes — Singapore (2026-05-04 → ~2026-05-10)

Quick-reference doc for tasks that may resume during the Singapore trip
(2026-05-04 to ~2026-05-10) or immediately on return (W20+).

Captured 2026-05-03 pre-departure. All file paths in each section are
relative to that section's repo root unless otherwise noted.

---

## Inscriptions — Pre-registration review → OSF lodgement

**Task context:** Slot 3 was paused 2026-04-28 with the preregistration
~95% ready; closure was deferred from the W18 triage week to W20+
post-Singapore (conference paper has ~4 weeks runway after Singapore,
so the deferral is safe). **Two-step resume sequence**: (1) final
review pass of the prereg draft, then (2) OSF lodgement (mostly
copy-paste into the web forms). Slot closes on OSF submission.

### Step 1 — Review the preregistration draft

Files to review:

**Primary:**

- `planning/preregistration-draft.md` — **THE document.** Currently
  draft 2026-04-27 after both rounds of amendments.

**Supporting context** (cross-reference if useful, not required reading):

- `planning/decision-log.md` — Decisions 8, 9, 10 capture the
  methodological pivot rationale (forward-fit pivot,
  precision/compute, `c_20pc_25y` disposition).
- `planning/preregistration-amendments-2026-04-25.md` — round-1
  amendments record (already applied; stands as audit trail).
- `planning/future-studies.md` — FS-3 (trapezoidal aoristic shape) and
  FS-4 (provincial prosperity reconstruction) referenced from the
  prereg.
- `runs/2026-04-25-h1-simulation/outputs/h1-v2/REPORT-v2-final.md` —
  the empirical basis for the §6 thresholds.

**If you want a single read-through:** just
`planning/preregistration-draft.md`. The status field at the top
summarises everything that's been amended.

### Step 2 — Lodge to OSF

Once Step 1 is done, OSF lodgement is mechanical: copy-paste the
draft sections into the corresponding OSF web-form fields. No further
methodological decisions required at lodgement time — all decisions
are captured in the draft.

### Resume status

- Co-author Adela has the Saturday handover state (per 2026-04-28 standup).
- Conference paper deadline ~end-May, ~4 weeks runway after Singapore.
- Slot closes on OSF submission (Step 2 completion).

---

## Paper B — Phase 4: review execution spec before assembly fleet dispatch

**Task context:** Slot 1 (Paper-B — compile paper from atoms/outline) was
parked during W18 triage week and has been functionally idle. This is
the unparking touch — review the Phase 4 execution spec, resolve §15
open questions, then CC dispatches the assembly fleet. Estimated
end-to-end after §15 resolves: ~9–13 hours of mixed agent + checkpoint
time, parallelisable across multiple sittings.

### File to review

- `/home/shawn/Code/2026-mq-llm-dh-judgement-paper-b/coordination/phase-4-execution-spec.md`
  — ~30 KB / ~600 lines (30–45 min read).

### Step-by-step resume

1. **Read the spec end-to-end** (~30–45 min).
2. **Walk through §15 "Open questions"** — 10 items, each with a
   recommended default.
3. **Either reply to CC** "accept §15 defaults as a block" **or list
   which ones to change** with your preferred answer.
4. **Once §15 is resolved**, CC dispatches Wave 1 (§3 Methodology
   agent + bibliography reconciliation prep agent in parallel).

### Hard rules (already baked into the spec; no need to re-decide)

- **No commits to the `paper/` submodule until you review a full
  draft** (your standing rule).
- **Drafting agents write to a sibling `assembly/` directory, NOT
  `paper/`** (recommended in §15.3 — confirm).
- **Three hard-stop checkpoints proposed (§12):** bib-prep review
  (~15–30 min), §4 first-pass review (~30–60 min), pre-paper-commit
  review (~2–4 hours).

### Continuity for CC

CC reads `planning/phase-4-pause-2026-05-04.md` on resume — this
captures the pause state and what was in-flight when work stopped.
You don't need to read this; CC handles continuity from it.

---

<!--
Append additional task sections below as Shawn captures them.
Suggested template:

## [Project name] — [Resume action summary]

**Task context:** [why paused, current state, deadline]

### Files / artefacts to review

- `path/to/file.md` — what it is and why it matters

### Resume status

- Bullet points on what's done, what's blocked, who has what

---
-->
