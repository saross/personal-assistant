# Defence-pass protocol — adversarial qualification of audit findings

**Status:** proven in production (map-reader GATE 1, 2026-07-29).
**Origin:** the PI, reviewing 12 headline audit findings from memory,
qualified 2 — both one-sided evidence assembly (facts correct, licensing
and exculpatory context missing), not factual error. Fact-checking the
findings had given false comfort: it audited the dimension that held.
**Reusable for:** any repo review or audit producing breach-class
findings (next: inscriptions, llm-reproducibility).

## The failure class

Breach-hunting pipelines (audit agents, discharge mappers, reviewers)
optimise for detecting contradictions and never run the opposite
search. The result is prosecutor's bias: findings whose facts verify
but whose framing overstates, because nobody searched for the erratum,
dated decision, registered qualifier, or commit-timeline fact that
licenses or mitigates the breach. Spot-audits of cited facts do not
catch this — they check the prosecution's evidence, not its omissions.

## The protocol

1. **One fresh-context agent per finding, briefed as counsel for the
   defence.** Input: the finding's text and primary sources only.
   Task: find every fact that licenses, mitigates, qualifies, or
   overturns the finding — with verbatim quotes and locators. "Stands"
   is a valid outcome; manufacturing doubt is not the job.
2. **Blinding.** Agents must not open the audit's own outputs
   (adjudication records, revised packages) — primary sources only, so
   defence evidence is independently derived.
3. **Calibration probes.** Seed the batch with findings whose
   qualifications are already known (e.g. caught by the PI) *without
   telling the agents*. If the pass independently rediscovers the known
   qualifications, its verdicts on the unknown findings carry measured
   weight; if it misses them, escalate (human review, cross-vendor).
4. **Mandatory defence-search record.** Every verdict states what was
   searched and the nearest miss — the auditable-negative discipline
   applied to context. Prosecution without a recorded defence search is
   an incomplete verdict (map-reader charter § 5 rule 13).
5. **Monitor enforcement.** The build-time revalidation layer rejects
   breach-class ledger rows lacking a defence-search record, so the
   discipline persists after the audit ends.

## Production results (map-reader, 2026-07-29)

Both calibration probes passed (the pass recovered the PI's context
and found more). 12/12 findings needs-qualification, 0 overturned,
3 sub-claims retracted. Meta-finding surfaced only by the defence
side: the recurrent root cause was internal inconsistency within the
preregistration itself, not execution drift. Cost: US$0 (Opus agents
on the Max plan, ~40 min wall-clock).

## Transfer notes

The protocol is symmetric insurance: prosecution agents hunt breaches,
defence agents hunt licences, and the adjudicator (orchestrator or
PI) rules on the join. Defence agents are themselves first-party — for
the highest-stakes findings, spot-verify their load-bearing claims
mechanically (byte-diffs, re-derivations) or send disputed items
cross-vendor. Full apparatus in the map-reader repo:
`reports/verification/apparatus/defence-pass-adjudication-2026-07-29.md`
and `planning/audit-charter.md` § 5 rule 13, § 6.
