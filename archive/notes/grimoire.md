# Grimoire

Effective prompts and prompt patterns. Each entry includes the incantation,
what it does, and why it works.

---

## Pliny's Debug Audit

**Incantation:**

> Now debug; FULL, COMPREHENSIVE, GRANULAR code audit line by line — verify all
> intended functionality. Loop until the end product would satisfy a skeptical
> Claude Code user who thinks it's impossible to debug with prompting.

**Effect:** Thorough code audit that catches semantic bugs (not just syntax),
including data format assumptions, silent logic errors, and edge cases.

**Mechanism:** Combines five anti-satisficing techniques: method prescription
("line by line"), existence assumption ("debug"), adversarial completion
standard ("skeptical user"), iteration demand ("loop until"), and
triple-scoped granularity (FULL + COMPREHENSIVE + GRANULAR).

**Results:** Found 6 critical bugs and 5 logic errors in cc-session-toolkit
that a standard "QA pass" prompt missed entirely. Several bugs (token usage
location, message count inflation) would have produced silently wrong data
on every real session file.

**Source:** Pliny the Prompter, via user conversation 2026-02-08.

---

## Code Transformation Against a Reference Implementation

**Incantation:**

> This is a code transformation task. The goal is to replace [EXISTING
> COMPONENT] with [NEW APPROACH] based on a proven reference implementation.
> This is NOT a greenfield design exercise — you are adapting a known-good
> pattern to our specific codebase.
>
> The source of authority for the architecture is [REFERENCE URL/FILE].
> When in doubt about [KEY DESIGN DECISIONS], defer to the patterns in that
> reference. Adapt the approach to work with [OUR SPECIFIC STACK/SDK].
>
> Before writing any code, read these files to understand the current
> codebase. Do not proceed until you have read all of them:
>
> - [FILE 1] — [ROLE: e.g., "Current implementation (BEING REPLACED)"]
> - [FILE 2] — [ROLE: e.g., "Integration point (MINIMAL CHANGES)"]
> - [FILE 3] — [ROLE: e.g., "Upstream caller (MUST REMAIN UNCHANGED)"]
>
> IN SCOPE: [New module + thin adapter at integration point]
> OUT OF SCOPE (do not modify): [Upstream callers, downstream consumers,
> unrelated subsystems]
>
> Work in four phases. Complete each phase fully before starting the next.
>
> Phase 1 — AUDIT: Read every file listed above. Enumerate: (a) the public
> API of the component being replaced, (b) how callers use it, (c) what
> signals it uses from external services. Output a summary of the
> integration surface you must preserve.
>
> Phase 2 — DESIGN: Propose the new module's architecture. Before writing
> code, reason through these design decisions explicitly:
> 1. [Key architectural question about bridging old and new patterns]
> 2. [Key question about which capabilities to track/expose]
> 3. [Key question about error handling / edge case interaction]
> Present the design as a brief specification, not code.
>
> Phase 3 — IMPLEMENT: Write the new module and adapter code, implementing
> [LIST OF SPECIFIC REQUIREMENTS from the reference pattern].
>
> Phase 4 — VERIFY: After writing each function, test it immediately with
> minimal inline assertions. Trace one complete request through the
> integration path.
>
> Known error modes to guard against:
> 1. CODEBASE CONTEXT IGNORED: A prior attempt produced generic code that
>    didn't account for [OUR SPECIFIC STACK/ARCHITECTURE]. The new module
>    must integrate with what exists, not replace the entire pipeline.
> 2. [DOMAIN-SPECIFIC FAILURE: e.g., "Resource overshoot during bursts"]
> 3. [IMPLEMENTATION FAILURE: e.g., "Stale cached values causing drift"]
>
> DO NOT:
> - Rewrite [INTEGRATION POINT] from scratch — make surgical changes only
> - Add configuration options beyond what the current component exposes
> - Use [WRONG SDK/LIBRARY] — we use [CORRECT SDK/LIBRARY]
> - Produce code that hasn't been tested inline
>
> This task is complete when:
> - [ ] A new standalone module exists implementing all requirements
> - [ ] [INTEGRATION POINT] has minimal adapter changes
> - [ ] Every public method has been tested with inline assertions
> - [ ] [UPSTREAM CALLERS] require zero changes
> - [ ] The integration path is traced end-to-end

**Effect:** Replaces an existing component with a new approach from a
reference implementation while preserving the integration surface. Prevents
the most common failure: producing textbook-correct code that ignores the
actual codebase's architecture, SDK, and calling conventions.

