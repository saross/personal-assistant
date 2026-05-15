# Memory Corpus Audit — 2026-05-14

Read-only adversarial audit of `~/personal-assistant/memories/memories.jsonl`.
No files were modified. The goal was to quantify confabulation (confidently
stated but false specifics) and structural unverifiability in the auto-extracted
memory corpus.

## 1. Headline numbers

- **Corpus size:** 25,581 entries (0 parse errors), spanning 2025-11-20 to
  2026-05-14.
- **Unverifiable by construction:** Only **46.8%** of entries carry *any*
  mechanical re-verification anchor (file path, filename, plausible git hash,
  line reference, or Zotero key). The majority — **~53%** — cannot be
  mechanically re-checked at all. `session_id` was excluded as an anchor because
  transcripts rotate.
- **Confabulation rate (deep sample):** 5 of 400 sampled entries (**1.2%**) cite
  a file, identifier, or count that does not exist and per git history never
  did. **Caveat:** n=400, stratified and weighted (not a simple random sample),
  so the 95% interval on the true corpus-wide rate is roughly 0.4–2.9%. The rate
  among entries that actually make a checkable specific claim is higher (5 of
  ~115 checkable-claim entries, ~4%).
- **Drift rate:** 6 of 400 (**1.5%**) — all in the oldest cohort, all from one
  relocated/repurposed project (`inscriptions`). Staleness, not invention.
- **Verified:** 104 of 400 (26.0%) had at least one anchor token confirmed
  against the filesystem or git history.
- **Confidence inflation:** 93.1% of the entire corpus is tagged
  `confidence: high` (23,817 / 25,581); only 2 entries are `low`. The
  `confidence` field carries almost no signal — every confabulation found was
  tagged `high`.

## 2. Tier A — structural audit (all 25,581 entries)

### Counts by source

| Source | Count | % |
|---|---|---|
| extraction | 23,788 | 93.0% |
| reprocessing | 1,636 | 6.4% |
| manual | 157 | 0.6% |

### Counts by category (valid set)

| Category | Count | Category | Count |
|---|---|---|---|
| decision | 5,554 | methodology | 637 |
| progress | 4,265 | limitation | 650 |
| gotcha | 2,595 | surprise | 342 |
| architecture | 2,410 | self_reflection | 323 |
| commitment | 1,734 | hypothesis | 294 |
| context | 1,376 | waiting_for | 273 |
| pattern | 1,202 | completion | 250 |
| source_insight | 1,021 | provenance | 216 |
| error_mode | 871 | blocker_real | 195 |
| prompt_effectiveness | 738 | system_success | 173 |
| | | system_evolution | 138 |
| | | system_friction | 116 |
| | | openness | 94 |
| | | ethics | 37 |
| | | contact | 35 |
| | | blocker_excuse | 20 |
| | | slip | 16 |

### Field completeness

- **`source_context` non-empty:** 18,460 / 25,581 = **72.2%**.
- **`summary` non-empty:** 25,578 / 25,581 = **100.0%** (3 missing).

### Anchor analysis (the key structural metric)

| Anchor type | Entries | % of corpus |
|---|---|---|
| Any anchor (path / filename / git hash / line ref / Zotero key) | 11,979 | **46.8%** |
| Path or filename token | 11,227 | 43.9% |
| Plausible git-hash mention (7–12 hex, mixed alpha+digit) | 918 | 3.6% |
| Line-number reference | 829 | 3.2% |
| `zotero_key` populated | 32 | 0.1% |

**Interpretation:** more than half the corpus makes claims with nothing
concrete enough to grep, git-show, or stat. This is the dominant structural
weakness — not active confabulation, but a corpus that *cannot be policed*
because the extraction step records conclusions without locators.

### Category validity

The valid set holds. **6 entries carry out-of-set categories** — all
`source: manual` (user-authored, not extraction artefacts):

| ID | Category | Project |
|---|---|---|
| `2026-03-13-31a93d5dbf2f` | feedback | fieldmark-docs-staging |
| `2026-03-14-943dcd40eb2c` | feedback | map-reader-llm |
| `2026-03-15-bae8d5c327d2` | feedback | map-reader-llm |
| `2026-03-24-704f57cb5049` | feedback | map-reader-llm |
| `2026-04-08-e268ab11ec62` | feedback | personal-assistant |
| `2026-04-18-f9944e9bf2a3` | preference | personal-assistant |

These are not extraction errors — they are deliberate user captures using
category labels (`feedback`, `preference`) that were never added to the schema.
The fix is a schema decision, not a data cleanup.

### Duplication

