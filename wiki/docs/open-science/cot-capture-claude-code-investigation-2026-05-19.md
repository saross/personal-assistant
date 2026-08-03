---
title: Chain-of-Thought capture from Claude Code — state-of-practice investigation
date: 2026-05-19
author: Shawn Ross
audience: open-science / research-transparency / agentic-tooling community
related:
  - ../../../data/archive/rda-ig-application-2026-07/RDA_IG_Statement_of_Work.docx  # relocated 2026-08-03, see rda-ig-documents-note.md
  - ../../../data/archive/rda-ig-application-2026-07/RDA_IG_Summary_and_Description.docx  # relocated 2026-08-03
  - ../../continuity.md (workstream E)
tags: [open-science, provenance, agents]
status: complete
---

# Chain-of-Thought capture from Claude Code — state-of-practice investigation

## Executive summary

Claude Code (Anthropic's CLI agent, hereafter **CC**) renders extended-thinking
("chain-of-thought", CoT) text to the terminal in real time, but **does not
persist that text** to its session transcript files. Only the cryptographic
`signature` field of each thinking block is written; the `thinking` text field
is empty. This is the result of an Anthropic-side design change rolled out in
February–March 2026 and is documented as known, contested, and closed-as-won't-fix
in the upstream issue tracker. **There is no documented setting that restores
thinking-text persistence on current models** (specifically on Claude Opus 4.7,
the recent flagship).

The community has responded with a dense ecosystem of proxy and observability
tools (network MITM, eBPF kernel-level interception, hook-based wrappers), but
none of these tools was designed for **research-grade, FAIR-compliant capture
of reasoning traces as first-class research artefacts**. They were built for
cost monitoring, model routing, and debugging. The research-transparency gap
is genuine and unsolved.

This finding has direct implications for the RDA "Documenting Generative AI
Interactions in Research" Interest Group (RDA IG, co-chaired by the author with
Brian Ballsun-Stanton) and the Three Ps framework (Prompt, Process, Provenance)
the IG is developing. **Reasoning-trace capture from agentic coding tools is a
candidate IG output or working-group deliverable.**

## Why this matters for open science

Agentic coding tools — CC, Aider, Cline, Cursor CLI, OpenCode — increasingly
mediate substantive research work: data analysis pipelines, statistical model
implementations, instrument-control scripts, literature-extraction workflows.
When such tools fail in non-obvious ways (introducing subtle bugs, choosing
incorrect statistical methods, mis-handling units, confabulating identifiers),
the **reasoning traces leading to the failure are the primary diagnostic
artefact**. Without them, a downstream researcher reviewing the work cannot:

1. Distinguish a deliberate methodological choice from a model error.
2. Audit whether the model considered and rejected alternative approaches.
3. Reproduce a non-deterministic decision path under controlled conditions.
4. Identify failure-mode patterns across a corpus of agent-mediated research.

These map directly onto the Three Ps:

- **Prompt** — the user's request (visible in the JSONL transcript, captured).
- **Process** — the reasoning + tool-call trajectory (**partially captured**:
  tool calls and tool results are persisted; reasoning traces are not).
- **Provenance** — the audit trail allowing third-party verification (broken
  for the reasoning component).

Reasoning-trace capture is, therefore, not an optional nicety. It is a
**necessary precondition** for treating agentic-coding sessions as auditable
research interactions in any framework that takes the Three Ps seriously.

## The technical situation (as of 2026-05-19)

### What CC does today

- Persists session transcripts to `~/.claude/projects/<project-slug>/<session-id>.jsonl`.
- For each assistant message, writes content blocks including:
  - `text` blocks (preserved verbatim).
  - `tool_use` blocks (preserved with inputs).
  - `tool_result` blocks (preserved with content).
  - `thinking` blocks — **`type` and `signature` preserved; `thinking` text is
    the empty string**.

### Sharp version boundary, documented empirically

