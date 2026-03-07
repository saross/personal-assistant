# Progressive Disclosure Memory — Format Prototype

**Generated:** 2026-02-15 13:46 UTC
**Total memories in system:** 3621
**Simulated project:** personal-assistant (cross-project hub mode)

---

## Comparison Summary

| Metric | Current (Level 2 flat) | Proposed (Level 1 compact) |
|--------|----------------------|---------------------------|
| Memories loaded | 35 | 150 |
| Context size | 13,845 chars (~3,461 tokens) | 19,403 chars (~4,850 tokens) |
| Chars per memory | 395 | 129 |
| Coverage ratio | 35/3621 (1.0%) | 150/3621 (4.1%) |

---

## A. Current System Output (Level 2 — Full Memories)

This is what the session-start hook currently injects:

```text
# Memory Context

The following memories were retrieved from previous sessions:

## Recent Memories (last 7 days)

- [decision] (high, 2026-02-15) Implemented three-way error classification for documentation corrections: (1) purge deprecation language entirely, (2) soften unverified bugs to 'known limitation', (3) reframe hard validation as soft validation (visual warnings that don't block saves). This consistency prevents mixed signals about RadioGroup's status across documentation. | tags: documentation, consistency, error-classification
- [methodology] (high, 2026-02-15) Verification regex sweep catches documentation instances missed by semantic inventory from explore agents, including code-embedded passages and cross-referenced sections. The plan's verification step is essential because explore agents search by semantic category while regex catches all syntactic matches regardless of context. | tags: verification, search-strategy, documentation-audit
- [gotcha] (high, 2026-02-15) Deprecation and validation language can hide in code blocks and cross-referenced sections where semantic search agents may not look thoroughly. Exhaustive verification with grep-based patterns is necessary to ensure clean documentation after bulk corrections. | tags: documentation, search-completeness, edge-case
- [completion] (high, 2026-02-15) Successfully corrected ~35 passages across 4 documentation files (select-choice-fields-v05.md, text-fields-v05.md, component-reference.md, dynamic-forms-guide.md) with zero regex matches on verification sweep, producing clean 42,304-line reference.md ready for downstream use. | tags: documentation-maintenance, quality-assurance
- [decision] (high, 2026-02-15) Decided to investigate whether temperature and thinking level are additive (combining HIGH thinking + T=1.0 gives more diversity than either alone) or substitutable (they hit the same diversity ceiling). This requires a factorial experiment (2×3 or 3×3) at multiple thinking levels × temperatures with consensus evaluation within the existing consensus sweep framework. | tags: llm-diversity, temperature-parameter, thinking-level, experimental-design, factorial-design, consensus-evaluation
- [surprise] (high, 2026-02-15) HIGH thinking level unexpectedly outperformed lower thinking levels in diversity metrics during comparative analysis, contradicting earlier assumptions and prompting re-evaluation of the Obs 71 infrastructure decision about thinking level tuning. | tags: llm-diversity, thinking-level, model-behavior, belief-revision
- [self_reflection] (high, 2026-02-15) Claude reflected on the boundary between direct experience in current session instance versus summary context from earlier compacted conversation, noting that reasoning should be grounded in what happened in this instance (the comparison analysis, Obs 140, and to-do additions) rather than assuming full continuity. | tags: llm-continuity, instance-boundaries, epistemic-humility
- [error_mode] (high, 2026-02-15) Identified a pilot blind spot: evaluating model outputs under wrong conditions (e.g., using non-representative prompts or suboptimal parameter combinations during initial testing), which can lead to incorrect infrastructure decisions. Need to validate evaluation methodology before drawing conclusions. | tags: experimental-design, evaluation-methodology, validation, confound-control
- [pattern] (high, 2026-02-15) Established a reflection protocol with priority ordering: (1) session-reflection, (2) llm-observations, (3) working-notes, (4) abductive-reasoning [conditional], (5) session-log. Documents have priority fields that determine processing order at session end. | tags: system-process, documentation, workflow
- [decision] (high, 2026-02-15) Organized accumulated repository changes into 6 logical commits: (1) reference input sources rebuild, (2) 19 new field type design docs, (3) shared conditions doc, (4) fixes and link updates in existing docs, (5) Playwright spec with screenshots, (6) generated faims3-converted output. Rationale: grouping by logical connection and coupling (e.g., Playwright spec tightly coupled with screenshots) improves commit legibility and review clarity.
- [progress] (high, 2026-02-15) Successfully committed and pushed 8 commits (6 new logical batches plus 2 from previous session) to the field types documentation and automation repository. Work spans multiple sessions including new field type design docs, conditions.md with screenshots, Playwright spec expansions, and link updates across guides.
- [decision] (high, 2026-02-15) Thinking level (MINIMAL vs HIGH) functions as an experimental factor when consensus voting is the evaluation strategy, not a fixed infrastructure setting. This distinction emerged when Phase 3a strategy shifted from single-pass (Protocol A) to ensemble consensus (Protocol B), retroactively reframing what looked like a calibration parameter as a manipulable variable. | tags: llm-ensemble, consensus-voting, experimental-design, parameter-configuration
- [source_insight] (medium, 2026-02-15) Temperature and thinking level are mechanistically independent stochasticity axes (token sampling vs internal deliberation pathways) but functionally equivalent in their effect on consensus quality. They may be substitutable rather than additive when used for ensemble diversity generation. | tags: llm-ensemble, stochasticity, consensus-voting, parameter-interaction
- [limitation] (high, 2026-02-15) Early calibration pilots evaluated under single-pass protocol (T=0.0, K=1) are structurally incapable of detecting diversity effects that emerge in ensemble/consensus protocols. Changing downstream analytical strategy can invalidate prior calibration decisions. | tags: experimental-design, protocol-dependency, calibration, ensemble-methods
- [surprise] (high, 2026-02-15) HIGH thinking consensus outperforms MINIMAL by +6.8 pp F1 on Track 2 in Phase 3a because HIGH generates 3-4× more cluster diversity, which consensus voting can then filter into higher quality. The mechanism was invisible in single-pass calibration. | tags: llm-ensemble, consensus-voting, thinking-diversity, empirical-finding

## Key Decisions & Knowledge

- [architecture] (high, 2026-02-08) Time tracking system design: simple `logs/time.jsonl` with entries containing {project, task, minutes, activity_type, date}. Support both start/stop and manual entry via `/track` command. Weekly `/review` aggregates and formats hours per project. | tags: data-pipeline, time-tracking
- [architecture] (high, 2026-02-08) Prompt coaching system: review session transcripts from `~/.claude/projects/` to extract lessons. Store in `memories/` as `coaching_lesson` entries with tags for teaching content and observed improvement. Daily standup hook references yesterday's lesson and checks today's transcripts for evidence of application. | tags: llm-interaction, skill-development
- [architecture] (high, 2026-02-08) Preference capture mechanism: `/prefer` command writes entries to both a `system_friction` memory AND a staging area for batch review into CLAUDE.md. Consolidates preference logging and system design feedback into single action.
- [architecture] (high, 2026-02-08) Progressive disclosure for memories should follow skills tiering model: one-line synopsis (filter tier) → memory metadata/category/confidence (relevance tier) → full content (execution tier). Each tier loads only when previous tier signals relevance. Key design challenge: threshold logic for when to expand from synopsis to full text. | tags: information-architecture, memory-management
- [decision] (high, 2026-02-08) Skills documentation uses three-tier progressive disclosure: registry one-liner (filter), SKILL.md front matter (usage), full command files (execution). This model should inform memory grouping and disclosure — memories may benefit from clustering into thematic groups rather than remaining flat lists, with similar tier-based loading logic. | tags: information-architecture
- [decision] (high, 2026-02-08) User wants daily morning standup prompt coaching: review last 24h prompts (72h on Mondays), identify user's prompting errors, deliver one focused improvement lesson, then track if user improved next day. Start with prompting but expand later to Claude Code practices (skill usage, CLAUDE.md optimization, subagent invocation, hooks/agents). | tags: prompt-effectiveness, llm-interaction-improvement, coaching
- [system_evolution] (high, 2026-02-08) User proposes intentional friction tracking: create mechanism to record preferences for CLAUDE.md updates that get forgotten during sessions (e.g., preference for one task at a time vs. command chains during debugging). This feeds both system improvement and memory of patterns. | tags: system-friction, preferences, debugging-workflow
- [architecture] (medium, 2026-02-08) User proposes progressive disclosure for memory loading: store brief synopses/pointers to long-form memories in context, expanding full memory only when needed. Speculative idea applying UI progressive disclosure pattern to memory management for context efficiency. | tags: memory-architecture, context-efficiency, information-hierarchy
- [decision] (high, 2026-02-08) Implemented request governor that dynamically reduces concurrency when 429 errors occur, trading latency for reliability. At concurrency=1, API achieves 100% success rate even within stated quotas, indicating the dashboard limits are either advisory or not the actual bottleneck. This trade-off is acceptable for overnight batch processing. | tags: api, rate-limiting, concurrency-control, data-pipeline
- [decision] (high, 2026-02-08) Set API request concurrency to 1 for processing image-bearing requests against Google AI Studio. Trade-off accepts slower processing speed in exchange for reliability when underlying 429 errors occur for reasons outside documented quota limits. | tags: api, concurrency-control, error-resilience
- [limitation] (high, 2026-02-08) Google Cloud Monitoring API for rate limit telemetry is not available for AI Studio (only for Vertex AI). Dashboard view in Google AI Studio console is the best real-time visibility available for quota and capacity monitoring. | tags: api, monitoring, observability
- [decision] (high, 2026-02-08) Exit code 2 (partial failure) in Phase 2c is now accepted when ≤2 tiles fail per unit, rather than failing the entire unit. Rationale: K-35-053-3_Elenovo_x0_y2688.png consistently fails with JSON parse errors but other tiles in the batch succeed; full rejection was too harsh. | tags: error-handling, data-quality, fault-tolerance
- [error_mode] (high, 2026-02-08) Governor latency record accumulation threshold (5 records) was too high for tiles taking >60s to process, causing the pruning window (60s) to discard records before threshold reached. Fixed by reducing minimum records to 2 and separating latency_window_seconds to 5× TPM window (300s). | tags: governor, concurrency-control, metric-aggregation
- [prompt_effectiveness] (high, 2026-02-08) User's `/remember` command: 'Google Gemini 3 Flash API performance is highly variable, and we shouldn't try to guess the cause, but instead trust the governor in our scripts.' This reflects the pragmatic decision to delegate API behavior analysis to the governor's reactive mechanism rather than pre-emptive diagnosis. | tags: api-behavior, system-design-philosophy
- [architecture] (high, 2026-02-08) Governor now uses separate time windows for TPM ledger pruning (60s) and latency records pruning (300s) to prevent correlated pruning when tile processing times exceed base window. Minimum latency records threshold reduced to 2 from 5. | tags: governor, concurrency-control, system-design
- [error_mode] (high, 2026-02-08) Initial diagnosis attributed slow processing to poor API performance/governor issues; actually the slowness was caused by 429 retries with exponential backoff masking the underlying rate-limit issue. The governor was functioning correctly by reducing concurrency in response to legitimate 429 errors. | tags: api, error-diagnosis, retry-logic
- [prompt_effectiveness] (high, 2026-02-08) Diagnostic output from rate-limit governor (showing concurrency changes, TPM usage, and rate-limit reason codes) was effective in identifying that 429 errors were real, not imaginary, and triggered user to check actual quota status rather than dismissing the problem. | tags: prompt-effectiveness, diagnostic-output
- [error_mode] (high, 2026-02-08) Governor was stuck at concurrency=1 due to repeated 429 rate limit errors from the Gemini API. Each 429 triggered a rate_limit_event in the governor's deque, and these events persisted for 60 seconds. The governor correctly reduced concurrency from 3→2→1 in response, but once at minimum concurrency, couldn't recover because 429s continued, preventing any ramp-up logic from executing (Priority 1 rate_limited events always take precedence). | tags: api, rate-limiting, concurrency-control, retry-logic
- [decision] (high, 2026-02-08) Separated latency record pruning from TPM rate-limit window: latency window now 300s (5× the 60s TPM window) so that latency data persists long enough for the governor to accumulate ≥2 records and compute gap-proportional ramp-up, even for slow APIs. Reduced minimum_latency_records threshold from 5 to 2 to allow adjustments sooner. | tags: concurrency-control, api
- [limitation] (high, 2026-02-08) The Gemini API appears to enforce a much stricter rate limit than the advertised 1M TPM, possibly a free tier or per-project quota. Single worker sustained ~11.5K TPM but still triggered 429 errors after minutes, suggesting the actual quota is orders of magnitude lower. The governor cannot ramp above minimum concurrency if the API continuously rate-limits. | tags: api, rate-limiting
```

