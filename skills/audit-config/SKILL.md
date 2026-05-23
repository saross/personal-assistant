---
name: audit-config
description: "Pre-launch experimental configuration audit. Use before committing API spend to a detection or verification run. Systematically checks every config parameter against the preregistered protocol, known failure modes, and the filesystem. Produces a READY TO LAUNCH / BLOCKED verdict. Trigger phrases: 'audit configs', 'check configs', 'ready to run', 'launch the evaluation'. Also trigger PROACTIVELY when the user is about to launch an experimental API run — especially after generating new configs."
---

# /audit-config — Pre-Launch Experimental Configuration Audit

This is a VERIFICATION task — not a review, not a suggestion engine. The goal
is to produce a binary READY TO LAUNCH / BLOCKED verdict by systematically
checking every configuration parameter against the preregistered protocol.
This is NOT a code review or a design discussion. Do not suggest improvements
to the experimental design; only verify that the implementation matches the
intent.

You are auditing VLM detection experiment configurations before an API run
that costs real money. Your job is to catch configuration errors,
preregistration violations, and silent parameter mismatches BEFORE they waste
budget. The H10/H12 text-only error ($33 wasted, half a day of invalid
analysis and troubleshooting) was caused by exactly the kind of mistake this
audit is designed to catch.

## Sources of Truth (in priority order)

1. **Preregistration**: `docs/methodology/preregistration/osf/preregistration.md` — the canonical protocol
2. **Errata**: `docs/methodology/preregistration/protocol-errata.md` — documented deviations that override the preregistration
3. **Decisions log**: `docs/methodology/preregistration/decisions-log.md` — decisions that constrain or modify the protocol
4. **The filesystem**: actual file paths, image dimensions, JSON values — NOT config descriptions or comments

When sources conflict, higher-numbered sources override lower (errata override
preregistration; filesystem overrides everything claimed in config
descriptions).

## Inputs

The user will provide:

- The hypothesis being tested (e.g., "H10", "H12")
- The config files to audit (paths or glob pattern)
- Optionally: the specific parameter being varied

## Scope

**IN SCOPE**: Every parameter that reaches the API payload — model,
temperature, thinking_level, include_example_images, instruction_file,
examples list, tile size, tile manifest, evaluation bounds.

**OUT OF SCOPE**: Code quality, script architecture, analysis plan, cost
optimisation. These are valid concerns but not this audit's job.

## Audit Steps

### Step 1: Extract preregistration requirements (OUTPUT: requirements checklist)

Read the relevant hypothesis section from
`docs/methodology/preregistration/osf/preregistration.md`. Also read
`protocol-errata.md` and `decisions-log.md` for modifications. Refer to other
preregistration documents as necessary to clarify the protocol.

Extract EVERY testable requirement into a numbered checklist. For each
requirement, record:

- The requirement (what the preregistration says)
- The source (section number, line number, or errata entry)
- Whether it is a HARD constraint or a RECOMMENDED practice

Do not proceed to Step 2 until this checklist is complete. This checklist
becomes the input for Step 4.

### Step 2: Config pairwise diff (OUTPUT: parameter table)

Load ALL condition configs. For EVERY field in EVERY config, check whether it
is IDENTICAL across all conditions or DIFFERS. Do not skip fields that
"obviously" should be the same — check them.

Report as a table:

| Field | Identical? | Value(s) | Classification |
|-------|-----------|----------|---------------|
| model | YES | gemini-3.5-flash | Controlled |
| examples | NO | [differs per pool] | MANIPULATED — expected |
| temperature | YES | 0.7 | Controlled |
| ... | ... | ... | ... |

Check in BOTH directions:

- **Config → intent**: For every field that DIFFERS, confirm it is the
  intended manipulated variable or expected metadata. Flag any UNEXPECTED
  differences as potential confounds.
- **Intent → config**: For the factor the hypothesis is testing, confirm it
  actually differs between conditions. If the target factor is IDENTICAL
  across configs, flag as a BLOCKER (the experiment tests nothing).

### Step 3: Transmission verification (OUTPUT: per-config pass/fail)

For EVERY config, verify that the manipulated factor will physically reach
the API. Check against these known failure modes:

| Error Mode | What to check | Source |
|---|---|---|
| **Image flag off** | `include_example_images` is explicitly `true`, not `false`, `null`, or absent | H10/H12 text-only error |
| **Temperature shadowed** | No CLI `--temperature` override contradicts config value | E43, E44 |
| **Thinking level dropped** | `thinking_level` matches intent; if model is Pro, level is ≥ MEDIUM | E34, E40 |
| **Model version drift** | `model` field is identical across all conditions and matches the study's model | Scratchpad rule |
| **Tile size mismatch** | Config tile_size matches actual tile dimensions (384 vs 512) | Dry-run error |
| **Wrong tile set** | Manifest points to correct tile set (calibration vs evaluation vs full) | Manual check |
| **Wrong instruction file** | `instruction_file` matches the intended track (image vs text-only) | H10/H12 base config error |
| **Example paths broken** | EVERY path in the `examples` list resolves to a file under `inputs/examples/` | Filesystem check |
| **Example image dimensions** | Crop images are the expected size (e.g., 150×150 for hard examples, 384×384 for nulls) | Pipeline consistency |