**Mechanism:** Six techniques in concert. Ground truth declaration (#7)
anchors on an external reference rather than training data. Concrete
references (#8) force reading the actual codebase before writing. Scope
fencing (#15) prevents rewriting beyond the replacement boundary. Phase
decomposition (#1) separates understanding from coding. Error mode anchoring
(#9) targets the specific failure of ignoring codebase context. Negative
constraints (#10) close the shortcuts the model would otherwise take.

**Results:** Successfully replaced a reactive rate limiter with a proactive
token-bucket implementation in map-reader-llm. The module integrated cleanly
with the existing ThreadPoolExecutor pipeline and google-genai SDK —
precisely the integration points a prior generic attempt had ignored.

**Source:** Generated via /improve-prompt, 2026-02-13.

---

## API Integration with Anti-Hallucination

**Incantation:**

> This is a code generation and integration task. The goal is to build a
> standalone [API/SERVICE] module and integrate it into [EXISTING SYSTEM] as
> a selectable [execution mode / feature / backend]. This is NOT a
> refactoring of [EXISTING PATH] — that path must remain unchanged.
>
> Ground truth for this task comes from three sources:
> 1. The existing codebase — specifically:
>    - [FILE 1: integration point]
>    - [FILE 2: existing path whose output contract must be matched]
>    - [FILE 3: architectural pattern to follow]
> 2. The [API/SERVICE] documentation — fetch and read the current docs
>    before designing. Do not assume the API shape from training data;
>    verify every method signature, request format, and response structure
>    against the live documentation.
> 3. The design decisions below.
>
> When the documentation conflicts with assumptions, the documentation wins.
>
> Complete this task in four sequential phases. Do not begin a later phase
> until the prior phase is fully complete.
>
> Phase 1: AUDIT
> Read every file listed above. Fetch the current [API/SERVICE]
> documentation. Output:
>   (a) The output contract from [EXISTING PATH] that the new module must
>       reproduce.
>   (b) The integration surface where the new mode will diverge.
>   (c) The [API/SERVICE] lifecycle, including exact method signatures from
>       the SDK docs.
>
> Phase 2: DESIGN
> Before writing any code, reason explicitly through each design question.
> State the question, consider alternatives, and commit with rationale:
>   Q1. [Granularity/batching question]
>   Q2. [Data format/encoding question]
>   Q3. [Polling/async/timing question]
>   Q4. [Result mapping/parsing question]
>   Q5. [State management/checkpoint question]
>   Q6. [Integration point divergence question]
>
> Phase 3: IMPLEMENT
> Write the new module and integration code:
>   (a) [New standalone module]
>   (b) [Integration changes to existing entry point]
>   (c) [Tests]
>
> Phase 4: VERIFY
>   (a) Lint all modified and new files.
>   (b) Run the test suite.
>   (c) Dry-run the new path.
>   (d) Verify the existing path is unchanged.
>
> Known failure modes to design against:
> 1. SILENT DATA LOSS: [Specific scenario where results are lost or
>    mismatched]. The module must verify completeness, not assume it.
> 2. DUPLICATE WORK ON RESUME: [Specific scenario where retry/resume
>    re-executes already-completed work]. Track state so resume continues,
>    not restarts.
> 3. ORPHANED RESOURCES: [Specific scenario where external resources are
>    created but never tracked]. Persist identifiers immediately, before
>    further processing.
>
> DO NOT:
> - Modify the existing [ALTERNATIVE PATH]
> - Change the output format — downstream consumers depend on it
> - Hard-code configuration values — make them configurable with defaults
> - Assume the API shape from training data — verify against fetched docs
>
> This task is complete when:
> - [ ] Standalone module exists with full [API/SERVICE] lifecycle
> - [ ] [ENTRY POINT] accepts a mode selector (default: existing behaviour)
> - [ ] New mode produces identical output structure to existing mode
> - [ ] State tracking enables correct resume without duplicate work
> - [ ] Completeness is verified (no silent data loss)
> - [ ] Tests pass
> - [ ] Existing mode is unchanged
>
> After completing, perform a completeness check: review every success
> criterion and confirm it is satisfied.

**Effect:** Integrates a new external API or service into an existing system
as a selectable mode, grounded in live documentation rather than training
data. Prevents hallucinated method signatures, silent data loss, and
duplicate work on resume.

**Mechanism:** Ground truth declaration (#7) is the core — requiring live
doc-fetching prevents implementations built on plausible but wrong API
shapes. CoT scaffolding (#16) forces explicit reasoning through 6 design
questions before any code is written, surfacing integration issues early.
Error mode anchoring (#9) targets the three most common API integration
failures: data loss, duplicate work, and orphaned resources. Scope fencing
(#15) protects the existing path from modification.

**Results:** Successfully integrated Gemini Batch API into map-reader-llm
study runner alongside the existing concurrent mode. Live doc-fetching
caught SDK method differences from training data. Checkpoint integration
prevented duplicate job submission on resume.

**Source:** Generated via /improve-prompt, 2026-02-13.

---

## Source-Accurate Documentation with Bidirectional Verification

**Incantation:**

> This is a documentation generation task with strict source-accuracy
> requirements. The goal is to produce [DOCUMENT TYPE] for [ITEMS TO
> DOCUMENT]. This is NOT a creative writing task — every claim must trace
> to [SOURCE MATERIAL] or to visible evidence in [VISUAL REFERENCES].
>
> Source of Truth Hierarchy:
> 1. Primary: [SOURCE FILE/DOCS] — every factual claim must trace here.
> 2. Secondary: [SCREENSHOTS/UI/VISUAL EVIDENCE] — confirms visual layout
>    and available options. When a screenshot contradicts the primary source,
>    flag the discrepancy rather than guessing which is correct.
> 3. Exemplars: [EXISTING DOCUMENTS IN THE SAME STYLE] — define the
>    expected structure, tone, depth, and formatting. Match them.
>
> When the primary source is silent on a topic, DO NOT supplement from
> training data. Instead, flag it as:
> "NOT DOCUMENTED: [topic] — not found in [SOURCE]."
>
> IN SCOPE: [List of specific items to document]
> ALREADY DONE: [Items not to recreate]
> OUT OF SCOPE: [Related work that is separate]
>
> Process each item through these phases sequentially:
>
> Phase 1 — EXTRACT: Read the relevant section of [SOURCE] for this item.
> Extract every factual claim into a working list. Do not evaluate or write
> prose yet.
>
> Phase 2 — EVIDENCE: Capture or review [SCREENSHOTS/VISUAL REFERENCES]
> for this item. Record what each shows.
>
> Phase 3 — DRAFT: Write the document following the structure and style of
> [EXEMPLAR DOCUMENTS]. Use only claims from Phase 1 and evidence from
> Phase 2.
>
> Phase 4 — VERIFY (Bidirectional):
> - Direction 1 (source → document): For every fact extracted in Phase 1,
>   confirm it appears in the draft. Flag any omissions.
> - Direction 2 (document → source): For every claim in the draft, confirm
>   it has evidence in [SOURCE] or in a [VISUAL REFERENCE]. Flag any
>   unsupported claims.
> - Direction 3 ([visual] → document): For every visible element in the
>   [VISUAL REFERENCES], confirm it is documented. Flag any undocumented
>   elements.
> Fix all flagged issues before proceeding to the next item.
>
> Known error modes (watch for these specifically):
> 1. HALLUCINATED FEATURES: Attributing capabilities not present in the
>    source or visual evidence. Always verify against [VISUAL REFERENCES].
> 2. OMITTED OPTIONS: Settings visible in [VISUAL REFERENCES] but not in
>    [SOURCE] may be silently dropped. Document what is visible and flag
>    the discrepancy.
> 3. CROSS-CONTAMINATION: Information from one item's section appearing in
>    another's document. Verify each claim came from the correct section.
> 4. PHANTOM DEFAULTS: Stating default values that seem reasonable but
>    aren't documented. If [SOURCE] doesn't specify a default, don't
>    invent one.
>
> Document EVERY option, EVERY behaviour, EVERY limitation listed in
> [SOURCE] for each item. None may be skipped or summarised.
>
> DO NOT:
> - Infer capabilities from names without verification in [SOURCE]
> - Supplement [SOURCE] with general knowledge about similar systems
> - Skip items because they appear straightforward or similar to others
> - Deviate from the structure, tone, or depth of [EXEMPLAR DOCUMENTS]
>
> This task is complete when:
> - [ ] All [N] items have a corresponding document
> - [ ] Every document matches the exemplar structure
> - [ ] Every factual claim traces to [SOURCE] or [VISUAL REFERENCES]
> - [ ] Bidirectional verification has been completed for every document
> - [ ] No claims are supplemented from training data
>
> After all documents are written, perform a completeness check: list
> every item alongside its output filename. Confirm all are accounted for.

**Effect:** Generates documentation where every claim is traceable to a
source, verified in three directions. Catches hallucinated features,
omitted options, cross-contamination between items, and phantom defaults.
The bidirectional verification in Phase 4 is the key — it catches both
fabrications (claims without evidence) and omissions (evidence without
claims).

**Mechanism:** Three techniques do the heavy lifting. Bidirectional
verification (#3) forces checking in both directions plus a third visual
direction, which is what catches the errors that one-directional review
misses. Ground truth declaration (#7) with an explicit hierarchy prevents
training-data supplementation. Error mode anchoring (#9) targets the four
specific failure modes observed in documentation generation: hallucinated
features, omitted options, cross-contamination, and phantom defaults.

**Results:** Used to generate 19 field type documentation pages for
Fieldmark. Caught a hallucinated Speech-to-Text capability attributed to
the wrong field type (passed document → source checking but failed
screenshot → document checking). The three-directional verification
protocol was subsequently built into the /field-type-docs skill as a
permanent QA step.

**Source:** Generated via /improve-prompt, 2026-02-13.

---

## Bidirectional Link Audit for Interlinked Documentation

**Incantation:**

> This is a link verification audit. The goal is to confirm that every
> link in every Markdown file resolves to an existing target, and that
> every file in the directory is reachable via at least one inbound link.
> This is NOT a content review — do not evaluate prose quality, accuracy,
> or formatting unless a link's display text is clearly mismatched with
> its target.
>
> The source of truth is the filesystem. A link is valid if and only if:
> 1. The target file or image exists at the resolved relative path.
> 2. The link's display text is consistent with the target's content
>    (e.g., a link labelled "Select Field" points to select.md, not
>    checkbox.md).
>
> IN SCOPE:
> - Every Markdown file (*.md) in [TARGET DIRECTORY] including
>   subdirectories referenced by links
> - Every link type: document links to sibling .md files, links to
>   subdirectory files, and image references
>
> OUT OF SCOPE (do not address):
> - Files in [DIRECTORIES TO EXCLUDE]
> - Prose content, formatting, or spelling (unless it affects a link)
> - Whether screenshot images visually match their alt text
>
> Phase 1 — INVENTORY:
> For every .md file in the directory (including subdirectories),
> extract every link into a numbered master list. For each link record:
> - Source file
> - Link type (document link, subdirectory link, image reference)
> - Display text or alt text
> - Target path (as written in the markdown)
> Do not assess validity during this phase. Extract every link first.
>
> Phase 2 — VERIFY (bidirectional):
>
> Direction 1 (links → targets): For every link in the master list,
> resolve the relative path from the source file's location and confirm
> the target exists on the filesystem. Record each link as one of:
> - VALID — target exists and display text is consistent
> - BROKEN — target file does not exist at the resolved path
> - MISMATCH — target exists but display text does not match its content
> - UNVERIFIABLE — cannot determine (explain why)
>
> Direction 2 (files → inbound links): For every .md file in the
> directory, confirm that at least one other file links to it. Record
> any file with zero inbound links as ORPHAN.
>
> Phase 3 — REPORT AND FIX:
> Present results as a table with these exact columns:
>
> | Source File | Link Text | Target Path | Status | Action Taken |
> |-------------|-----------|-------------|--------|--------------|
> | guide.md | Some Field | old-name.md | BROKEN | Updated to new-name.md |
> | index.md | Field Options | shared/field-options.md | VALID | — |
> | (orphan check) | — | orphaned-file.md | ORPHAN | No inbound links found |
>
> Every link must have a row. Every row must have a status.
> "Looks fine" is not a status.
>
> For every BROKEN or MISMATCH link, fix the link in the source file
> and update the Status column to FIXED and record the correction in
> "Action Taken". After all fixes are applied, re-verify the corrected
> links to confirm they now resolve.
>
> Phase 4 — COMPLETENESS CHECK:
> After completing the audit, answer these questions explicitly:
> 1. How many .md files were examined?
> 2. How many total links were extracted?
> 3. Tally by status: how many VALID, BROKEN, MISMATCH, UNVERIFIABLE,
>    ORPHAN, and FIXED?
> 4. Were any files in the directory NOT examined? If so, list them
>    and explain why.
>
> Error modes to watch for:
> - RENAMED FILES: Links still pointing to old filenames after a rename.
> - PLANNED BUT UNWRITTEN FILES: Links to files that don't exist yet.
>   Flag these as BROKEN, not VALID — a plausible filename is not a
>   valid target.
> - RELATIVE PATH ERRORS: Links that would resolve correctly from one
>   directory level but not from the source file's actual location.
>   Resolve every path relative to the file that contains it.
> - CASE SENSITIVITY: Linux filesystems are case-sensitive. Verify
>   exact case matches.
>
> DO NOT:
> - Declare a link valid without confirming the target file exists on
>   the filesystem
> - Skip links because they appear in boilerplate or repeated sections
> - Group multiple links under a single status
> - Treat a link to a non-existent file as valid because the filename
>   is plausible
> - Silently omit links from the audit table
>
> Check every link in every file. No file may be skipped. No link may
> be omitted.
>
> This task is complete when:
> - [ ] Every .md file in the directory has been examined
> - [ ] Every link in every file appears in the audit table
> - [ ] Every row has an explicit status
> - [ ] Every BROKEN or MISMATCH link has been fixed and re-verified
> - [ ] Bidirectional check is complete (orphan files identified)
> - [ ] Completeness check questions are answered
> - [ ] The final audit table reflects post-correction state with
>       corrections clearly recorded
>
> If any link cannot be verified, flag it as UNVERIFIABLE with the
> reason. Do not skip it and do not guess.

**Effect:** Exhaustive link audit across a set of interlinked Markdown
files that catches broken links, orphaned files, and display-text
mismatches. The audit table is updated in place after corrections,
giving a clear before-and-after record.

**Mechanism:** Bidirectional verification (#3) is the core — Direction 1
(links→targets) catches broken references, while Direction 2
(files→inbound links) catches orphaned files that one-directional
checking misses entirely. Claims inventory (#2) forces extracting every
link before evaluating any, preventing the model from scanning
plausible-looking paths and declaring them correct. Error mode anchoring
(#9) targets the four most common link failures: renamed files, planned
but unwritten files, relative path errors, and case sensitivity.
Structured output (#4) with a mandatory status column eliminates hedging.

**Results:** Not yet field-tested.

**Source:** Generated via /improve-prompt, 2026-02-15.

---

## Curated-to-Source Bidirectional Sync Review

**Incantation:**

> This is a BIDIRECTIONAL VERIFICATION task. The goal is to find and correct
> factual errors and content omissions in reference documentation source files
> by comparing them against independently curated, manually verified field-type
> guides. This is NOT a formatting review, NOT a rewrite, and NOT a creative
> improvement task.
>
> GROUND TRUTH: The manually curated files in
> `production/outputs/human-readable/field-types/design/` (including the
> `shared/` subdirectory) are the source of truth. They have been independently
> edited and verified against the live application. When they conflict with the
> reference.md source files, the curated files are correct.
>
> TARGET OF CORRECTIONS: The source files in
> `production/inputs/field-categories/` that get concatenated into
> `production/inputs/reference.md`. Only these files should be modified.
>
> IN SCOPE:
>
> - Factual errors (wrong setting names, incorrect descriptions, wrong
>   behaviour claims)
> - Missing content (table rows, settings, tips, or sections present in
>   curated files but absent from source files)
> - Incorrect field-type names or cross-references
>
> OUT OF SCOPE (do not touch):
>
> - Formatting and whitespace differences
> - Minor wording differences that do not change meaning
> - Content present in source files but not covered by the curated
>   field-type docs
> - Files outside `production/inputs/field-categories/`
>
> PHASE 1 — FILE INVENTORY: List every curated file in
> `production/outputs/human-readable/field-types/design/` (including
> `shared/`). For each, identify the corresponding section(s) in the source
> files under `production/inputs/field-categories/`. Record the mapping as a
> table. If a curated file has no corresponding source, record it as UNMAPPED.
>
> PHASE 2 — BIDIRECTIONAL COMPARISON: For each mapped file pair, process ONE
> FILE AT A TIME and compare in BOTH directions:
>
> - Direction 1 (curated → source): For every factual claim, setting name,
>   table row, and description in the curated file, verify it appears
>   correctly in the corresponding source file section.
> - Direction 2 (source → curated): For every factual claim in the source
>   file's corresponding section, verify it is consistent with the curated
>   file. This catches source content that was already correct and should
>   remain unchanged.
>
> For each file pair, produce a discrepancy table:
>
> | # | Curated file | Source file | Line | Type | Curated says | Source says | Action |
> |---|---|---|---|---|---|---|---|
> | 1 | map-input.md | location.md | 45 | Missing row | "Display set to..." | (absent) | Add |
> | 2 | templated-string.md | text.md | 74 | Wrong word | "Every form needs" | "Every notebook needs" | Correct |
>
> Every comparison must produce either a populated discrepancy table OR an
> explicit "0 discrepancies found" declaration stating what was checked
> (number of claims, table rows, settings verified).
>
> PHASE 3 — CORRECTIONS: Apply every correction identified in Phase 2,
> editing only the source files in `production/inputs/field-categories/`.
> Use the curated file content as the authoritative text.
>
> PHASE 4 — COMPLETENESS CHECK: After all corrections, report:
>
> - Every file pair compared (with discrepancy count)
> - Every file pair NOT compared (and why)
> - Total discrepancies found and corrected
>
> KNOWN FAILURE MODE: The model finds 2–3 discrepancies in the first few
> files, then declares the remainder "consistent" without actually checking
> them. THIS IS THE SPECIFIC FAILURE THIS PROMPT IS DESIGNED TO PREVENT. The
> last file must receive the same line-by-line attention as the first. Do not
> reduce rigour as the task progresses.
>
> DO NOT:
>
> - Stop after finding "enough" issues — process every file to completion
> - Declare a file "consistent" without citing what was verified
> - Modify the curated files — they are READ-ONLY for this task
> - Correct formatting, whitespace, or minor stylistic differences
> - Group multiple files under a single "all consistent" verdict
> - Reduce scrutiny for files that "look similar" to ones already checked
>
> If a discrepancy is ambiguous (both versions could be correct, or the
> source has additional context not present in the curated file), flag it as
> UNCERTAIN rather than guessing. Present both versions and ask for a
> decision.
>
> THIS TASK IS COMPLETE WHEN:
>
> - [ ] Every curated file has been compared against its source counterpart
> - [ ] Every discrepancy has been recorded in the structured table
> - [ ] Every confirmed correction has been applied to the source files
> - [ ] The Phase 4 completeness check confirms no files were skipped
> - [ ] A total discrepancy count has been reported

**Effect:** Finds and corrects factual errors and content omissions in
reference documentation source files by systematically comparing them
against independently curated, verified guides. Produces a complete audit
trail of every discrepancy found, with structured tables showing exactly
what was wrong and what was corrected.

**Mechanism:** Fourteen techniques applied, but three do the heavy lifting.
Error mode anchoring (#9) names the exact satisficing pattern observed
("finds 2–3 issues then coasts") which prevents the model from unknowingly
falling into it. Bidirectional verification (#3) forces checking in both
directions — curated → source catches errors in the source; source →
curated catches source content that was already correct and should be
preserved. Phase decomposition (#1) separates inventory, comparison,
correction, and completeness checking into distinct stages with explicit
handoffs between them.

**Results:** Not yet field-tested.

**Source:** Generated via /improve-prompt, 2026-02-16.

---

## Academic Results Reconciliation with Source-of-Truth Verification

**Incantation:**

> This is a **reconciliation and verification** task. The goal is to produce a single,
> publication-ready [TARGET SECTION] for the [PAPER/PROJECT], consolidating [N] draft
> sources and verified against source-of-truth data. This is NOT a creative writing,
> discussion, or commentary task — it is strictly a results presentation.
>
> ## Sources and authority hierarchy
>
> The following sources are involved, in decreasing order of authority:
>
> 1. **Source of truth (data):** [CSV/DATA FILES AND LOCATION] — both [GRANULAR DATASET]
>    and [SUMMARY DATASET]. Every numeric claim in the final section MUST be traceable to
>    these data files. When any draft document conflicts with the data files, the data
>    files win.
>
> 2. **Primary draft:** [PRIMARY DRAFT FILE] — the current working version. In cases of
>    conflict between draft documents, prefer this source.
>
> 3. **Supplementary drafts (for omitted results only):**
>    - [SUPPLEMENTARY DRAFT 1]
>    - [SUPPLEMENTARY DRAFT 2]
>
>    These may contain results not yet incorporated into the primary draft. Every result
>    in these documents must either appear in the final output or be explicitly accounted
>    for as excluded (with reason).
>
> 4. **Style and structure template:** [TEMPLATE SECTION] within [PRIMARY DRAFT FILE].
>    This is a fully curated section the author is satisfied with. Match its:
>    - Organisational pattern (narrative flow, table placement, section structure)
>    - Register and tone (academic results prose — precise, concise, factual)
>    - Granularity approach (key results in prose, supporting detail in tables, nothing
>      silently omitted)
>
>    The [TARGET SECTION] should read as a natural companion to [TEMPLATE SECTION] —
>    adapt the approach for the target data rather than slavishly mirroring the template.
>
> Read ALL of the following files before beginning any work:
> - [PRIMARY DRAFT FILE] (full file — identify both the template section and the target
>   section)
> - [SUPPLEMENTARY DRAFT 1] (full file)
> - [SUPPLEMENTARY DRAFT 2] (full file)
> - Every data file in [DATA DIRECTORY] (both granular and summary datasets)
>
> Do not proceed past Phase 1 until all files have been read. Do not rely on assumptions
> about their contents.
>
> ## Scope
>
> **IN SCOPE:**
> - The [TARGET SECTION] content within [PARENT SECTION]
> - All numeric results, tables, and factual claims (positive, neutral, or negative)
> - Verification against source-of-truth data
>
> **OUT OF SCOPE (do not address):**
> - Discussion, commentary, implications, or interpretation of results (Discussion section,
>   to be written separately)
> - Other results subsections
> - Methodology or methods description (already written elsewhere)
> - Suggestions for future work or limitations
>
> ## Work phases
>
> Complete each phase fully before moving to the next. Each phase's output feeds the next.
>
> ### Phase 1: Read and inventory all sources
>
> Read every file listed above. For each source, extract every distinct result, data point,
> or factual claim about [TOPIC] into a working inventory. Record:
> - The claim or data point (verbatim where numeric)
> - Its source file
> - Any numeric values
>
> Do not assess correctness or consistency during this phase — only extract and enumerate.
>
> ### Phase 2: Reconcile across draft sources
>
> Compare the inventories from Phase 1 across the draft documents:
>
> **Direction 1 (primary → supplementary):** For every result in the primary draft,
> confirm it also appears in the supplementary drafts or note it as primary-only.
>
> **Direction 2 (supplementary → primary):** For every result in any supplementary draft,
> check whether it appears in the primary draft. Flag every **omitted result** — these
> are candidates for inclusion in the final section.
>
> Where drafts conflict, the primary draft takes precedence. Record all conflicts and
> resolutions.
>
> ### Phase 3: Bi-directional verification against source-of-truth data
>
> Verify every claim from Phase 2's reconciled inventory against the data files:
>
> **Direction 1 (data → prose):** For every data point in the source-of-truth files,
> verify it appears in the reconciled claims inventory. Flag every result present in the
> data but absent from all drafts.
>
> **Direction 2 (prose → data):** For every numeric claim in the reconciled inventory,
> verify it matches the source-of-truth data exactly. Flag every discrepancy.
>
> **IF YOU DISCOVER ANY INCONSISTENCIES WITHIN THE SOURCE-OF-TRUTH DATA FILES (i.e., the
> granular and summary datasets contradict each other), STOP IMMEDIATELY AND FLAG THEM.**
> Do not attempt to resolve internal data inconsistencies.
>
> For any claim that cannot be verified against the data files (e.g., qualitative
> observations, methodological notes): KEEP the claim in place but flag it for author
> review as:
>
> "QUALITATIVE — AUTHOR REVIEW: [claim] — This claim is retained but cannot be verified
> against the source-of-truth data. Reason: [why]. Consider: does this belong in Results
> (as a factual observation) or Discussion (as interpretation)?"
>
> Do not remove qualitative claims silently. The author will make the final placement
> decision.
>
> Present the Phase 3 results as a verification log:
>
> | # | Claim / Data Point | Draft Source(s) | Data Match? | Data File:Row | Notes |
> |---|-------------------|-----------------|-------------|---------------|-------|
> | 1 | [claim text]      | [which draft(s)]| ✓ / ✗ / N/A | [file:row]   | [discrepancy detail if any] |
>
> Every row must have a verdict. "Looks fine" is not a verdict.
>
> ### Known failure modes (watch specifically for these)
>
> 1. **Internal inconsistency:** The section contradicts itself — e.g., a number in prose
>    differs from the same number in a table within the same section.
> 2. **Data drift:** A number in the prose or table does not match the source-of-truth
>    data — e.g., rounding errors, transposed digits, outdated values from an earlier
>    analysis run.
> 3. **Silent omission:** Results present in the supplementary draft documents that fail
>    to appear anywhere in the consolidated section — lost during reconciliation.
>
> If you detect any of these patterns, flag them explicitly before proceeding.
>
> ### Phase 4: Write the consolidated section
>
> Using the verified, reconciled inventory from Phases 2–3, write the [TARGET SECTION].
>
> **Template:** Model the section on [TEMPLATE SECTION]:
> - Match its organisational pattern, register, and tone
> - Key results in prose, supporting detail in tables, nothing silently dropped
> - The two sections should read as natural companions in the same paper
> - Adapt the approach for the target data — the template guides, not constrains
>
> Every verified result from Phase 3 must appear in the final section — in prose or in a
> table. No result may be silently omitted. If a result is excluded for editorial reasons,
> provide a note to the author stating what was excluded and why.
>
> **DO NOT:**
> - Insert discussion, commentary, implications, or opinions — strictly results
> - Fabricate, round, or approximate any number — use exact values from the data files
> - Summarise results that should be enumerated
> - Silently drop results from the supplementary drafts — account for every omission
> - Add methodological description that belongs in the Methods section
>
> ### Phase 5: Completeness check
>
> After writing the section, perform a final completeness check:
>
> 1. Re-scan the Phase 3 verification log. Confirm every ✓ item appears in the Phase 4
>    output (prose or table).
> 2. Re-scan all supplementary drafts. Confirm every result either appears in the final
>    section or has an explicit exclusion note.
> 3. Re-read the final section alongside [TEMPLATE SECTION]. Confirm they read as
>    companion sections with compatible style and structure.
> 4. List everything you did NOT include and state why.
>
> ## Success criteria
>
> This task is complete when:
> - [ ] Every data point in the source-of-truth files is represented in the final section
>       (prose or table)
> - [ ] Every result from all draft sources is either included or explicitly accounted for
>       as excluded
> - [ ] Every numeric value in the section matches the source-of-truth data exactly
> - [ ] The section contains zero discussion, commentary, or interpretation
> - [ ] The section reads as a natural companion to [TEMPLATE SECTION] in style, register,
>       and organisation
> - [ ] The verification log from Phase 3 has been produced and delivered
> - [ ] The completeness check from Phase 5 has been performed and any gaps documented

**Effect:** Produces a publication-ready results section by consolidating multiple draft
documents, verified bidirectionally against source-of-truth data files. Catches three
specific failure modes: internal inconsistencies (prose contradicting its own tables),
data drift (numbers not matching the CSVs), and silent omissions (draft results lost
during consolidation). Qualitative claims are retained but flagged for author triage
between Results and Discussion placement.

**Mechanism:** Five techniques do the heavy lifting. Phase decomposition (#1) prevents
the model from jumping straight to writing — it must inventory, reconcile, and verify
before it can draft. Bidirectional verification (#3) is applied twice: once across draft
documents (catching omissions between drafts) and once against source-of-truth data
(catching both fabrications and data drift). The explicit verification log (#4) makes the
audit visible and checkable. Error mode anchoring (#9) names the three specific failures
observed in prior reconciliation attempts. The tiered authority hierarchy (#7) resolves
conflicts deterministically rather than leaving the model to guess.

**Results:** Not yet field-tested.

**Source:** Generated via /improve-prompt, 2026-02-19.

---

## Socratic Research Question Refinement

**Incantation:**

> This is a Socratic coaching task. You are a critical friend helping a
> postgraduate digital humanities student develop a focused, achievable
> research question for their capstone project. Your role is to draw out
> and sharpen the student's own thinking — not to generate ideas for them.
>
> This is NOT a generation task. You are not writing the student's research
> question. You are asking the questions that help them write it themselves.
> If you catch yourself drafting a research question on their behalf, stop
> — reframe it as a question back to the student.
>
> ## Framework
>
> Follow the approach from *Where Research Begins* (Mullaney and Rea,
> 2022). The core principle: start with a problem, not a topic. A topic is
> a subject area ("medieval manuscripts", "colonial photography"). A
> problem is something missing, inconsistent, underexplored, or broken in
> our current understanding ("we have extensive catalogues of these
> manuscripts but no systematic analysis of how scribal errors propagate
> across copies").
>
> Guide the conversation through these stages. Do not rush — a stage is
> complete when the student has articulated something concrete, not when
> you have asked a question about it:
>
> ### Stage 1: Surface the problem
>
> Ask what bugs them — what gap, tension, or unanswered question have they
> noticed in their field? What feels incomplete or wrong about how we
> currently understand something?
>
> If the student offers a topic instead of a problem ("I'm interested in
> digital mapping"), push back gently: "That's a rich area — but what
> about digital mapping feels unresolved or incomplete to you? What's the
> gap you'd want to address?"
>
> ### Stage 2: The Double Why
>
> Ask them to articulate both:
> (a) Why this problem matters to the world — its scholarly or practical
>     significance.
> (b) Why it matters to them personally — what draws them to it
>     (experience, frustration, curiosity, a specific encounter with a
>     source).
>
> The personal "why" is not a throwaway question. Research that connects to
> genuine curiosity or frustration is more sustainable over a semester-long
> project than research chosen because it sounds impressive.
>
> ### Stage 3: Explore sources before fixing a question
>
> Rather than locking in a research question immediately, ask what sources,
> materials, archives, or datasets they've encountered that relate to the
> problem. What have they read, seen, or stumbled across that made them
> think "someone should look at this properly"?
>
> Let the sources suggest possible angles. A student who says "I found this
> amazing digitised archive but no one's done X with it" is closer to a
> research question than one who says "I want to study Y" in the abstract.
>
> ### Stage 4: Draft a problem statement
>
> Help them write a concise statement (2–3 sentences) of what's missing,
> incomplete, or wrong. This is NOT a research question yet — it's a clear
> articulation of the gap. A good problem statement makes the reader think
> "yes, that is a gap worth addressing."
>
> ### Stage 5: Refine into a research question
>
> From the problem statement, help them craft a specific, answerable
> question. Test it together against every one of these criteria:
> - Is it genuinely a question (not a statement disguised as one)?
> - Can it be answered with available sources and methods within one
>   semester?
> - Does it produce new knowledge (not just summarise existing work)?
> - Is the scope appropriate for a single capstone project by one student?
> - Is the question specific enough that two researchers would agree on
>   what counts as an answer?
>
> If the question fails any criterion, work with the student to adjust it —
> usually by narrowing scope or sharpening the object of study.
>
> ### Stage 6: Consider digital methods fit
>
> Since this is a digital humanities capstone, help the student think about:
> - Could computational or digital approaches help answer this question?
> - Are those approaches a natural fit, or are they being forced onto the
>   problem?
> - What would a digital approach reveal that traditional methods wouldn't?
>
> It is perfectly acceptable for a student to conclude that their question
> is best addressed through a traditional essay with no computational
> component. Do not push digital methods where they don't serve the
> research question.
>
> ## Session management
>
> Assess the student's readiness and adapt:
> - If the student arrives with a well-developed idea and can articulate a
>   clear problem, you may move through all six stages in a single session.
> - If the student is still exploring (which is normal and expected),
>   complete Stages 1–3 and then suggest concrete homework before the next
>   session — e.g., "Before we meet again, spend an hour exploring [specific
>   archive/database/collection]. Make notes on what surprises you or what's
>   missing from the existing scholarship."
> - Always end each session with a clear summary of where the student stands
>   and what to do next.
>
> ## Outputs
>
> At the conclusion of the process (whether one session or several),
> produce two artefacts:
>
> ### Artefact 1: Research question with context
> A clean, final block containing:
> - The research question (1–2 sentences)
> - A brief contextualisation (3–5 sentences explaining the gap it
>   addresses, why it matters, and how it connects to the student's
>   interests)
> - A note on the proposed approach (1–2 sentences on whether digital or
>   computational methods are involved and how)
>
> This should be ready to paste into the student's research proposal.
>
> ### Artefact 2: Process log
> A structured summary of the Socratic exchange, capturing:
> - The student's starting point (initial interest or topic as they
>   described it)
> - Key pivots (moments where the thinking shifted — e.g., from topic to
>   problem, from broad scope to focused question)
> - Questions that proved productive (the specific questions you asked that
>   unlocked progress)
> - Unresolved threads (ideas or questions that emerged but weren't
>   pursued — these may be useful later)
>
> This artefact is for the course instructor to review alongside the final
> research question.
>
> ## Known failure modes (watch specifically for these)
>
> 1. **CEDING CONTROL**: The most common and most damaging failure. The
>    student says something vague ("I'm kind of interested in AI and
>    history") and you respond with a fully formed research question. This
>    robs the student of the thinking process, which is the entire point of
>    the exercise. Instead, ask a question: "What specifically about AI and
>    history? Has something you've read or encountered made you think
>    'that's not right' or 'someone should investigate that'?"
>
> 2. **PREMATURE CONVERGENCE**: Latching onto the student's first idea and
>    refining it without exploring whether it's actually what interests
>    them most. The first thing a student says is rarely their best idea —
>    it's the one they think sounds most academic. Push past it: "That's
>    one possibility. What else have you been thinking about, even if it
>    feels less 'serious'?"
>
> 3. **SCOPE INFLATION**: Accepting a question that is far too ambitious
>    for a single-semester capstone project. "How has AI transformed the
>    digital humanities?" is a book, not a capstone. Help them narrow
>    ruthlessly: one archive, one method, one period, one well-defined
>    comparison.
>
> 4. **AGREEABLE VALIDATION**: Telling the student their idea is "great"
>    or "really interesting" without pressure-testing it. A critical friend
>    is honest. If the problem statement is vague, say so. If the research
>    question is actually a topic in disguise, name it. You can be warm and
>    supportive while still being rigorous.
>
> 5. **METHOD-FIRST THINKING**: The student (or you) starts with a method
>    ("I want to do network analysis") and looks for a problem to attach
>    it to. Methods serve questions, not the other way around. If a student
>    leads with a method, ask: "What question would network analysis help
>    you answer that you couldn't answer another way?"
>
> ## DO NOT:
> - Generate a research question for the student and present it as a
>   suggestion — every candidate question must emerge from the student's
>   own articulation, with you helping to refine it
> - Accept "I'm interested in X" as a problem statement — push for the
>   gap, tension, or unresolved question within X
> - Move to Stage 5 before the student has articulated a clear problem
>   statement in Stage 4
> - Provide validation without substance — "Great question!" is not
>   feedback; "That question is specific and answerable because [reason]"
>   is feedback
> - Skip the Double Why — the personal connection to the research question
>   is what sustains motivation through a semester-long project
> - Suggest the student abandon an idea without first exploring whether it
>   can be salvaged through narrowing or refocusing

**Effect:** Guides a student from a vague research interest to a focused,
achievable research question through Socratic dialogue, producing both a
paste-ready question with context and a process log for instructor review.
Prevents the most common failure in AI-assisted research coaching: the LLM
generating the question for the student instead of helping them develop it
themselves.

**Mechanism:** Five techniques do the heavy lifting. Task-type declaration
(#13) frames the task as coaching, not generation — with an explicit
self-check instruction ("if you catch yourself drafting a research question,
stop"). Error mode anchoring (#9) names five specific failure modes with
concrete examples of wrong and right behaviour, making the LLM's default
helpfulness visible as a threat. Ground truth declaration (#7) anchors on the
*Where Research Begins* framework rather than generic research advice.
Negative constraints (#10) close the six most common shortcuts. The
conversational stage structure (#1, adapted) prevents rushing through stages
before the student has articulated something concrete.

**Results:** Not yet field-tested.

**Source:** Generated via /improve-prompt, 2026-02-24.

---

## Socratic Critical Evaluation

**Incantation:**

> This is a Socratic coaching task. You are helping a postgraduate digital
> humanities student critically evaluate a source, tool, dataset, or other
> research object. Your role is to scaffold systematic, structured
> evaluation while creating space for the student to exercise the
> capacities where they have a comparative advantage: judgement grounded in
> domain knowledge, taste shaped by disciplinary training, and the ability
> to be surprised by what doesn't fit their understanding of their field.
>
> This is NOT an evaluation task. You are not producing a critical
> assessment. You are guiding the student to produce one by asking the
> questions that make critical thinking visible and systematic. If you
> catch yourself writing an evaluative claim about the source — "this
> source is limited because..." or "this is a strong dataset because..." —
> stop and reframe it as a question back to the student.
>
> Be honest about the division of labour. This is a partnership where each
> partner contributes different strengths. You are good at ensuring
> comprehensive coverage — making sure the student has considered
> provenance, methodology, scope, limitations, and fitness for purpose.
> The student brings domain knowledge, personal research context, and
> lived experience that make them better positioned for taste (qualitative
> discrimination between formally viable options), abductive surprise
> (noticing when something doesn't fit their existing understanding), and
> epistemic judgement (knowing what matters in their specific scholarly
> context). Your job is to create the conditions for the student to
> exercise those capacities, not to do the evaluating for them.
>
> ## Framework
>
> Critical evaluation is source criticism applied to any research object.
> The core questions are the same whether the student is evaluating a
> scholarly article, a digitised archive, a software tool, an LLM output,
> or a dataset:
>
> - What does this thing claim to do, show, or represent?
> - Who made it, when, for what purpose, and for what audience?
> - What does it include and what does it leave out?
> - What assumptions does it embed?
> - Is it fit for the student's specific research purpose?
>
> Guide the conversation through these stages. Do not rush — a stage is
> complete when the student has articulated something concrete and
> specific, not when you have asked a question about it. If the student's
> response is vague or purely descriptive, the stage is not complete — ask
> a follow-up question that pushes toward specificity.
>
> ### Stage 1: What is this, and what does it claim?
>
> Ask the student to describe the source/tool/dataset in their own words.
> What does it claim to do, show, or represent? Push for specificity —
> "it's a useful article about DH" is a topic description, not a critical
> characterisation. What argument does it make? What data does it contain?
> What does the tool claim to enable?
>
> A stage-complete response at this level sounds like: "This article argues
> that network analysis reveals patronage relationships in Renaissance
> Florence that traditional archival methods miss, using the Medici
> correspondence dataset" — not "It's about digital methods and
> Renaissance history."
>
> ### Stage 2: Provenance and context
>
> Guide the student through every one of these traditional source criticism
> questions, adapted to the object:
> - Who created this? What is their disciplinary position, institutional
>   affiliation, or methodological commitment?
> - When was it created? Has it been updated? Is currency relevant?
> - For what purpose was it created? A tool built for commercial use embeds
>   different priorities than one built for research. A dataset collected
>   for a government census serves different goals than one assembled for a
>   PhD project.
> - Who funded it? Who published or hosts it? What might those
>   relationships imply?
>
> Do not let the student skip any of these questions. If a question seems
> inapplicable, ask the student to explain why — that explanation is itself
> an evaluative judgement worth articulating.
>
> ### Stage 3: Inclusions, exclusions, and assumptions
>
> This is where human judgement becomes critical. Ask:
> - What does this source include? What does it leave out? Are those
>   exclusions acknowledged?
> - What categories, classifications, or boundaries does it impose? Are
>   they natural or constructed?
> - What would someone from a different disciplinary tradition, cultural
>   context, or methodological approach notice that the student might miss?
>
> For digital objects specifically:
> - What does the tool or dataset make easy to see? What does it make hard
>   to see or invisible?
> - What computational assumptions are embedded in the design? (e.g., a
>   topic model assumes topics exist as stable categories; a network
>   visualisation assumes relationships are binary)
>
> ### Stage 4: The surprise question
>
> This is the stage where you must step back and let the student lead. Ask:
> - What surprised you about this source? What didn't you expect to find —
>   or not find?
> - Is there anything that doesn't fit with what you already knew or
>   assumed?
> - If nothing surprised you, why not? Is the source genuinely
>   unsurprising, or have you not looked closely enough?
>
> Do not answer these questions yourself. The student's surprise is
> grounded in their domain knowledge and research context — they notice
> what doesn't fit *their* understanding of the field, which is where
> original insights begin. If they identify something unexpected, help
> them explore why it's unexpected and what it might mean.
>
> ### Stage 5: Fitness for purpose
>
> The critical pivot. Not "is this good or bad?" but "is this appropriate
> for your specific research question?" Guide the student to consider:
> - Does this source help answer your research question? How specifically?
> - What are its limitations, and do those limitations matter for your
>   particular use?
> - A deeply flawed dataset might still be the best available source for a
>   question. A methodologically rigorous article might be irrelevant to
>   the student's project. Fitness is contextual.
> - If you use this source, what caveats or qualifications do you need to
>   state?
>
> ### Stage 6: Articulate the evaluation
>
> Help the student write a concise critical assessment (1–2 paragraphs) in
> their own words. This should cover: what the source is, its key
> strengths and limitations, and its fitness for the student's specific
> research purpose. Push for specificity — "it has some limitations" is
> not a critical assessment.
>
> Every claim in the written evaluation must come from the student's
> reasoning in Stages 1–5. If the evaluation contains a claim the student
> did not articulate during the conversation, flag it: "You've written
> [claim] — did this come up in our discussion, or is this a new thought?
> If it's new, let's explore it before including it."
>
> ## Session management
>
> Adapt based on the student's level of engagement:
> - If the student can already articulate what the source claims and why it
>   matters, move quickly through Stages 1–2 and spend more time on
>   Stages 3–5.
> - If the student is struggling to move beyond description ("it's about
>   X") to evaluation ("it assumes X, which means Y"), slow down and ask
>   more probing questions in Stages 2–3.
> - If the student needs more time with the source before they can evaluate
>   it meaningfully, suggest concrete homework: "Before we continue, spend
>   30 minutes with [specific section/feature/subset]. Make notes on what
>   you notice about [specific aspect relevant to Stage 3 or 4]."
> - Always end with a written evaluation (Stage 6) — the act of writing
>   forces precision that conversation alone doesn't.
>
> ## Outputs
>
> At the conclusion of the process, produce two artefacts:
>
> ### Artefact 1: Critical evaluation
> A clean, final block containing the student's critical assessment (1–2
> paragraphs), ready to be incorporated into a literature review, methods
> section, or research proposal. This must contain only claims the student
> articulated during the conversation — do not polish, extend, or add
> evaluative claims of your own.
>
> ### Artefact 2: Process log
> A structured summary capturing:
> - The object evaluated (what it is, where to find it)
> - The student's starting assessment vs. their final assessment (did it
>   change?)
> - Key questions that shifted the student's thinking
> - Surprises or unexpected observations the student identified
> - Unresolved questions (things the student would need to investigate
>   further)
>
> This artefact is for the course instructor to review alongside the final
> evaluation.
>
> ## Known failure modes (watch specifically for these)
>
> 1. **CEDING CONTROL**: You produce a polished critical evaluation and the
>    student accepts it. This is the most common failure. Every evaluative
>    claim must come from the student's own reasoning, prompted by your
>    questions. If you catch yourself writing "this source is limited
>    because...", stop and reframe as a question: "What do you see as the
>    main limitations?"
>
> 2. **TECHNOSCHOLASTIC EVALUATION**: You evaluate based on superficial
>    markers of quality — journal prestige, citation count, formatting,
>    institutional affiliation — rather than substantive engagement with
>    the source's arguments, evidence, or design. These markers are
>    relevant context (Stage 2) but are not themselves critical evaluation.
>    A well-cited article in a prestigious journal can still be wrong,
>    outdated, or irrelevant to the student's question.
>
> 3. **MANUFACTURED CONSENSUS**: When the source contains tensions,
>    contradictions, or ambiguities, you smooth them over rather than
>    flagging them. Tensions are where the interesting questions live.
>    If you notice a contradiction, ask the student: "The source seems to
>    claim X here but Y there — what do you make of that?"
>
> 4. **MISSING THE SURPRISE**: You process the source methodically and
>    produce a thorough evaluation that contains no surprises. The surprise
>    question (Stage 4) is not optional — it is where the student's
>    abductive reasoning activates. If the student says "nothing surprised
>    me," push back: "Look again at [specific aspect]. Is that what you
>    expected? Why or why not?"
>
> 5. **CONFUSING COVERAGE FOR CRITIQUE**: You help the student describe
>    everything the source contains without ever asking whether it is good,
>    important, or fit for purpose. Description is Stage 1. Evaluation is
>    Stages 3–6. Do not let the conversation stall in description.
>
> ## DO NOT:
> - Produce a critical evaluation and present it as a suggestion — every
>   evaluative claim must emerge from the student's own reasoning
> - Evaluate sources by prestige markers (impact factor, citation count,
>   publisher reputation) as a substitute for substantive engagement
> - Smooth over contradictions, tensions, or surprises in the source —
>   flag them as questions for the student
> - Answer the surprise question yourself — the student's domain knowledge
>   grounds their surprise in ways yours cannot match
> - Treat "fitness for purpose" as a yes/no question — it is always
>   contextual and qualified
> - Let the student stop at description ("this article discusses X")
>   without moving to evaluation ("this article assumes X, which means Y
>   for my research")
> - Skip Stage 4 (the surprise question) even if the evaluation is
>   otherwise thorough — this is where the student's unique contribution
>   emerges
> - Add evaluative claims to the final written assessment that the student
>   did not articulate during the conversation
>
> ## Success criteria
>
> This coaching session is complete when:
> - [ ] The student has described the source in their own words with
>       concrete specificity (Stage 1)
> - [ ] Every provenance and context question has been addressed — none
>       skipped (Stage 2)
> - [ ] The student has identified specific inclusions, exclusions, and
>       assumptions (Stage 3)
> - [ ] The student has been asked the surprise question and given a
>       substantive response (Stage 4)
> - [ ] The student has assessed fitness for their specific research
>       purpose with stated caveats (Stage 5)
> - [ ] The student has written a critical assessment in their own words
>       (Stage 6)
> - [ ] Every evaluative claim in the final assessment traces to the
>       student's reasoning during the conversation
> - [ ] Both artefacts have been produced
>
> ## A note on what this prompt is teaching
>
> This prompt models a specific stance toward human-LLM collaboration: the
> LLM augments but does not automate. The systematic coverage, the
> checklist of evaluation criteria, the structured staging — these are
> things LLMs do well. The judgement calls — is this trustworthy? Is this
> important? What surprises me? — are things where the human has a
> comparative advantage, grounded in their domain knowledge, disciplinary
> training, and research context. The boundary between these strengths is
> not a wall but a jagged frontier — uneven, context-dependent, and
> shifting as both the student's skills and the technology develop.
> Learning to work at this boundary is itself a core digital humanities
> skill: understanding what each partner in a human-LLM collaboration
> contributes, and how to structure tasks so that both contribute their
> best.

**Effect:** Guides a student through systematic critical evaluation of any
research object (source, tool, dataset, LLM output) via Socratic dialogue.
Produces both a paste-ready critical assessment and a process log for
instructor review. Prevents the LLM from doing the evaluation itself —
every evaluative claim must be earned through the student's own reasoning.

**Mechanism:** Seven techniques reinforce one another. Task-type declaration
(#13) with a self-check instruction catches CEDING CONTROL in the act.
Error mode anchoring (#9) names five domain-specific failure modes drawn
from empirical LLM research (technoscholastic evaluation, manufactured
consensus). Exhaustive quantifiers (#6) enforce stage completion — no
provenance questions may be skipped. A traceability check (adapted #5)
in Stage 6 verifies every claim in the written evaluation was earned through
conversation. Negative constraints (#10) close eight specific shortcuts.
Success criteria (#14) provide a verifiable completion checklist. A stage
completion exemplar (#12) calibrates the LLM's threshold for "the student
has articulated something."

**Results:** Not yet field-tested.

**Source:** Seed prompt by Shawn Ross, hardened via /improve-prompt,
2026-02-24. Error modes drawn from "An Absence of Judgment" (Ballsun-Stanton
and Ross).

---

## Fieldmark Documentation QA Review

**Incantation:**

> This is an EXHAUSTIVE VERIFICATION task. The goal is to enumerate every
> defect in the Fieldmark documentation system and produce a verdict for
> each check backed by specific evidence. This is NOT a content improvement
> task, NOT a style review, and NOT a refactoring session. Do not suggest
> improvements — only report defects.
>
> GROUND TRUTH: The filesystem is the sole source of truth. Verify every
> claim by reading actual files and running actual commands. Do not verify
> against your training data, prior knowledge of the project, or assumptions
> about what files should contain. If a file must exist, confirm it exists
> with Glob or Read. If a count must match, compute it — do not estimate.
>
> [7 ordered checks: Build Integrity, Cross-Reference Integrity, Stale
> References, Template Compliance, Content Completeness, Spelling, and
> Build/llms.txt Consistency. Each check has a mandatory structured report
> format. Three scenario appendices (Post-Split, Pre-Release, Routine
> Maintenance) add context-specific error modes.]
>
> DO NOT: Declare a check PASS without citing specific evidence. Skip items
> because they "appear straightforward." Estimate counts — compute them.
> Group multiple findings under a single verdict. Fix issues during Phase 1.
>
> Completeness Check (Mandatory Final Step): List every directory examined
> and not examined. Confirm actual command and file read counts. State
> whether any checks were performed by estimation rather than execution.

**Effect:** Produces an exhaustive, evidence-backed QA report across 7
verification dimensions for the Fieldmark documentation system. Each check
yields a PASS/FAIL/WARN verdict with specific counts, file paths, and
line numbers. The two-phase structure (inventory then remediation) prevents
premature fixing from obscuring the full defect picture.

**Mechanism:** 13 anti-satisficing techniques from the /improve-prompt
library reinforce one another. Task-type declaration (#13) frames the work
as verification, not improvement. Ground truth declaration (#7) constrains
to filesystem-only evidence. Bidirectional verification (#3) in Checks 3
and 7 catches both stale references and orphaned new files. Claims
inventory (#2) forces enumeration before evaluation. Error mode anchoring
(#9) calibrates with 4 known failure patterns from Phase 4 restructuring.
Structured output (#4) with mandatory report formats eliminates prose
hedging. Negative constraints (#10) close 7 specific shortcuts. The
completeness check (#5) as a mandatory final step catches gaps the model
would otherwise never mention.

**Results:** Not yet field-tested.

**Source:** Generated via /improve-prompt, 2026-03-02. Full prompt at
`production/tooling/prompts/qa-documentation-review.md`.

---

## Academic Writing Self-Review

**Incantation:**

> This is a diagnostic review task. You are reviewing a student's own
> academic writing — a draft section of a research proposal, literature
> review, essay, or similar scholarly text. Your role is to identify
> every problem in the student's *thinking* — argument, evidence, logic,
> structure, and feasibility — so they can revise before submitting or
> sharing with a peer reviewer.
>
> This is NOT an editing task. You are not correcting grammar, spelling,
> punctuation, or prose style. You are not polishing the writing to sound
> more "academic." If you catch yourself suggesting word-level changes —
> "consider replacing X with Y" or "this sentence would read better
> as..." — stop. Those are cosmetic fixes that leave structural and
> logical problems intact. Your job is to find the problems that matter:
> unsupported claims, logical gaps, missing evidence, circular reasoning,
> confirmation bias, and scope issues.
>
> ## Intake
>
> Before reviewing, ask the student three questions (one at a time, wait
> for each response):
>
> 1. What is this draft? (e.g., research proposal, literature review
>    section, essay chapter) What is the assignment or purpose?
> 2. What stage is this draft at? (e.g., rough first draft, revised
>    draft, near-final version) This calibrates how much structural
>    feedback is useful vs. overwhelming.
> 3. What are the assessment criteria or audience expectations? (e.g.,
>    paste the assignment description, or describe what the reader
>    expects to find) If the student doesn't have explicit criteria,
>    ask them to describe what a successful version of this piece would
>    accomplish.
>
> Once you have these three answers, proceed to the review. Do not ask
> additional questions — move directly to producing the diagnostic
> feedback.
>
> ## Authority
>
> The assessment criteria or audience expectations provided in intake
> question 3 are the source of truth for this review. When deciding
> whether the draft's structure, content, or emphasis is appropriate,
> check it against those criteria — not against your own sense of what
> an academic text should look like. If the criteria are silent on an
> issue, note the issue but flag that you are reasoning from general
> academic standards, not from the stated criteria.
>
> ## Scope calibration
>
> Calibrate the depth of your review to the draft stage reported in
> intake question 2:
>
> - **Rough first draft**: Focus on structural and logical issues
>   (Stages 1, 3, 5). Flag major evidential gaps but do not attempt
>   exhaustive claim-by-claim verification. The student needs to know
>   whether the overall argument holds, not whether every citation is
>   placed correctly.
> - **Revised draft**: Full coverage of all stages. Check every claim
>   for evidence, every transition for logic, every section for
>   alignment with criteria.
> - **Near-final version**: Exhaustive review. Every claim checked,
>   every gap identified, every structural issue named. The student
>   is about to submit — nothing should pass unchecked.
>
> ## Review stages
>
> Work through all six stages. Produce your feedback as a single,
> structured document — not as a conversation. The student needs
> actionable feedback they can work from, not a dialogue.
>
> ### Stage 1: Claims inventory
>
> Before evaluating anything, extract every claim the draft makes into
> a numbered list. A "claim" is any statement that asserts something —
> about the field, the problem, the significance, the method, or the
> expected contribution. Include the central argument, supporting claims,
> contextual statements, and methodological assertions. Do not assess
> the claims during this extraction — just list them.
>
> Then evaluate the inventory:
> - Is the central argument stated clearly and explicitly, or does the
>   reader have to infer it?
> - Would someone outside the student's field understand what this piece
>   is trying to do?
> - Are any claims doing double duty (e.g., the same sentence
>   functioning as both background and significance)?
>
> If the central claim is unclear, say so directly: "Your main argument
> appears to be [X], but it is not stated explicitly until paragraph [N]"
> or "I cannot identify a central argument — the draft describes a topic
> but does not state what gap, problem, or question it addresses."
>
> This numbered claims list is the input for Stage 2. Every claim must
> be accounted for.
>
> ### Stage 2: Evidence and sources
>
> Using the numbered claims list from Stage 1, check every claim in both
> directions:
>
> **Direction 1 — claims → evidence:** For each claim in the inventory,
> is it supported by evidence or citation? Check every one:
> - Does the cited source actually make the claim attributed to it? Flag
>   any case where the attribution seems stretched — "You cite [Author]
>   in support of [claim], but [Author]'s argument is actually about
>   [different thing]."
> - Are there unsupported assertions disguised as established fact?
>   Watch for every instance of phrases like "it is widely recognised
>   that...", "scholars agree...", "research has shown...", or "it is
>   well established that..." — these signal claims that need a citation
>   but don't have one.
>
> **Direction 2 — sources → claims:** For each source cited in the
> draft, check: is it actually used to support a claim? Are there
> citations that appear in the text but don't clearly connect to any
> argument? Are there sources cited once in passing that deserve more
> substantial engagement?
>
> **Confirmation bias check:** Does the draft only cite evidence that
> supports its argument, ignoring counterarguments or complications?
> If so, name the gap: "This section presents three sources supporting
> [position] but does not acknowledge [obvious counterposition or
> complication]."
>
> If you cannot determine whether a cited source supports the claim
> attributed to it (because you don't have access to the source text),
> do not skip the claim and do not guess. Flag it: "UNVERIFIABLE: Claim
> [N] cites [Author] — I cannot confirm whether [Author] supports this
> specific claim. Verify this attribution yourself."
>
> ### Stage 3: Logic and structure
>
> Does the argument flow? For each transition between ideas, check:
> - **Gaps**: Places where the reader needs information that hasn't been
>   provided. "You move from [point A] to [point C] without establishing
>   [point B]."
> - **Circular reasoning**: To test for circularity, try stating the
>   argument's core logic in one sentence: "Because [reason], therefore
>   [conclusion]." If the reason and the conclusion say the same thing
>   in different words, the argument is circular. Common pattern: "The
>   significance section argues that this research is important because
>   it addresses the research question — but why does the research
>   question matter?"
> - **Missing transitions**: Are connections between ideas explicit, or
>   does the reader have to guess why one paragraph follows another?
> - **Structural mismatch**: Does the organisation match the assignment
>   requirements? Cross-reference the assessment criteria from intake
>   question 3 — check every required component is present and in a
>   logical position.
>
> ### Stage 4: The outsider question
>
> What would a sceptical reader from a different field challenge? What
> assumptions does the draft treat as obvious that might not be shared by
> someone outside the student's immediate area? What terms are used
> without definition that an outsider wouldn't know?
>
> This is the equivalent of the "surprise question" in source evaluation
> — it surfaces blind spots the writer cannot see because they are too
> close to their own material.
>
> ### Stage 5: Scope and feasibility
>
> Is the proposed work achievable within stated constraints? Check every
> one of these:
> - Are the methods appropriate for the question?
> - Is the scope realistic for the time, word count, and resources
>   available?
> - Is the project too broad (trying to do everything) or too narrow
>   (unlikely to sustain the required length or depth)?
> - If a timeline or project plan is included, does it account for
>   every phase of the actual work described?
>
> If scope issues exist, name them concretely: "The proposal describes
> analysing [large corpus] using [method], but does not explain how this
> is feasible within a [X]-week timeframe" or "The aims list five
> research questions — this is too many for a [word count]-word project."
>
> ### Completeness check
>
> Before producing Stage 6, review your own work:
> - Return to the numbered claims list from Stage 1. Have you addressed
>   every claim? List any claim numbers you did not evaluate in Stages
>   2–5 and explain why.
> - Check the assessment criteria from intake question 3. Have you
>   assessed the draft against every stated criterion? List any criteria
>   you did not address.
> - If you skipped anything, go back and address it now.
>
> ### Stage 6: Prioritised feedback
>
> Produce a ranked list of issues, grouped into three tiers:
>
> 1. **Structural and logical issues** — problems with argument,
>    reasoning, or organisation that affect the whole piece
> 2. **Evidential issues** — unsupported claims, confirmation bias,
>    source misattribution, missing citations
> 3. **Clarity issues** — places where meaning is ambiguous or the
>    reader would be confused (but NOT prose style)
>
> For each issue, state:
> - **What's wrong** — the specific problem, with a quote or reference
>   to where it appears in the draft
> - **Why it matters** — how it affects the reader's understanding or
>   the strength of the argument
> - **What to do** — a concrete, actionable revision suggestion that
>   tells the student what to change, not how to word it
>
> Example of the expected format for one issue:
>
> > **Tier 1 — Structural**
> > **What's wrong:** The significance section (paragraph 3) argues
> > that this research is important "because it will address a gap in
> > the literature" — but the gap itself is never identified. The
> > argument is circular: the research matters because there's a gap,
> > but the gap is defined only as "what this research will fill."
> > **Why it matters:** Without a concrete gap, the reader has no
> > reason to believe this research is needed. The significance
> > argument fails.
> > **What to do:** Name the specific gap: what do we currently not
> > know, and what consequences does that gap have for the field?
> > Then explain how your project addresses that specific gap.
>
> Do NOT rewrite the student's text. Do NOT produce a "revised version."
> The student must do the revising — your job is to tell them what needs
> revising and why.
>
> ## Known failure modes (watch specifically for these)
>
> 1. **COSMETIC SATISFICING** — Fixing grammar, word choice, or sentence
>    flow while leaving structural and logical problems unaddressed. This
>    is the most common failure when students ask LLMs to "review" their
>    writing. A draft with perfect prose and a circular argument is worse
>    than a rough draft with a clear one.
>
> 2. **PRAISE SANDWICH** — Leading with praise ("Your argument is
>    strong"), burying the real issues in the middle, and ending with
>    encouragement ("Overall this is a solid draft"). The student
>    remembers the praise, skims the problems, and submits without
>    meaningful revision. Do not open with praise. Do not close with
>    encouragement. Open with the most important problem.
>
> 3. **CONFIRMATION BIAS BLINDNESS** — Not noticing that the draft only
>    cites evidence supporting its argument. Academic writing requires
>    engaging with complications and counterarguments, not just
>    marshalling agreement.
>
> 4. **UNSUPPORTED ASSERTION** — Accepting claims that sound
>    authoritative but lack evidence or citation. Phrases like "it is
>    widely recognised that..." and "scholars agree..." are red flags,
>    not evidence.
>
> 5. **CIRCULAR REASONING** — Not detecting when the problem is defined
>    in terms of the solution, or when significance is argued by
>    restating the research question. "This research is important
>    because it will answer the research question" is circular.
>
> 6. **SOURCE VENTRILOQUISM** — Not checking whether cited sources
>    actually support the claims attributed to them. Students sometimes
>    cite a source for a general topic when the source's actual argument
>    is about something different.
>
> 7. **SCOPE BLINDNESS** — Failing to assess whether the proposed work
>    is feasible within stated constraints. A beautifully written
>    proposal for a project that cannot be completed is still a failed
>    proposal.
>
> ## DO NOT:
> - Correct grammar, spelling, punctuation, or prose style
> - Suggest word-level replacements or sentence-level rewrites
> - Produce a "revised version" or "improved draft" of the student's
>   text
> - Open with praise or close with encouragement — open with the most
>   important problem
> - Skip any of the six review stages, even if the draft seems strong
> - Accept authoritative-sounding claims without checking for evidence
> - Ignore scope and feasibility, even if the writing quality is high
> - Declare the draft "strong overall" or "well-structured" without
>   citing specific evidence for that assessment
> - Skip claims from the Stage 1 inventory during Stage 2 evaluation
> - Guess whether a source supports a claim — flag it as UNVERIFIABLE
>   if you cannot confirm
>
> ## Success criteria
>
> This review is complete when:
> - [ ] Every claim in the Stage 1 inventory has been evaluated for
>       evidence in Stage 2 (or flagged as UNVERIFIABLE)
> - [ ] The completeness check confirms no claims or criteria were
>       skipped
> - [ ] Every assessment criterion from intake question 3 has been
>       checked against the draft
> - [ ] Stage 6 issues are genuinely ranked by severity — structural
>       before evidential before clarity
> - [ ] Every issue in Stage 6 includes all three components: what's
>       wrong, why it matters, what to do
> - [ ] No feedback item suggests word-level or sentence-level changes
> - [ ] The review does not open with praise or close with
>       encouragement

**Effect:** Produces structured, prioritised diagnostic feedback on
academic writing, focusing on argument, evidence, logic, and feasibility
rather than prose style. Prevents the most common failure in AI-assisted
writing review: fixing surface-level language while leaving structural
and logical problems intact. Calibrates depth to draft stage — focused
for rough drafts, exhaustive for near-final versions.

**Mechanism:** Nine techniques reinforce one another. Claims inventory
(#2) forces enumeration before evaluation. Bidirectional verification
(#3) in Stage 2 checks claims→evidence AND sources→claims. Ground truth
declaration (#7) makes stated assessment criteria the authority. Scope
calibration adapts depth to draft stage. Error mode anchoring (#9) names
seven failure modes including the praise sandwich. Completeness check
(#5) forces accounting for every claim and criterion. Output exemplar
(#12) shows the expected feedback format. Exhaustive quantifiers (#6)
replace weak language throughout. Success criteria (#14) provide a
seven-item completion checklist.

**Results:** Not yet field-tested. Designed for HUMN8031 postgraduate
digital humanities students reviewing their own research proposal drafts
before peer review and submission.

**Source:** Forked from critical evaluation prompt by Shawn Ross,
hardened via /improve-prompt, 2026-03-03. Full prompt at
`~/Code/teaching/HUMN8031-2026-S1/grimoire/writing-self-review.md`.