---

## B. Proposed System Output (Level 1 — Compact Index)

This is what the redesigned hook would inject:

```text
# Memory Index
# 150 memories loaded | Level 1 (compact)
# To retrieve full memory: query psql or use /recall [keyword]
# CC: when a topic matches these tags, fetch Level 2 and announce it.

## decision (28)
- #documentation #consistency #error-classification — Implemented three-way error classification for documentation correc... [2026-02-15]
- #llm-diversity #temperature-parameter #thinking-level — Decided to investigate whether temperature and thinking level are a... [2026-02-15]
- Organized accumulated repository changes into 6 logical commits: (1... [2026-02-15]
- #llm-ensemble #consensus-voting #experimental-design — Thinking level (MINIMAL vs HIGH) functions as an experimental facto... [2026-02-15]
- #documentation #ui-testing #screenshot-capture — Added a second screenshot showing the condition editor modal open w... [2026-02-15]
- #testing #documentation #naming-convention — Named Playwright screenshot tests with 'shared-NN' convention (e [2026-02-15]
- #git-workflow #code-organization — Split batch API governance implementation into 2 commits for clarit... [2026-02-15]
- #documentation #playwright #screenshot-testing — Adding a Playwright screenshot test for field conditions to the doc... [2026-02-15]
- #thinking-level #consensus-voting #comparative-analysis — Phase 3a comparative analysis design: analyze three parallel consen... [2026-02-15]
- #documentation #user-guide — Created `shared/conditions [2026-02-15]
- #documentation #link-validation #quality-assurance — Created a link audit prompt for documentation sets that uses `[TARG... [2026-02-15]
- #version-control #code-organization — Split implementation into two commits: (1) library layer with new g... [2026-02-15]
- #documentation #link-verification #quality-assurance — Executed a systematic 4-phase link audit on production/outputs/huma... [2026-02-15]
- #reproducibility #documentation #validation — Created a hardened prompt for link verification audits in Markdown ... [2026-02-15]
- #prompt-engineering #documentation-management #link-validation — User is building a reusable prompt (not one-time execution) to vali... [2026-02-15]
- #data-pipeline #resource-management #quota-handling — Implemented three-part Batch API File Storage Governance system: (1... [2026-02-15]
- #quota-management #data-pipeline — Implemented cleanup-on-completion logic to free input and output fi... [2026-02-15]
- #prompt-engineering #llm-optimization #escape-hatch-closure — Adopted 'Systematic Prompt Hardening' skill with 16 field-tested an... [2026-02-15]
- #field-method #instrument-design #data-quality — In Fieldmark data collector documentation, clarified that device ra... [2026-02-15]
- #file-storage #quota-management #pipeline-optimization — Implemented file storage governance with completion cleanup (delete... [2026-02-15]
- #resource-management #quota-handling #api-governance — Chose functional approach for file storage governance (three statel... [2026-02-15]
- #checkpoint-evolution #backward-compatibility — Backward compatibility achieved in checkpoints without migration: n... [2026-02-15]
- #documentation #naming-consistency #field-type — Renamed 'Unique ID' field type to 'Auto Incrementing Field' through... [2026-02-15]
- #planning #quota-management — A revised plan with three proposed changes was drafted to handle qu... [2026-02-15]
- #batch-api #quota-management #api-limits — Discovered file_storage_bytes quota (20 GB limit) as a separate bot... [2026-02-15]
- #scope-management #prioritization — Scope of corrections limited to 4 files (`select-choice-fields-v05 [2026-02-15]
- #batch-api #quota-governance #architecture — Design a FileStorageGovernor class (modeled on TokenBucketGovernor)... [2026-02-15]
- #component-selection #field-categories #ux-guidance — Standardised option-count threshold for RadioGroup vs Select compon... [2026-02-15]