For each config, report PASS or FAIL per error mode. A FAIL on any error mode
is a BLOCKER.

### Step 4: Preregistration cross-check (OUTPUT: alignment table)

Using the requirements checklist from Step 1, check EVERY requirement against
the configs:

| # | Requirement | Config value | Verdict | Notes |
|---|---|---|---|---|
| 1 | Pool sizes: 20, 40, 80, 160 | [check] | MATCHES / DEVIATION | |
| 2 | ... | ... | ... | |

Verdict categories:

- **MATCHES**: Config aligns with preregistration (or errata-modified
  requirement)
- **DELIBERATE DEVIATION**: Config differs, but a corresponding entry EXISTS
  in `protocol-errata.md`. Cite the errata entry (e.g., "E49").
- **UNDOCUMENTED DEVIATION**: Config differs with NO errata entry. **BLOCKER**
  — must be corrected or recorded in errata before proceeding.

Also check the reverse direction: for every parameter in the configs, is it
consistent with the preregistration? This catches parameters the
preregistration doesn't mention but the config sets to non-default values.

### Step 5: Dry-run validation (OUTPUT: pass/fail)

Run `--dry-run` of the detection script with ONE config and verify:

- Correct number of tiles found in manifest (state expected vs actual)
- Correct number of examples loaded (state expected vs actual)
- No "Warning: Reference image not found" messages
- No "Tile dimensions do not match" errors
- The `experiment_intent.md` preview confirms the hypothesis, factor, and
  modality

Report PASS or FAIL. Any discrepancy is a BLOCKER.

### Step 6: Holdout and evaluation scope (OUTPUT: pass/fail)

Verify:

- The evaluation manifest is DISJOINT from any calibration/training tiles
  (zero overlap)
- The evaluation tile count matches expectations (state expected vs actual)
- Ground truth reference file is correct for this evaluation area
- The bounds file used for scoring matches the evaluation tile set

### Step 7: Completeness check

After completing Steps 1-6, review your own audit:

- List any config fields you did NOT check and state why
- List any preregistration requirements from Step 1 that were not verified in
  Step 4
- List any error modes from Step 3 that could not be verified (e.g.,
  runtime-only checks)
- State whether any checks were skipped due to missing information

If any items remain unchecked, flag them as WARNINGS in the final report.

## Output Format

Present results as a structured audit report. EVERY check MUST have a verdict
— "looks fine" is not a verdict.

```text
=== PRE-LAUNCH AUDIT: [Hypothesis] ===

1. PREREGISTRATION REQUIREMENTS: [N requirements extracted]
   [numbered list]

2. CONFIG DIFF: [N fields identical, M fields differ]
   Controlled: [list with values]
   Manipulated: [list — EXPECTED or UNEXPECTED per field]
   Confounds: [NONE or list]

3. TRANSMISSION CHECK:
   [table: config × error mode → PASS/FAIL]
   Blockers: [NONE or list]

4. PREREGISTRATION ALIGNMENT:
   Matches: [count]
   Deliberate deviations: [count, with errata refs]
   Undocumented deviations: [count — BLOCKER if >0]

5. DRY-RUN: PASS / FAIL
   [details if FAIL]

6. EVALUATION SCOPE: PASS / FAIL
   [details if FAIL]

7. COMPLETENESS: [items not checked, if any]

BLOCKERS: [list, or NONE]
WARNINGS: [list, or NONE]

OVERALL: READY TO LAUNCH / BLOCKED ([reasons])
```

## Success Criteria

This audit is complete when:

- [ ] Every preregistration requirement has been checked (Step 1 count = Step
  4 count)
- [ ] Every config field has been compared across conditions (Step 2 table is
  complete)
- [ ] Every error mode has been checked for every config (Step 3 matrix is
  full)
- [ ] Every deviation is either documented in errata or flagged as a blocker
- [ ] A dry-run has confirmed example loading and tile counts
- [ ] The completeness check (Step 7) has been performed

## Critical Rules

DO NOT:

- Trust config `description` fields — check the ACTUAL JSON values for every
  parameter
- Declare a parameter "correct" without verifying it against the
  preregistration or errata
- Skip a check because the parameter "obviously" hasn't changed
- Accept `include_example_images: null` or absent as equivalent to `true` —
  it must be explicitly `true` for image-based experiments
- Proceed past an undocumented deviation — it is ALWAYS a blocker until
  recorded in errata
- Group multiple parameters under a single "all correct" verdict — each
  parameter gets its own check

A config with `include_example_images: false` that claims to test an
image-based factor is ALWAYS a blocker. If more parameters differ between
conditions than the target factor + metadata fields, flag as a potential
confound.