Grouping by the normalised first 80 characters of `content`: **19 near-duplicate
groups**, accounting for **20 redundant entries (0.1%)**. Duplication is *not* a
material problem in this corpus — re-extraction across sessions produces
different phrasings, not byte-identical leads. The few real repeats are
high-value recurring rules (e.g. the sapphire-compute rule, the paired
permutation test).

### Growth by month

| Month | Entries |
|---|---|
| 2025-11 | 301 |
| 2025-12 | 402 |
| 2026-01 | 673 |
| 2026-02 | 6,022 |
| 2026-03 | 6,733 |
| 2026-04 | 9,356 |
| 2026-05 (partial) | 2,094 |

Extraction volume jumped ~9× between January and February 2026 and has stayed
high. April 2026 alone produced more memories than all of 2025. Whatever
extraction-hook change landed around Feb 2026 turned the corpus into a
high-volume firehose; the audit findings below should be read against that
volume (a 1.2% confabulation rate on ~9,000 April entries is ~108 bad entries
in one month).

## 3. Tier B — confabulation deep-dive

### Sample construction

400 entries, stratified and weighted (seed 42, weighted draw without
replacement). Weights favoured: the oldest cohort (×4), the post-4.7 cohort
(×2.5), the six checkable-specifics categories (×2), entries whose text contains
a concrete token (×2.5), and `extraction` source (×1.2). Realised composition:

- **By age bucket:** oldest (2025-11..2026-01) n=35; mid (2026-02..03) n=117;
  post-4.7 (2026-04..05) n=248. The oldest bucket is small because only 1,376
  corpus entries predate February 2026 — 35 is already 2.5% of that stratum.
- **By category:** decision 102, progress 96, architecture 54, gotcha 42,
  context 15, commitment 15, the rest in single digits.
- **Concrete-token entries:** 298 / 400.

Verification method: decoded each `project` field to a repo path, indexed every
repo's current files and full `git log --all` history, then checked filename
tokens, path tokens, and git hashes mechanically. NOTFOUND candidates and all
hash mismatches were inspected by hand (regex over-matches prose, so raw
NOTFOUND counts were not trusted). VAGUE/UNVERIFIABLE entries with no anchor
token were classified by a prose-specificity heuristic and a spot-read of 18.

### Classification results (n=400)

| Verdict | Count | % |
|---|---|---|
| UNVERIFIABLE | 236 | 59.0% |
| VERIFIED | 104 | 26.0% |
| VAGUE | 49 | 12.2% |
| DRIFT | 6 | 1.5% |
| CONFABULATION | 5 | 1.2% |