## architecture (18)
- #data-pipeline #comparative-analysis — Project uses a two-track comparison structure (Track 1 and Track 2)... [2026-02-15]
- #playwright #screenshot-testing #test-architecture — Playwright screenshot spec uses a shared elements describe block fo... [2026-02-15]
- #batch-api #data-pipeline #file-format — Detection file loading is compatible across both pipeline versions:... [2026-02-15]
- #documentation-strategy #progressive-disclosure — Condition operators implemented with regex variants (`contains-rege... [2026-02-15]
- #api-design #code-review #testing-strategy — Git commit strategy: split changes along library/consumer boundary [2026-02-15]
- #data-pipeline #file-management #batch-processing — Implemented file storage governance system for batch API: cleanup-o... [2026-02-15]
- #documentation-architecture #audit-methodology #reusable-templates — Link audit prompt uses placeholder-based approach (`[TARGET DIRECTO... [2026-02-15]
- The grimoire exists at ~/personal-assistant/notes/grimoire [2026-02-15]
- #prompt-engineering #system-design #knowledge-management — Grimoire system stores reusable prompts at ~/personal-assistant/gri... [2026-02-15]
- #data-pipeline #api-integration #resource-management — Extended lib_batch_api [2026-02-15]
- #data-pipeline #quota-management #etl — Two-track job submission system: Track 1 handles image data (larger... [2026-02-15]
- #prompt-engineering #workflow-design #progressive-disclosure — Prompt improvement workflow uses 5-phase progressive disclosure: Ph... [2026-02-15]
- #offline-first #data-collection #identifier-management — Fieldmark auto-incrementer design: ranges are user-configurable per... [2026-02-15]
- #data-pipeline #file-storage #batch-processing — Two-track batch processing architecture: Track 1 (image JSONL, ~160... [2026-02-15]
- #api-design #breaking-change #checkpoint-evolution — Modified submit_batch_unit() to return tuple[str, str] (job_name, u... [2026-02-15]
- #batch-api #quota-management #resource-governance — Plan developed for Batch API File Storage Governance system to hand... [2026-02-15]
- #documentation #build-process #system-design — Documentation build uses source files (`*-v05 [2026-02-15]
- #batch-api #architecture #file-tracking — Current batch pipeline (lib_batch_api [2026-02-15]