Independent user investigation (GitHub issue #32810, 331-session audit) shows
the boundary at CC v2.1.72: 307 thinking blocks fully populated across 18
sessions on v2.1.71; 99% empty in the next 13 sessions after upgrading. The
root cause is identified as an Anthropic server-side flag
(`tengu_quiet_hollow`) and an opt-in beta API header
(`redact-thinking-2026-02-12`) that CC began sending. After this rollout, the
API returns thinking signatures but empty thinking text to CC, which writes
exactly what it received.

### What I confirmed locally (2026-05-19)

- Three recent live CC sessions: 88, 7, and 24 thinking blocks respectively.
- All `signature` fields populated; **zero** thinking-text fields populated
  across all three sessions.
- This is consistent with the issue-tracker reports and indicates the
  redaction is universal on the author's Opus 4.7 setup.

### Known workaround, no longer functional on current model

`showThinkingSummaries: true` in `~/.claude/settings.json` partially restored
summary text capture on earlier models (working through Claude 3.7 Sonnet and
Claude Opus 4.6). **It does not work on Opus 4.7** (issue #49708, closed as
duplicate). The author is on Opus 4.7; the workaround is therefore unavailable
in the current production environment.

### Anthropic's stated rationale

Where surfaced in issue discussions, Anthropic's rationale is that Claude 4
models return encrypted thinking (the full CoT is folded into the signature,
only a summary is returned to clients), and the JSONL-persistence omission of
even the summary appears to have been a UI/latency optimisation rather than a
deliberate policy decision. **The community response has been sharply
negative**; the relevant issues have collected substantial engagement and
remain closed without resolution.

### Relevant upstream issues

| # | Title | Status | Significance |
|---|-------|--------|---|
| [#32810](https://github.com/anthropics/claude-code/issues/32810) | Thinking block content empty in JSONL since 2.1.72 | CLOSED | Documents the sharp version boundary, the server flag, the beta header. |
| [#31143](https://github.com/anthropics/claude-code/issues/31143) | Persist summarised thinking text to JSONL | CLOSED | The "correct framing" feature request; notes the v3.7 Sonnet workaround. |
| [#49708](https://github.com/anthropics/claude-code/issues/49708) | Opus 4.7: thinking content empty despite `showThinkingSummaries: true` | CLOSED as duplicate | Confirms the workaround no longer functions on current models. |
| [#39343](https://github.com/anthropics/claude-code/issues/39343) | Add hook event for extended thinking / LLM reasoning blocks | **OPEN, STALE** | **The right architectural fix.** A `ThinkingBlock` hook event that fires in real time would bypass the JSONL persistence question entirely. 4 comments, no Anthropic commitment. |
| [#32997](https://github.com/anthropics/claude-code/issues/32997) | Thinking redaction correlates with deceptive model behaviour | CLOSED stale | Methodologically interesting for the research-transparency case; causation not established but the data are suggestive. |

## State of practice — community workarounds

The following community-built tools could in principle be used to capture
thinking traces. None is a turn-key research-transparency solution; each is
either heavy infrastructure, untested for this purpose, or compromised by
licensing or maintenance status.

### Network-layer interception (proxies + MITM)

| Tool | Approach | Licence | Maturity | Fit |
|------|----------|---------|----------|-----|
| [eunomia-bpf/agentsight](https://github.com/eunomia-bpf/agentsight) | eBPF kernel-level TLS interception | MIT | 328 stars, active | **HIGH in principle** — reads raw API bytes before CC's runtime can discard anything. Requires Linux + `sudo`. |
| [chouzz/llm-interceptor](https://github.com/chouzz/llm-interceptor) | Python mitmproxy explicitly targeting CC | **no licence declared** | 32 stars, active | MEDIUM-HIGH technical; **blocker for open-science publication** due to missing licence. |
| [seifghazi/claude-code-proxy](https://github.com/seifghazi/claude-code-proxy) | Go transparent proxy + React dashboard | MIT | 463 stars, active | MEDIUM as-is; **best base to build on** for a research-grade wrapper. |
| [dyshay/proxyclawd](https://github.com/dyshay/proxyclawd) | Rust MITM + TUI | no licence | 3 stars | LOW (immature, unlicensed). |
| [bukzor/claude-code-mitmproxy](https://github.com/bukzor/claude-code-mitmproxy) | Python mitmproxy script | unspecified | 0 stars | LOW (single-person, minimal docs). |

### Hook-based observability

| Tool | Approach | Notes |
|------|----------|-------|
| [disler/claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability) | CC hooks → SQLite + WebSocket | 1,420 stars, but **CC hooks do not currently fire for thinking blocks** (see issue #39343). Captures tool calls and session events; reasoning traces invisible. |
| [doneyli/claude-code-langfuse-template](https://github.com/doneyli/claude-code-langfuse-template) | CC → Langfuse | Thinking is discarded by CC *before* it reaches Langfuse; this and similar downstream-of-CC observability tools cannot solve the problem. |

### Terminal scraping

The verbose-mode display of thinking has itself been broken as a regression
(issues #25980, #22977). Even when working, terminal output (via `tmux`,
`asciinema`, `script(1)`) is not reliably parseable into structured thinking
blocks and does not survive headless / batch / agent-as-subprocess invocations.
**Not recommended for any research use.**

### CC forks

None found. The CC source was partially reverse-engineered via a leaked
sourcemap (March 2026) and analysed academically by
[VILA-Lab/Dive-into-Claude-Code](https://github.com/VILA-Lab/Dive-into-Claude-Code)
(1,189 stars, CC-BY-NC-SA-4.0), but no maintained fork with a
thinking-persistence patch exists.

### Replacement clients

Surveyed: Aider, Cline, Cursor CLI, OpenCode. None was found to explicitly
persist extended-thinking text for research-transparency purposes. Most do not
use Anthropic's extended-thinking API in the same way CC does, so the question
is partially moot for those tools — but it also means none of them is a
drop-in replacement that solves the problem.

### Academic / open-science literature

**Null result.** No academic or open-science literature was found specifically
addressing CoT-trace capture from agentic coding tools for reproducibility or
FAIR archiving. Adjacent work exists in workflow-provenance (RO-Crate
extensions for AI workflows) but does not address the agentic-CLI transcript-
capture problem at the level the RDA IG framework would require.

## Recommendations

### Immediate (within the author's PA-infrastructure work)

1. **Treat thinking-block metadata as the captured signal, not the content.**
   The existing `session.meta.json` schema already records `thinking_blocks.count`,
   `thinking_blocks.signature_count`, sharing preferences, and use constraints.
   This is the honest "what we have" position pending an upstream fix.

2. **Document the limitation in the PA `session.meta.json` schema.** A
   `thinking_blocks.text_capture` field with values such as
   `"unavailable-cc-redacted-since-v2.1.72"` would make the provenance gap
   machine-readable rather than invisible.

3. **Note in continuity.md that workstream E (RDA IG) gained a concrete
   technical input.** This investigation is the first piece of empirical
   open-science evidence the IG can cite.

### Medium-term (within a 3–6 month horizon, if priorities align)

4. **File a comment on issue [#39343](https://github.com/anthropics/claude-code/issues/39343)**
   with the RDA IG research-transparency framing. The unique voice — a
   formally-constituted research-data-standards IG co-chair making the
   reproducibility case — is qualitatively different from the developer
   voices currently on that thread. A `ThinkingBlock` hook event is the
   correct architectural fix.

5. **For specific failure-mode investigations** where CoT capture is
   load-bearing for a particular analysis (e.g., a publication that needs
   to reconstruct exactly how the model arrived at a methodological choice),
   set up [eunomia-bpf/agentsight](https://github.com/eunomia-bpf/agentsight)
   as the capture layer **for that session only**. Document the session's
   special capture status in its `session.meta.json`.

### Long-term (potential RDA IG / WG output)

6. **Build a thin research-grade wrapper on
   [seifghazi/claude-code-proxy](https://github.com/seifghazi/claude-code-proxy)**
   (MIT, well-architected). Add:
   - A streaming-SSE thinking-block parser.
   - An RO-Crate-compatible export mode.
   - A `thinking_blocks.text_capture_method` provenance field.
   - Documentation aligned with the Three Ps framework.

   This is plausibly publishable as a **tools paper** in a venue such as
   *Journal of Open Source Software* (JOSS), *Computational Communication
   Research*, or a methodological venue depending on framing. The
   "research-grade reasoning-trace capture for agentic coding tools" wrapper
   does not currently exist in the ecosystem. **Estimated effort: 2–4
   focused weeks** for a minimum-viable wrapper + paper, building on the
   existing proxy infrastructure.

7. **Position this work as RDA IG Tier-2 output ("Research Grimoires
   Framework" candidate, or its own deliverable).** The RDA IG Statement of
   Work and Summary documents (`./RDA_IG_Statement_of_Work.docx`,
   `./RDA_IG_Summary_and_Description.docx`) explicitly contemplate tooling
   and pattern outputs. Reasoning-trace capture is exactly such an output:
   a concrete pattern with reference implementation, aligned to the Three
   Ps, addressing a documented gap in the field.

## Suspected publication angles (for later evaluation)

The findings here support several plausible research-output framings, not
mutually exclusive:

1. **Methodological paper**: "Reasoning-trace provenance in agentic coding
   tools: a Three Ps audit of Claude Code, Aider, Cline, and Cursor CLI."
   Comparative empirical study across the major CLI agents, mapping each
   tool's capture surface against the Three Ps. Venue: RDA proceedings,
   F1000Research, *Data Science Journal*.

2. **Tools paper**: as above (Recommendation #6).

3. **Position paper / IG output**: "The reasoning-trace gap in
   research-mediating AI tools." Frames the empirical finding (this
   investigation) as motivation for a Three Ps-aligned capture standard;
   draws on the RDA IG framework. Venue: RDA IG report, or a
   research-data-standards venue.

4. **Empirical study with provocative angle**: extend issue #32997's
   thinking-redaction-vs-deception correlation analysis on a larger
   controlled corpus. Methodologically demanding; only feasible after
   reasoning-trace capture is solved.

## Provenance of this report

- **Author**: Shawn Ross, in collaboration with Claude Code (Opus 4.7) as
  research-assistant client.
- **Investigation method**:
  - Empirical inspection of three live CC sessions' JSONL files (`~/.claude/projects/`).
  - Dispatched `claude-code-guide` subagent (Anthropic-docs / settings audit; 60 sec).
  - Dispatched `prior-art-scout` subagent (community-tools state-of-practice
    survey; 196 sec, 38 tool calls, 8 distinct GitHub repositories examined,
    5 issue threads examined). Subagent reports captured in
    `/tmp/claude-1000/-home-shawn-personal-assistant/.../tasks/`.
- **Date**: 2026-05-19. Findings should be treated as time-bounded; the
  upstream behaviour has changed in the past 12 weeks and may change again.
- **Re-verification needed before citing**: any specific GitHub issue
  number, tool name, star count, or version-boundary claim. The underlying
  ecosystem is fluid.

## Cross-references

- **Empirical evidence informing the 850K transcript cap decision**:
  `data/experiments/transcript-cap-analysis-2026-05-19/findings.md`
- **RDA IG framing documents**: `./RDA_IG_Statement_of_Work.docx`,
  `./RDA_IG_Summary_and_Description.docx`
- **Memory-system rethink (workstream D)**: `../../continuity.md`
  workstream D — the `notes/<topic>.md` wiki structure aligns with the
  "Research Grimoires Framework" candidate IG output.
- **Three Ps already in `session.meta.json` schema**: see
  `cc_session_toolkit/archive.py:create_session_metadata`. The schema
  contemplates these fields; this report addresses one of the unfilled
  fields (the reasoning-trace text).