**The headline is not the confabulation rate — it is the 59% UNVERIFIABLE
rate.** These are entries that assert checkable specifics (counts, "pushed
commit", "completed N runs", named decisions) but provide no anchor to check
them against. They are not provably wrong; they are *unauditable*. Combined with
the structural anchor analysis (53% of the whole corpus), this is the
corpus-defining problem.

### By age bucket — does post-4.7 confabulate more?

| Bucket | n | VERIFIED | UNVERIFIABLE | VAGUE | DRIFT | CONFAB | Confab rate |
|---|---|---|---|---|---|---|---|
| oldest (2025-11..2026-01) | 35 | 5 | 17 | 5 | 6 | 2 | **5.7%** |
| mid (2026-02..03) | 117 | 28 | 74 | 15 | 0 | 0 | **0.0%** |
| post-4.7 (2026-04..05) | 248 | 71 | 145 | 29 | 0 | 3 | **1.2%** |

**Answer to the key question: no, the post-4.7 cohort does not confabulate more
than older cohorts in this sample.** The oldest cohort has the highest
confabulation *rate* (2/35), and the only DRIFT cases. The post-4.7 cohort's
rate (3/248, 1.2%) is *lower* than the oldest cohort's. Two caveats:

1. The oldest bucket is small (n=35) — its 5.7% rate has a wide interval
   (roughly 1–19%). The difference between buckets is not statistically robust
   at these sample sizes.
2. The *kind* of error differs. Old-cohort errors are about a relocated project
   (mostly reclassifiable as DRIFT). Post-4.7 errors are cleaner inventions —
   named files asserted as existing-and-documented (`feedback_flex_mode.md`,
   `obs-writer.md`, `sapphire-zbook-cleanup-comparison.md`) that never existed.
   This matches the Opus 4.7 "states invented identifiers with conviction"
   concern, even though the raw rate is not elevated.

The more important post-4.7 signal is **volume**: 1.2% of ~11,450 post-4.7
entries is ~135 confabulated entries, versus ~30 in the entire pre-February
corpus.

### By category

| Category | n | VERIFIED | UNVERIFIABLE | VAGUE | DRIFT | CONFAB |
|---|---|---|---|---|---|---|
| decision | 102 | 23 | 67 | 11 | 0 | 1 |
| progress | 96 | 29 | 63 | 3 | 0 | 1 |
| architecture | 54 | 17 | 24 | 8 | 4 | 1 |
| gotcha | 42 | 15 | 20 | 7 | 0 | 0 |
| limitation | 8 | 1 | 4 | 3 | 0 | 0 |
| provenance | 6 | 1 | 3 | 0 | 2 | 0 |

`architecture` is the highest-risk category: it carries both the DRIFT cluster
and a confabulation, and it is where invented "system structure" claims land.
`decision` and `progress` are overwhelmingly UNVERIFIABLE — they assert that
things happened without recording where to look.

## 4. Failure-mode taxonomy

### Mode A — Invented file asserted as existing-and-documented

The most dangerous mode: a memory states that a named file exists and describes
its contents or "contract", when no such file exists in the filesystem or
anywhere in git history. Concentrated in the post-4.7 cohort.

- `2026-05-06-fd17a25992f6` (decision, map-reader-llm): *"Pro-tier fallback
  documented in `feedback_flex_mode.md`: if flex mode returns 503, use
  `--service-tier standard` flag."* — No file matching `*flex_mode*` or
  `*flex-mode*` exists in the repo or its history. The underlying API fact may
  be true; the documented-file locus is invented.
- `2026-04-28-b01e31031cb9` (progress, map-reader-llm): *"Fallback agent met
  obs-writer.md contract fully: re-read source reports for citations, passed
  collision check, used 6-section template..."* — No `obs-writer.md` anywhere
  in the repo or history. (Note: the commit hash `88c17581` in the *same* entry
  *does* verify — a true-fact + invented-file compound.)
- `2026-05-12-100089ec4dcb` (commitment, map-reader-llm): *"review
  results/sapphire-zbook-cleanup-comparison.md § Key finding and §
  Interpretation..."* — No `sapphire-zbook*` file in fs or history.

### Mode B — Invented precise counts / line numbers attached to a real concept

A real artefact or concept, welded to a fabricated quantitative specific.

- `2026-01-18-b8cb507b6370` (pattern, fieldmark-docs-staging): *"Standardized to
  'General User' per codebase naming (model.ts line 865)."* — No `model.ts`
  exists in the docs-staging repo or its history (it is a FAIMS3-codebase file,
  a different repository). The terminology-standardisation decision is real; the
  "model.ts line 865" citation is invented for this project.
- `2026-01-14-a26bf80f976a` (architecture, llm-reproducibility): *"Extraction.json
  contains 27 evidence items, 24 claims, 7 implicit arguments, 6 designs, 6
  methods, 12 protocols."* — No file named `Extraction.json` exists; the
  lowercase `extraction.json` files that do exist carry entirely different
  counts (the crema run has 10 evidence / 8 claims / 2 implicit / 3 designs /
  4 methods / 7 protocols). The cited six-number tuple matches no file checked.

### Mode C — Project drift (stale, not invented)

The claim was plausibly true when written, but the referenced workspace has
since been relocated or repurposed. All six DRIFT cases are 2025-11/2025-12
entries tagged `project: -home-shawn-Code-inscriptions`, referencing extraction
scripts and CSVs (`extract_roles_kaz2010.py`, `Name-mapping.csv`,
`attribution.csv`, `qa-guidance.md`, `qa-corrections-manifest-comprehensive.json`)
that do not exist in the *current* `inscriptions` repo or its history — because
that repo is a 2023 project (first commit 2023-08-26) that was repurposed for a
different inscriptions analysis in April 2026. The 2025 fieldwork-extraction
workspace these memories describe is no longer at a discoverable path.

- `2025-11-21-94a5096b52ed` (architecture): *"Created multiple extraction
  scripts... extract_roles_kaz2010.py, extract_roles_kaz2011.py..."*
- `2025-11-23-70c617beefc2` (provenance): *"Corrected
  scripts/extract_kazanluk_2009.py, increasing coverage from 200/269 to
  202/269 (75.1%)."*
- `2025-12-05-b2cd34b0ac74` (provenance): *"removed 6-digit mountain survey
  record (300030-300033) from attribution.csv... Attribution.csv is now clean
  data only."*

These are *not* confabulations — they are the predicted staleness failure. But
they are now indistinguishable from confabulation without external knowledge,
which is itself the problem.

### Mode D — Cross-repo hash (verifiable, but not where the entry says to look)

Not a confabulation, but a structural trap: the `project` field encodes the
session cwd, yet the cited commit lives in a *sibling* repo. Five sampled
entries cited hashes that fail in the cwd repo but resolve cleanly elsewhere:
`280bce8` (tagged `personal-assistant`, actually in `ANU-HUMN8031-2026`),
`afffd34`/`35dc3a8` (in the `pa-data` submodule), `ac2df9f` (in
`~/Code/talks/ardc-2026`), `f3cec15d` (an orphan session id, not a commit at
all). An automated verifier that trusts the `project` field would false-flag
all of these.

### Mode E — Asserted-action with no locator (the bulk: UNVERIFIABLE)

Not quotable as a single failure but the 236-entry majority mode: *"All changes
committed and pushed to origin"*, *"completed audit corrections across 8
reference source files"*, *"consensus building (78 conditions via script)"* —
specific, plausible, and completely unauditable because no path, hash, or run
directory is recorded. Examples: `2026-02-12-a7c055f4f300`,
`2026-04-17-97c60c541c6f`, `2026-04-30-46186b93e28e`.

## 5. Recommendations (ranked)

1. **Add a mandatory anchor field to the extraction schema.** The single
   highest-leverage change. Require the extractor to populate an `anchors`
   array (file paths, git hashes, run-directory names) for any entry in
   `decision`, `progress`, `architecture`, `gotcha`, `provenance`, or
   `completion`. If the transcript contains no anchor, the entry should be
   downgraded or dropped — not stored as a high-confidence unauditable claim.
   This attacks the 53%-of-corpus / 59%-of-sample UNVERIFIABLE problem directly,
   which dwarfs the confabulation problem.

2. **Add a post-extraction verification pass.** Before an extracted memory is
   committed, run a cheap mechanical check: do the cited filenames/paths exist
   in the repo (current *or* git history)? Do the cited hashes resolve *in any
   repo under `~/Code` plus the `pa-data` submodule*, not just the cwd repo
   (Mode D)? Flag failures for review rather than storing silently. This would
   have caught all five sampled confabulations and prevented the cross-repo
   false-negatives.

3. **Stop trusting the `confidence` field — or make it mean something.** 93% of
   the corpus is `confidence: high`, including every confabulation found. The
   field is decorative. Either bind `high` to "anchor present and
   self-consistent" or remove it.

4. **Fix the `project` → repo decode and handle sibling repos.** The `project`
   field encodes cwd, but commits and files are routinely in submodules or
   sibling repos. Any verifier must search a repo set, not a single decoded
   path. Separately, the `inscriptions` project code now points to a repurposed
   2023 repo — the Nov/Dec 2025 entries under that code are mis-attributed and
   should be re-tagged or archived.

5. **Resolve the `feedback` / `preference` categories.** Six manual entries use
   out-of-schema categories. Either add them to the valid set (they are
   coherent and useful) or re-categorise. Cheap, one-time.

6. **Treat extraction volume as a risk multiplier.** April 2026 produced ~9,300
   entries. At a 1.2% confabulation rate that is ~110 false specifics per month,
   and at a 59% unverifiable rate, ~5,500 unauditable entries per month. Volume
   throttling, or stricter inclusion conditions, would reduce absolute error
   load even if the *rate* stays constant.

7. **Periodic drift sweep.** Re-run the anchor-existence check across the whole
   corpus quarterly. Entries whose anchors have since disappeared should be
   marked `DRIFT` (stale) rather than silently rotting into indistinguishable-
   from-confabulation status — which is exactly what happened to the
   `inscriptions` cluster.

## Methodological honesty notes

- The 400-entry sample is **weighted, not random** — rates here are not direct
  estimates of corpus-wide rates. The weighting deliberately over-sampled
  old/recent/concrete/checkable-category entries, i.e. the strata *most* likely
  to contain confabulations. The true corpus-wide confabulation rate is
  therefore probably *lower* than 1.2%, but the absolute count is still large
  because the corpus is large.
- VERIFIED means **the anchor token was confirmed to exist** (file present, or
  hash resolves). For ~10 spot-checked VERIFIED entries the surrounding compound
  claim also held up, but a full compound-claim verification of all 104 was not
  done — some VERIFIED entries could still contain a Mode-B welded falsehood
  around a real anchor.
- The UNVERIFIABLE/VAGUE split rests on a prose-specificity heuristic plus an
  18-entry calibration read, not a full manual classification of all 285. The
  boundary is fuzzy; the combined "cannot mechanically check" figure (285/400,
  71%) is the robust number.
- Path-token regex over-matched prose (ratios, URLs, library names like
  `Reveal.js`). All NOTFOUND candidates were hand-inspected before any
  CONFABULATION verdict; the five reported are the survivors of that review.