## methodology (4)
- #verification #search-strategy #documentation-audit — Verification regex sweep catches documentation instances missed by ... [2026-02-15]
- #experimental-design #consensus-voting #temperature-sampling — Pilot evaluation of thinking levels at T=0 [2026-02-15]
- #consensus-voting #ensemble-method #temperature-sampling — Consensus approach uses voting across multiple temperature-sampled ... [2026-02-15]
- #documentation-process #batch-correction #quality-assurance — Three-phase inventory-before-fixing approach for large-scale docume... [2026-02-15]

## hypothesis (1)
- #consensus-voting #ensemble-method — Detection clustering strategy: majority-vote consensus filtering le... [2026-02-15]

## limitation (3)
- #experimental-design #protocol-dependency #calibration — Early calibration pilots evaluated under single-pass protocol (T=0 [2026-02-15]
- #modality-comparison #image-understanding #scope-boundary — Cross-modality performance gap: Track 1 Image HIGH (F1=0 [2026-02-15]
- #batch-api #gemini-api #error-handling — Known Gemini Batch API limitation (#1759): output file IDs may exce... [2026-02-15]

## source_insight (6)
- #llm-ensemble #stochasticity #consensus-voting — Temperature and thinking level are mechanistically independent stoc... [2026-02-15]
- #bias-variance-tradeoff #ensemble-methods #model-behavior — High thinking level functions analogously to high temperature in in... [2026-02-15]
- #validation #statistical-analysis #sampling — Tile-level bootstrap resampling (K=1000) produces wide confidence i... [2026-02-15]
- #prompt-engineering #task-classification #technique-application — Prompt improvement workflow uses task-type classification (e [2026-02-15]
- #batch-api #file-lifecycle #gemini-api — Input files can be safely deleted once a batch job transitions to R... [2026-02-15]
- #documentation-generation #error-propagation #technical-writing — RadioGroup deprecation language was concentrated in a single source... [2026-02-15]

