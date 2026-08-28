---
title: "Map-reader — priority, scoop risk, and what the 105-item corpus actually says"
tags: [map-reader-llm, publication, strategy, planning]
created: 2026-08-28
updated: 2026-08-28
status: active
---

# Map-reader — protecting priority, and why the corpus argues for moving FASTER

**Trigger:** Shawn, 2026-08-28: *"we have **outstanding** results from map reader that
**appear** unprecedented in the literature, and I'm worried about getting scooped."* He ran
`/lit-scout`, found nothing truly comparable, and then pointed at the real evidence base:
**the `vlm-burial-mound-detection` collection in Zotero.**

## ⭐ The deadline has a different SHAPE from everything else on the list

**The applications have a date. Scooping has a HAZARD RATE** — every week unpublished carries
a probability, not a deadline. ⇒ **Structurally the AFCA argument of 24 Aug** (*"an undated
rolling posting; an invisible deadline is not [safe to defer]"*), **applied to research.**
⚠ **And map-reader runs on drive-bys** — 5.25h in W35, third-largest project, no focus slot.
**That is how invisible deadlines get lost.**

## ✅ The evidence base is far stronger than a lit-scout — and I should not have hedged it as one

**`vlm-burial-mound-detection`: 105 items, curated.**

| Year | 2015–19 | 2020 | 2021 | 2022 | 2023 | **2024** | **2025** | **2026** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Items | 15 | 9 | 13 | 11 | 8 | **18** | **24** | **7** |

⇒ **49 of 105 items are from 2024 onward, and the newest are dated July 2026** — weeks old.
**This is a maintained survey, not a search.** ⭐ **A claim resting on it is much better
supported than one resting on a lit-scout run, and the earlier draft of this note
under-credited it.**

## ⚠⚠ BUT THE CORPUS DOES NOT SAY THE FIELD IS EMPTY — IT SAYS THE FIELD IS BUSY

**Directly adjacent work already in the collection, all within ~12 months:**

- **"Ancient Burial Mounds Detection in the Altai Mountains with High-Resolution Satellite
  Imagery"** — **2026-01-06**. Same object class.
- **"Visual Foundation Models for Archaeological Remote Sensing: A Zero-Shot Approach"** —
  **2025-10-07**. ⚠ **Zero-shot + archaeological remote sensing is the intersection.**
- **"Automated Detection of Hillforts in Remote Sensing Imagery With Deep Multimodal
  Segmentation"** — 2025-04.
- **"Archaeological Site Detection: … Europe-Wide Hillfort [survey]"** — 2025-01-31.
- **"Remote Sensing and AI Coupled Approach for Large-Scale Archaeological Mapping in the
  Andes"** — 2025-10-21.
- ⭐ **"CartoMapQA: A Fundamental Benchmark Dataset Evaluating Vision-Language Models on
  Cartographic [tasks]"** — **2025-11-03.** **Someone has published a VLM cartographic
  BENCHMARK, which is the thing Shawn wants to build.**

⚠ **I am reading titles, not papers.** **Whether any of these is comparable to the specific
result is a judgement only Shawn can make, having read them.** **But the volume and recency
are facts, and they carry two consequences.**

## ⇒ CONSEQUENCE 1: THE HAZARD RATE IS HIGH, NOT LOW

**~24 items in 2025 is roughly two publications a month in this space.** ⇒ **"Nothing truly
comparable" is compatible with a crowded field in which nobody has yet published *this
particular* thing** — **and a crowded field is precisely where being scooped is likely, not
unlikely.**

⚠ **And a survey can only see PUBLISHED, INDEXED work.** **What scoops you is preprint,
in-review or unindexed** — the population no survey observes. **This project has watched
exactly that: the GCPA-SIDCER framework existed on Zenodo, deposited 16–22 Aug, and was
invisible to search on the 24th.**

⇒ ⭐⭐ **A clean survey in a busy field does not lower the risk. It removes the only signal
that would have warned you.**

## ⇒ CONSEQUENCE 2: SEPARATE PRIORITY FROM PUBLICATION — only one is expensive

| | Cost | Buys |
|---|---|---|
| **Timestamped artefact** — preprint, Zenodo deposit, dated public repo | **Days** | **Precedence** |
| ISPRS paper | Months | Publication, citation, the benchmark |

**They are being treated as one task, which is what makes the whole thing feel unaffordable.**
⭐ **Shawn has watched the cheap instrument work at close range: Crawley's Zenodo deposits
established GCPA-SIDCER's precedence months before any journal would have.** **The ISPRS venue
is already locked and a manuscript skeleton is drafted**, so the expensive half is further
along than the framing suggests.

⏰ **Nothing here needs to happen before Monday.** **But the anti-scoop action is small and
separable — which is exactly what lets the PAPER be deferred without deferring the
PROTECTION.**

## ⚠ The novelty claim needs the §K1 treatment, and the corpus proves why

**"Nothing truly comparable" is a claim a reviewer will test** — and this project watched that
prediction come true two days ago. **Crawley on the RDA proposal: the *"no shared cross-domain
standard exists"* claim *"will likely be pointed out in the RDA Community Review or during the
TAB review."* He was right. And the fix was NOT to soften it.**

⇒ ⭐⭐ **Same discipline: name precisely WHICH LAYER is empty, rather than claiming a broad
absence.** **A narrow claim survives a counter-example; a broad one dies to it.** ⚠ **With 24
papers in 2025 alone, a reviewer will have a counter-example to hand** — **and the six items
listed above are the ones the paper must differentiate itself from explicitly, by name.**

⭐ **Turn the corpus into the argument rather than the risk:** *"here are the six closest
efforts and here is the specific thing none of them does"* is far stronger than *"we found
nothing comparable"*, and the 105 items are the evidence for it.

## ⭐⭐ THE CLAIM, STATED PROPERLY — and the F1 is NOT the contribution

**Shawn's actual claim, 2026-08-28** (which is far more specific than *"nothing comparable"*):
**nobody is reaching F1 ~0.85, on a large-scale (Belgium-sized) corpus of maps, with a
preregistered instrument, using TEXT-ONLY prompts, at a cost of about USD$100 in credits** —
**and on DEGRADED HISTORICAL maps, not modern born-digital ones.**

### ⚠ Six conjuncts is trivially true, and a reviewer will say so

**You can always add conjuncts until a claim is unique.** ⇒ **The paper must name WHICH ONE
carries the weight.** **That is the §K1 discipline, and this collection settles it.**

### ⚠⚠ CORRECTION 2026-08-28 — I COMPARED AGAINST THE WRONG NUMBERS, AND IT MATTERS

**I first told Shawn: *"F1 ~0.85 is not remarkable as a number — it is the bar you are
matching, not the contribution."* THAT WAS WRONG**, and he was on the point of softening the
claim on the strength of it.

**The error: I compared a POINT-FEATURE result against POLYGON and LINE numbers.** Once the
feature type is held constant the picture inverts. ⚠ **Shawn supplied the qualifier; I did not
ask for it.**

### What the corpus actually says, with feature type held constant

**Of 105 items, 65 have abstracts, and only FOUR report an F1:**

| Work | F1 | Feature type | Method | Input |
|---|---|---|---|---|
| Historical geologic maps (DARPA AI4CMA) | 0.91 | **polygon** | trained, one-shot + human-in-loop | historical |
| **Historical geologic maps — SAME PAPER** | **0.73** | ⭐ **POINT** | **as above** | historical |
| Kenya historical road network | 0.84 | **line** | deep learning | historical |
| Historical map vectorisation | 0.871 | line/area | trained pipeline | historical |

⇒ ⭐⭐ **THE ONLY POINT-FEATURE NUMBER IN THE ENTIRE CORPUS IS 0.73.** **Shawn is at ~0.85.**

⭐ **And the 0.91-vs-0.73 gap is INSIDE ONE PAPER** — same authors, same maps, same pipeline.
⇒ **That is direct evidence, from a comparator rather than from us, that POINT DETECTION IS
THE HARDER TASK.** **It is the strongest single sentence available for the paper's framing.**

### ⚠ And read their qualifiers, because they are the contribution

**`10.3390/geosciences14110305`, 2024-11-13:** *"achieved a median F1 score of 0.91 for polygon
feature segmentation and 0.73 for point feature detection **when such features had abundant
annotated data**"* — via **one-shot segmentation using legend prompts** and **a
human-in-the-loop system** letting geologists refine results.

**Against which Shawn's method:**

| | Comparator (0.73) | Map-reader (~0.85) |
|---|---|---|
| Annotated data | **"abundant"** | ⭐ **20 tiles, 512×512 px** |
| Setup time | not stated; pipeline + annotation | ⭐ **"a couple of hours"** |
| Human in the loop | **yes, by design** | no |
| Model weights updated | yes | ⭐⭐ **NO** |
| Cost | GPU + annotation + engineering | ⭐⭐ **~USD$100** |

### ⭐⭐ "CALIBRATED", NOT "TRAINED" — fight for the word, it is load-bearing

**Shawn's term, and it is the correct one.** **20 tiles used to select prompts and thresholds
is CALIBRATION; no model weights are updated.** ⇒ **That distinction is what separates this
from every trained pipeline in the corpus**, and using the loose word would hand a reviewer
the objection *"you trained too, you just call it something else."*

⭐ **The defensible line is concrete: NO MODEL WEIGHTS WERE UPDATED.** **Declare the 20 tiles
plainly as a development set for prompt and threshold selection** — the preregistration should
already carry this, and declaring it is stronger than minimising it.

### ⚠⚠ THE $100 IS THE DEPLOYMENT COST, NOT THE DISCOVERY COST — and this must be declared

**Shawn, unprompted, 2026-08-28:** *"to FIND the optimal configuration, I went through a
preregistered tree of several hundred combinations and spent $6k in Gemini credits, but the
RESULT is a narrow range of optimal configurations… all of which cost between ca. $30–300."*

⇒ **The honest cost claim is NOT "$100".** ⇒ **It is: $30–300 PER DEPLOYMENT, after a one-time
$6,000 preregistered search.**

### ⭐⭐ AND THE $6k IS THE CONTRIBUTION, NOT THE EMBARRASSMENT

**This is exactly the training-cost / inference-cost split that the comparators also have** —
they pay annotation + training compute + engineering once, then infer cheaply. **Same shape,
different currency.**

⇒ **The strongest framing available: HE SPENT $6,000 SO NOBODY ELSE HAS TO.** **The published
configuration IS the artefact, and its value is precisely that it cost $6k to find and costs
$30–300 to use.**

✅ **DISCLOSURE IS ALREADY DONE — Shawn, 2026-08-28: *"we walk through this process in methods, also it's in the disclosed prereg."*** ⚠ **So *"declare it"* was the wrong advice; it is declared.**

⇒ ⭐⭐ **THE REMAINING POINT IS DIFFERENT AND SHARPER: DISCLOSING IN METHODS IS NECESSARY; LEADING WITH IT IN THE ABSTRACT IS THE STRATEGIC MOVE.** **Plenty of papers bury the true cost in Methods, where nobody reads it, and headline the cheap number** — which is both weaker and more fragile. **Here the $6k is not a caveat to be survived, it is the reason the paper is worth reading**: *a $6,000 preregistered search, published, so your deployment costs $30–300.* ⇒ **Check that the ABSTRACT carries it, not only the Methods.**

### ⚠⚠ BUT IT INVITES ONE SERIOUS OBJECTION, AND THE PREREGISTRATION IS THE ANSWER

**Searching several hundred configurations and reporting the best is a garden-of-forking-paths
problem.** ⚠ **A reviewer WILL raise it, and it is the strongest attack available on this
paper.**

⇒ ⭐⭐ **THE PREREGISTERED TREE IS THE DEFENCE, AND IT UPGRADES THAT CONJUNCT'S ROLE.** **Earlier
in this note I filed preregistration as *"evidence it is honest, and rare in this
literature"* — a credibility flourish. IT IS NOT. It is the specific, load-bearing rebuttal to
the multiple-comparisons objection that a several-hundred-config search necessarily invites.**
**A declared search space searched exhaustively is optimisation. An undeclared one is
p-hacking. The preregistration is what makes it the former.**

### ⏰ THE ONE QUESTION THAT MUST BE ANSWERED BEFORE PUBLICATION

⚠⚠ **Was the reported F1 ~0.85 measured on data that played NO ROLE in selecting among the
several hundred configurations?**

**If the Belgium-scale evaluation is held out from the search, the result stands and the
generalisation claim is strong.** ⛔ **If the same data both selected the configuration and
produced the headline number, the F1 is a selection artefact and the paper does not survive
review.** ✅✅ **CONFIRMED BY SHAWN, 2026-08-28: the reported F1 WAS measured on data that played no role in selecting among the configurations.** ⇒ **The garden-of-forking-paths objection is ANSWERED, not merely disclosed.** ⭐ **This was the single load-bearing verification — every other strength in the paper rested on it, and it holds.** **Process is walked through in Methods and in the disclosed preregistration.**

### ⚠ And the generalisation limit is Shawn's own, correctly stated

*"I've generalised to ONE large and not atypical historical map set, but NOT to arbitrary
historical maps."* ⭐ **That is the right scope and it should appear in the abstract, not
buried in limitations.** ⇒ **Claiming one map set and delivering it beats claiming generality
and being asked for a second corpus in review.**

⭐ **The precision/recall dial is a strength, not a hedge** — *"you can change parameters to
dial towards precision or recall"* means the method exposes an operating curve rather than a
single point, which is what a practitioner actually needs. **Report the curve.**

### ⭐ And this gives the Belgium-scale conjunct a SECOND job

⚠ **A reviewer's obvious objection to a 20-tile calibration set is overfitting to those 20
tiles.** ⇒ **The Belgium-scale evaluation is the answer.** **A tiny calibration set against a
very large held-out evaluation is not a weakness — it is the generalisation result.**
⇒ **The conjuncts support each other: scale is no longer merely "not cherry-picked", it is the
evidence that 20 tiles did not overfit.**

### What the corpus says about the F1 itself

**Of 105 items, 65 have abstracts, and only FOUR report an F1 figure:**

| Work | F1 | Method | Input |
|---|---|---|---|
| Historical geologic maps (DARPA AI4CMA) | **0.91** polygon / 0.73 point | trained | historical |
| Kenya historical road network | **0.84** | deep learning | historical |
| Historical map vectorisation | 0.713 → **0.871** | trained pipeline | historical |

⇒ ⚠⚠ **F1 ~0.85 IS NOT REMARKABLE AS A NUMBER. It sits inside the band trained
deep-learning pipelines already achieve.** ⇒ **The F1 is the BAR BEING MATCHED, not the
contribution.**

### ⭐⭐ AND ALL THREE COMPARATORS ARE ON HISTORICAL MAPS — which is what makes the comparison LEGITIMATE

**Shawn's qualifier — degraded historical, not born-digital — does not separate him from these
three. It ALIGNS him with them, and that is the point.** ⚠ **If the comparators had worked on
clean modern data, a reviewer could dismiss the whole comparison as apples-to-oranges**: 0.85
on hard input is not measurable against 0.9 on easy input.

⇒ ⭐ **The collection does not merely supply comparators. It supplies comparators AT THE SAME
DIFFICULTY.** **That is what turns *"we match trained performance"* from an assertion into a
defensible one.**

### ⇒ The claim to make

> ⚠ **SUPERSEDED — this version compared against polygon and line results. See the correction
> above.** ~~We match trained deep-learning performance (F1 ~0.85, against 0.84–0.91)…~~

**⇒ THE CLAIM, WITH FEATURE TYPE HELD CONSTANT:**

> **On degraded historical maps, we detect POINT features at F1 ~0.85 — against 0.73, the
> only comparable published figure, which required abundant annotated data and a
> human-in-the-loop system. We calibrate on 20 tiles in a couple of hours, update no model
> weights, prompt in text only, and spend **USD$30–300 per deployment — after a one-time,
> preregistered $6,000 configuration search that we publish so it need not be repeated.**
> Evaluated at Belgium scale on one large, not-atypical historical map set; **generalisation
> to arbitrary historical maps is not claimed.**

**Each conjunct has a different job, and the paper should make that explicit:**

| Conjunct | Role in the argument |
|---|---|
| **F1 ~0.85 on POINT features** | ⭐⭐ **~12 points above the only comparable figure. This IS a contribution** |
| **20-tile calibration, no weight updates** | ⭐⭐ **The mechanism, and the sharpest contrast with 0.73's "abundant annotated data"** |
| Degraded historical input | ⭐ **What makes the comparison like-for-like** |
| **Text-only prompts** | ⭐⭐ **THE MECHANISM — this is the contribution** |
| **USD$30–300 per deployment** | ⭐⭐ **THE CONSEQUENCE THAT MATTERS** — orders of magnitude against GPU time, annotation and engineering |
| **One-time $6,000 preregistered search** | ⭐⭐ **THE ARTEFACT. He paid it so nobody else has to — declare it, it is the reason to read the paper** |
| **Preregistered tree** | ⭐⭐ **UPGRADED: not a credibility flourish but the specific rebuttal to the multiple-comparisons objection a several-hundred-config search invites** |
| Belgium-sized corpus | Evidence it is robust, not cherry-picked |
| Preregistered instrument | Evidence it is honest, and genuinely rare in this literature |

⇒ **The empty layer is not "high F1". It is "high F1 WITHOUT TRAINING, AT TRIVIAL COST".**
**Name that, and the six adjacent papers become the evidence for the claim rather than threats
to it.**

### ⚠ Method caveats on the above, stated so they are not forgotten

- **I read ABSTRACTS, not papers.** **Only 4 of 65 abstracts carry a number**, so this is a
  signal that reframes the claim, **not** a comparison table.
- **The tasks differ** — polygon segmentation on geologic maps is not burial-mound detection.
  ⚠ **The F1s are not directly comparable and the paper must not pretend they are.**
- ⏰ **The real table needs the papers read.** ⭐ **But that is paper work which ALSO answers
  the scoop question, so it is not a detour.**
- ⏰ **CartoMapQA (Nov 2025) — Shawn to check.** His read is that they test something else.
  **Confirm before the benchmark ambition is framed publicly.**

## The two goals are sequenced, not opposed

**A published benchmark in AI evaluation is a credential for exactly the roles being applied
for this weekend.** ⇒ **Map-reader is not competing with the career work; it is the evidence
base that makes the NEXT round of applications easier to write than this one.** ⚠ **CartoMapQA
(Nov 2025) is a reminder that the benchmark niche is also contested.**

## ⏰ Actions — none this weekend

1. **Decide the timestamp instrument** (preprint / Zenodo / dated public repo) and execute it
   **next week**, independent of the paper's timeline.
2. **Re-read the six adjacent items above** and write the differentiation explicitly. ⭐ **This
   is paper work that also answers the scoop question**, so it is not a detour.
3. **Re-run the novelty claim through the §K1 lens** before it enters the manuscript.
4. ⚠ **Consider a focus slot for map-reader once the applications clear.** **A hazard-rate
   deadline handled by drive-bys is the combination the 10 Aug ruling did not foresee** — and
   Slot 1 (EFN) is close to closeable.
5. **Re-run the survey near submission.** ⚠ **The population it cannot see today becomes
   visible later, and 2026 already has 7 items by August.**

---

## 🔭 FUTURE WORK — automating configuration discovery, and the trap it walks into

**Shawn, 2026-08-28:** *"I want to automate the discovery of optimal configurations, it's just
an F1 hill-climb."* **Proposed pipeline: give a model the map LEGEND TARGETS → (annotated)
CALIBRATION TILES → (annotated) TEST MAPS, with OFAT variation from the current optimal
configs → TARGET MAPS.**

### ⭐⭐ THE 5% FIGURE IS THE ONE TO REPORT — better than "20 tiles"

*"In our runs the annotated 'gold standard' calibration and test maps were about **5% of the
target corpus**."*

⇒ ⭐ **REPORT THE ANNOTATION BUDGET AS A FRACTION, NOT A COUNT.** **"20 tiles" is an absolute
number that means nothing without the corpus size; "5% annotated" is a ratio a practitioner
can apply to their own problem, and it is directly comparable to the 0.73 paper's "abundant
annotated data".** ⚠ **It is also the HONEST figure** — 5% is the total annotation burden
including test maps, and it is larger than "20 calibration tiles" implies. **Stating the
bigger, comparable number is stronger than the smaller, incomparable one.**

### ⚠⚠ AUTOMATING THE SEARCH REINTRODUCES THE FORKING-PATHS PROBLEM, IN A HARDER FORM

**The current work is safe because THE SEARCH TREE WAS PREREGISTERED — a declared space,
exhaustively searched, with a held-out evaluation.** ⚠ **An automated hill-climb is ADAPTIVE:
the path taken depends on results seen.** ⇒ **You cannot preregister a path that does not exist
until the search runs.**

⇒ ⭐⭐ **THE FIX, AND IT IS A CONTRIBUTION IN ITSELF: PREREGISTER THE ALGORITHM, NOT THE PATH.**
**A declared hill-climb procedure + declared stopping rules + declared search space + a final
evaluation held out from the entire search is defensible, and it is standard practice in
AutoML.** ⭐ ***"How to preregister an adaptive configuration search"* is a methods
contribution that fits the AI-evaluation credibility play exactly** — and it is the natural
second paper after this one.

### ⚠ OFAT will find a local optimum, and that should be said rather than discovered

**One-factor-at-a-time variation cannot see interactions.** ⚠ **If configuration parameters
interact — and tile size × prompt detail × confidence threshold almost certainly do — OFAT
converges to a LOCAL optimum and reports it as the optimum.**

⇒ **Not a reason to abandon it: OFAT is cheap, interpretable, and its steps are individually
explainable, which matters for a preregistered instrument.** ⇒ **But name the limitation
rather than let a reviewer name it**, and note the alternatives (factorial designs, Bayesian
optimisation) with the reason for not choosing them. ⭐ **"We chose an interpretable search
over an optimal one, and here is what that costs" is a strong sentence; being asked why you
used OFAT is a weak position.**

### ⭐ And the automation has a second payoff worth stating up front

**If discovery is automated, the $6,000 one-time cost becomes a REPEATABLE PROCEDURE rather
than a sunk expense** — ⇒ **which is what would let the method generalise beyond the one
large, not-atypical historical map set it is currently claimed for.** **That is the honest
route to the generality this paper deliberately does not claim.**