## error_mode (10)
- #experimental-design #evaluation-methodology #validation — Identified a pilot blind spot: evaluating model outputs under wrong... [2026-02-15]
- #markdown #syntax-error #documentation — Multi-line alt text in Markdown image syntax breaks rendering [2026-02-15]
- #debugging #troubleshooting-logic — Claude assumed test screenshot discrepancy (showing 'ADD CONDITION'... [2026-02-15]
- Claude assumed a notebook was closed/unavailable when user reported... [2026-02-15]
- #form-interaction #state-persistence #ui-state — User attempted to save a condition configuration in what appears to... [2026-02-15]
- #metadata-accuracy #thinking-level #config-management — High-thinking tracks (track1-image-high, track2-text-high) have met... [2026-02-15]
- #testing #type-safety — Test callback signatures required updating after changing submit_ba... [2026-02-15]
- #etl — Background task tool default timeout or system resource limit appea... [2026-02-15]
- #documentation #assumption-testing — Claude assumed users received pre-assigned ranges from the system r... [2026-02-15]
- #documentation #search-replace #completeness — Residual deprecation labels found during verification in `select-ch... [2026-02-15]

## surprise (5)
- #llm-diversity #thinking-level #model-behavior — HIGH thinking level unexpectedly outperformed lower thinking levels... [2026-02-15]
- #llm-ensemble #consensus-voting #thinking-diversity — HIGH thinking consensus outperforms MINIMAL by +6 [2026-02-15]
- #ensemble-methods #temperature-sampling #consensus-voting — Consensus voting with high thinking and elevated temperature produc... [2026-02-15]
- #consensus-voting #prompt-effectiveness #model-behavior — HIGH thinking mode dramatically outperforms MINIMAL for consensus v... [2026-02-15]
- #documentation-quality #constraint-validation — Designer preview for RadioGroup field actually works correctly — th... [2026-02-15]

## self_reflection (1)
- #llm-continuity #instance-boundaries #epistemic-humility — Claude reflected on the boundary between direct experience in curre... [2026-02-15]

## prompt_effectiveness (5)
- #prompt-engineering #quality-assessment #documentation-validation — Original seed prompt for link validation scored 16/50 across five d... [2026-02-15]
- #documentation #user-centered-design #clarification-workflow — Clarification requests mid-revision are essential for accuracy [2026-02-15]
- #technical-writing #clarity #user-documentation — User asked for readability improvements to two technical bullet poi... [2026-02-15]
- #prompt-clarity #task-specification — Structured line-by-line document review with explicit character-cou... [2026-02-15]
- #prompt-engineering #constraint-specification #error-prevention — Multi-layered prompt hardening with explicit ground truth declarati... [2026-02-15]

## system_success (1)
- #testing #integration — The new file storage governance system passed all 77 tests on first... [2026-02-15]

## pattern (9)
- #system-process #documentation #workflow — Established a reflection protocol with priority ordering: (1) sessi... [2026-02-15]
- #performance-tradeoff #ensemble-methods #optimization-strategy — Emerging pattern: deterministic configurations (low thinking, low t... [2026-02-15]
- #validation #documentation — Link verification audits follow a three-phase structure: Phase 1 (I... [2026-02-15]
- #quota-management #data-pipeline #optimization — Quota-aware submission pattern: submit text-only jobs first (smalle... [2026-02-15]
- #prompt-engineering #quality-assurance #output-validation — Prompt hardening uses 5-dimension quality scoring: Clarity (goal am... [2026-02-15]
- #callback-design #coordinator-pattern — Three-argument on_submit callback pattern: (job_name, tile_keys, up... [2026-02-15]
- #documentation #quality-assurance #markdown — User is systematically reviewing markdown documentation files in pr... [2026-02-15]
- #documentation #quality-assurance #workflow — Multi-file documentation corrections benefit from: (1) targeted edi... [2026-02-15]
- #documentation #quality-assurance — User requests document review for line-length compliance (100-chara... [2026-02-15]

## gotcha (23)
- #documentation #search-completeness #edge-case — Deprecation and validation language can hide in code blocks and cro... [2026-02-15]
- #file-structure #relative-paths #documentation-build — Relative path depth for images varies based on file nesting level [2026-02-15]
- #debugging #environment-config #form-state — When debugging conditional field visibility in Fieldmark notebooks,... [2026-02-15]
- #data-pipeline #validation — Read-only notebook state ('Closed: Notebook is read-only') may sile... [2026-02-15]
- #ui-debugging #form-state — When troubleshooting form field conditions, verify that the conditi... [2026-02-15]
- #testing #screenshot-capture #state-persistence — Screenshot test captured the field without a saved condition despit... [2026-02-15]
- #batch-api #file-governance #error-handling — Issue #1759 (file IDs >40 chars) caused consistent output file dele... [2026-02-15]
- #data-pipeline #batch-api #file-management — Bug #1759 (file deletion failure for IDs > 40 chars) is universal f... [2026-02-15]
- #form-validation #conditional-logic #ux-issue — Conditional field with Required constraint creates gotcha: field ap... [2026-02-15]
- #regex #parsing #markdown — Markdown link regex patterns can produce false positives when paren... [2026-02-15]
- #api-limits #file-management #known-issues — File ID length limitation (bug #1759) prevents deletion of output f... [2026-02-15]
- #file-size #base64-encoding #storage-quota — Track 1 image processing with base64-encoded tiles creates very lar... [2026-02-15]
- #regex-parsing #markdown-processing #text-extraction — Markdown link extraction regex is prone to false positives when lin... [2026-02-15]
- #prompt-engineering #error-mode #review-tasks — Link validation prompt is susceptible to satisficing trap: model re... [2026-02-15]
- #tooling #testing — ruff linting tool not found in PATH—must explicitly invoke as [2026-02-15]
- #etl #monitoring — Python stdout buffering when redirected to file causes misleading p... [2026-02-15]
- #field-method #data-pipeline #edge-case — Fieldmark auto-incrementer ranges cannot be edited once created on ... [2026-02-15]
- #technical-writing #precision #documentation-patterns — Technical documentation can conflate capability with limitation: sa... [2026-02-15]
- #api-quirks #mocking-strategy #error-handling — files [2026-02-15]
- #documentation #naming-consistency — When renaming field type documentation, must distinguish between th... [2026-02-15]
- #markdown #linting — Markdown table lines are typically exempt from line-length linting ... [2026-02-15]
- #data-pipeline #etl #documentation — Cascade correction pattern identified: errors in source file `selec... [2026-02-15]
- #batch-api #file-storage #quota-management — Gemini Batch API file storage quota (20 GB) counts both input AND o... [2026-02-15]

## progress (25)
- Successfully committed and pushed 8 commits (6 new logical batches ... [2026-02-15]
- #documentation #testing — Fixed image tag rendering issue (single-line formatting) [2026-02-15]
- #batch-processing #storage-management — Track 1 MINIMAL (image) batch processing remains in background with... [2026-02-15]
- #testing — All 31 Playwright tests in field-types-design [2026-02-15]
- #data-pipeline #batch-processing — Track 2 MINIMAL consensus analysis completed and incorporated into ... [2026-02-15]
- #consensus-voting #data-pipeline #validation — Track 1 MINIMAL image analysis: 34/90 jobs completed, 41 pending [2026-02-15]
- #pipeline-progress #checkpoint-tracking — Track 1 MINIMAL (image) background job progressed from 28 pending t... [2026-02-15]
- #consensus-voting #phase3a — Phase 3a consensus analysis completed for all three requested track... [2026-02-15]
- #documentation — Documentation link from `shared/field-options [2026-02-15]
- #documentation-audit — Link audit of production/outputs/human-readable/field-types/design ... [2026-02-15]
- #pipeline-execution #file-management #error-handling — Track 2 (text-only pipeline) completed successfully: 90/90 units pr... [2026-02-15]
- #pipeline-execution #batch-processing #error-tracking — Track 1 (image pipeline) mid-execution: Phase 1 complete with all 5... [2026-02-15]
- #batch-processing #progress-tracking — Track 2 (text): 65/90 completed, 25 pending in batch, all jobs subm... [2026-02-15]
- #progress-tracking #batch-processing — Track 2 (text-only): all 25 new batch jobs submitted successfully w... [2026-02-15]
- #data-pipeline — Track 2 progress before termination: 25/25 JSONL files built, 9/25 ... [2026-02-15]
- #data-pipeline #job-management #quota-management — Track 1 and Track 2 monitoring completed successfully [2026-02-15]
- #monitoring #automation — Background monitoring task for 'Track 1 (unbuffered)' completed suc... [2026-02-15]
- #implementation-complete #testing-verified — Successfully implemented Batch API File Storage Governance: added 3... [2026-02-15]
- #documentation #quality — Fixed spelling errors in auto-incrementing-field [2026-02-15]
- #storage-management #cleanup — File cleanup task completed successfully, deleting 151 old files an... [2026-02-15]
- #planning #analysis — Codebase exploration and research agent tasks both completed with c... [2026-02-15]
- #documentation — Documentation review underway: field-types/design/templated-string [2026-02-15]
- #batch-api #quota-management — Freed 4 [2026-02-15]
- #batch-api #research-methodology — Two research agents launched in parallel to investigate solutions: ... [2026-02-15]
- #batch-processing #quota-management — Track 1: 34/90 completed (56 failed with quota errors, need resubmi... [2026-02-15]

## context (7)
- #consensus-analysis #thinking-level #performance-comparison — Comparative analysis of three consensus tracks reveals thinking lev... [2026-02-15]
- #experiment-design #metadata #tracking — Four comparison tracks exist: track1-image (MINIMAL), track1-image-... [2026-02-15]
- #documentation #field-conditions #conditional-logic — The conditions [2026-02-15]
- #phase3a #track-status — Track 1 (image) with MINIMAL thinking is still in progress (34 comp... [2026-02-15]
- #documentation-validation #cross-reference-management — Documentation directory structure: production/outputs/human-readabl... [2026-02-15]
- #project-infrastructure — User has an active project at /home/shawn/Code/map-reader-llm with ... [2026-02-15]
- #documentation #architecture — faims3-converted directory contains generated files from human-read... [2026-02-15]

## completion (1)
- #documentation-maintenance #quality-assurance — Successfully corrected ~35 passages across 4 documentation files (s... [2026-02-15]

## blocker_real (3)
- #documentation-completeness #broken-links #content-planning — One broken link cannot be fixed immediately: shared/field-options [2026-02-15]
- #data-pipeline #etl — Resume run for both tracks exited prematurely: Track 2 stopped afte... [2026-02-15]
- #quota-management #resource-constraint #infrastructure — Track 1 and Track 2 resume tasks both failed due to file_storage_by... [2026-02-15]

```

---

## C. Level 2 Retrieval Example

When CC recognises a topic match (e.g., user mentions PostgreSQL), it would:

1. Announce: "I have memories about PostgreSQL and database architecture. Retrieving details..."
2. Run a query (PostgreSQL or JSONL grep)
3. Inject the full memories into the conversation:

```text
## Retrieved Memories: postgresql

[architecture] (high, 2026-02-07) id:2026-02-07-63d0aaabd427
Phase 2 will implement PostgreSQL query infrastructure. Phase 3 will add task system with /standup, /capture, /done, /focus commands.
Tags: open-code
Session: 82b25d45...

[architecture] (high, 2026-02-07) id:2026-02-07-e1a36da94cc8
Memory system architecture has three phases: Phase 1 (extraction/injection hooks, slash commands /recall and /remember), Phase 2 (PostgreSQL setup on sapphire server with sync script), Phase 3 (task system with /standup, /capture, /done, /focus commands and SessionStart accountability hook).
Session: 82b25d45...

[decision] (high, 2026-02-07) id:2026-02-07-8d10600827c5
Personal assistant memory system uses /recall for keyword-based search and /remember for manual memory capture, with both reading/writing to ~/personal-assistant/memories/memories.jsonl. Extraction hook handles automatic capture; Phase 2 will add semantic search via PostgreSQL.
Tags: memory-system, architecture
Session: 82b25d45...

[decision] (high, 2026-02-07) id:2026-02-07-12d3bfba935e
Phase 3 (task system with /standup, /capture, /done, /focus) prioritized over Phase 2 (PostgreSQL) due to time pressure on LLM-History-Paper and fieldmark-docs deliverables.
Tags: project-planning, prioritization
Session: ceac677e...

[decision] (high, 2026-02-07) id:2026-02-07-bc10c3e6a88e
Phase 3 (task system) can be implemented before Phase 2 (PostgreSQL) without complications. Phase 3 is entirely markdown-based (/standup, /capture, /done, /focus commands using FOCUS.md, inbox.md, waiting-for.md) and has no database dependencies. Phase 2's database value is primarily for richer queries on memories, which is separate from task system functionality.
Tags: architecture, dependency-management
Session: ceac677e...

```

---

## D. Level 3 Retrieval Example

If deeper context is needed, CC would ask:

> "The PostgreSQL decision was made in session `82b25d45...` on 2026-02-07.
> I can retrieve the full conversation section where this was discussed.
> This will use approximately 3-5K tokens of context. Retrieve it?"

If approved, CC would:
1. Look up `archive_path` from `sessions` table
2. Decompress the archived transcript
3. Search for relevant exchanges (using `source_messages` UUIDs or content matching)
4. Extract a window of 10-20 exchanges around the relevant section
5. Inject into conversation context
