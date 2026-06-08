# Component Guidelines

> How components are built in this project.

---

## Overview

<!--
Document your project's component conventions here.

Questions to answer:
- What component patterns do you use?
- How are props defined?
- How do you handle composition?
- What accessibility standards apply?
-->

(To be filled by the team)

---

## Component Structure

<!-- Standard structure of a component file -->

(To be filled by the team)

---

## Props Conventions

<!-- How props should be defined and typed -->

(To be filled by the team)

---

## Styling Patterns

<!-- How styles are applied (CSS modules, styled-components, Tailwind, etc.) -->

(To be filled by the team)

---

## Accessibility

<!-- A11y requirements and patterns -->

(To be filled by the team)

---

## Common Mistakes

<!-- Component-related mistakes your team has made -->

(To be filled by the team)

---

## Scenario: Zhuque AI Detect-Reduce UI Contract

### 1. Scope / Trigger

- Trigger: any frontend change to `ai_detect_reduce` mode selection, Zhuque browser launch/status guidance, session progress labels, result detail, or export/copy text display.
- This UI mirrors backend contracts; do not invent different risk-rate or billing semantics in components.

### 2. Signatures

- API client functions in `src/api/index.js`:
  - `optimizationAPI.startZhuqueBrowser()`.
  - `optimizationAPI.getZhuqueBrowserStatus()`.
  - `optimizationAPI.getZhuqueReadiness()`.
  - `optimizationAPI.preflightZhuqueTask(payload)`.
- Session segment fields consumed by detail UI:
  - `zhuque_detect_rate`, `zhuque_detect_result`, `zhuque_detect_count`, `zhuque_reduce_attempt`, `zhuque_reduced_text`.
- Session-level fields consumed by detail UI:
  - `zhuque_agent_trace`.
- Processing mode id:
  - `ai_detect_reduce`.

### 3. Contracts

- Workspace mode list must include `AI检测 + 降重`.
- Platform billing copy for `ai_detect_reduce` must say detection does not consume beer and actual high-AI LLM rewrite is charged by reduce call. Estimated start cost should display as zero/skip.
- When `processingMode === "ai_detect_reduce"`, show the Zhuque browser panel, call `getZhuqueBrowserStatus()` immediately, then poll every 5 seconds while the mode remains selected.
- The same panel must call `getZhuqueReadiness()` immediately and on the same polling cadence, then display page status, remaining uses, text-length readiness, readiness message, and actions.
- Before starting an `ai_detect_reduce` task, call `preflightZhuqueTask({original_text, processing_mode, billing_mode})`; if `ready=false`, show the backend message and do not call `startOptimization`.
- If preflight returns `estimated_max_round_credits`, show it as a risk estimate only. Do not present it as a pre-held or guaranteed charge.
- The launcher button calls `startZhuqueBrowser()` and keeps status based on the status endpoint's `connected` field, not on the launch response alone.
- Session detail final text must prefer `zhuque_reduced_text`, then `enhanced_text`, then `polished_text`, then `original_text`.
- Zhuque report risk rate in UI must use `max(labels_ratio[1], labels_ratio[2]) * 100` when `labels_ratio` is present, matching backend threshold semantics.
- Session detail must parse `zhuque_agent_trace` defensively and render the "Agent 决策轨迹" panel when trace or live Zhuque SSE events exist.
- When trace contains `type="reflection"` events, render them as "收敛反思" rows and show `stubborn_segment_indices`, `stagnation_count`, `current_strategy`, `next_strategy`, and `action` when present.
- When trace contains `type="prompt_evolution"` events, render them as "Agent 学习结果" rows and show root causes, source, safety status, and a collapsible `prompt_patch`.
- When trace or live `zhuque_reduce` events contain `length_adjustments`, render a "长度校正" summary with segment index, original length, before/after lengths, and bounds. This is metadata only; UI must not expect full text in the trace payload.
- When trace or live `zhuque_reduce` events contain `rewrite_mode`, render the mode. `rewrite_mode="breakthrough"` should be shown as "逃逸改写" so users can tell the agent has stopped using the default academic-polish base prompt after stagnation.
- When trace or live `zhuque_reduce` events contain `rewrite_mode="paper_reconstruction"`, render it as "论文重构" and show compact paper metadata when present: `paper_language`, `paper_section`, `paper_ai_patterns`, `candidate_count`, `candidate_selector`, and `fact_card_count`.
- When trace or live `zhuque_reduce` events contain `rollback_applied=true`, render a "回滚保护" summary with `rollback_reason`, `rolled_back_from_rate`, `rolled_back_to_rate`, and `restored_segment_indices` so users can see that an equal-or-worse rewrite did not overwrite a better previous version.
- Session detail SSE must consume `zhuque_detect` and `zhuque_reduce` in addition to `content`; live state is supplemental and refresh must still recover from stored trace.

### 4. Validation & Error Matrix

- Browser status endpoint fails -> show disconnected guidance, not a blocking crash.
- Readiness endpoint fails -> show a not-ready panel with action guidance, not a blocking crash.
- Preflight returns `ready=false` -> do not start the task; toast/display `message` and `actions`.
- Launch endpoint fails -> toast backend `detail` if present.
- `zhuque_detect_result` is missing or invalid JSON -> render a lightweight empty/raw report instead of crashing.
- `zhuque_agent_trace` is missing or invalid JSON -> hide trace or show lightweight diagnosis instead of crashing.
- Final report absent -> show "暂无报告" and keep result text panels usable.

### 5. Good/Base/Bad Cases

- Good: selecting `ai_detect_reduce` shows browser launcher, connected state updates from polling, and detail page shows final risk rate, detect count, reduce rounds, remaining uses, labels ratio, text length, and process timeline.
- Good: readiness shows page status, remaining uses, text length, action suggestions, and a "朱雀已就绪" state before task start.
- Good: detail page shows Agent trace rows with initial detect, round strategy, selected segments, risk-rate change, and final diagnosis.
- Good: detail page shows Convergence Reflection rows with stubborn segments and strategy-upgrade rationale after repeated minor/no drops.
- Good: detail page shows Prompt Evolution learning rows explaining why the previous prompt failed and which safe patch was used next.
- Good: detail page shows length-correction metadata when Zhuque reduce output was repaired to stay within ±10% of the original segment length.
- Good: detail page shows "逃逸改写" when a repeated-stagnation round uses `rewrite_mode="breakthrough"`.
- Good: detail page shows "论文重构" with Chinese/English language, section, AI pattern, candidate count, and fact-card metadata when a stubborn paper paragraph uses `rewrite_mode="paper_reconstruction"`.
- Good: detail page shows "回滚保护" when a round regresses, including the restored segment indices and risk-rate rollback.
- Base: no report yet; result page still shows original/optimized text and a non-crashing empty report.
- Bad: UI treats `labels_ratio[0]` as AI, shows a fixed "20%" threshold unrelated to backend config without matching tests, or marks browser connected just because launch was attempted.
- Bad: UI calls `startOptimization` after preflight returns `ready=false`, or displays estimated max credits as already charged beer.

### 6. Tests Required

- Static/frontend tests should assert mode option text, launcher/status endpoint strings, browser status polling state usage, report field rendering, and `zhuque_reduced_text` final-text priority.
- Static/frontend tests should assert readiness/preflight endpoint strings, readiness field rendering, preflight usage before start, Agent trace/reflection/prompt-evolution/length-correction/rewrite-mode panel strings, and `zhuque_detect` / `zhuque_reduce` SSE handling.
- Static/frontend tests should assert Paper Reconstruction trace strings: `paper_reconstruction`, "论文重构", `paper_language`, `paper_section`, `paper_ai_patterns`, `candidate_count`, and `fact_card_count`.
- Static/frontend tests should assert rollback protection strings: `rollback_applied` and "回滚保护".
- Build must pass with `npm.cmd run build` on Windows PowerShell environments where `npm.ps1` may be blocked by execution policy.
- After any production frontend change, sync `package/frontend/dist` into `package/static` before committing. Because `package/static` is ignored, new hashed assets must be staged with `git add -f package/static/...`; old hashed assets must be staged as deletions so `package/static/index.html` never points at missing files.

### 7. Wrong vs Correct

#### Wrong

```jsx
const finalText = segments.map(seg => seg.enhanced_text || seg.polished_text || seg.original_text);
const aiRate = Number(result.labels_ratio?.[0] || 0) * 100;
```

#### Correct

```jsx
const finalText = segments.map(
  seg => seg.zhuque_reduced_text || seg.enhanced_text || seg.polished_text || seg.original_text
);
const aiRate = Number(result.labels_ratio?.[1] || result.labels_ratio?.["1"] || 0) * 100;
const suspiciousRate = Number(result.labels_ratio?.[2] || result.labels_ratio?.["2"] || 0) * 100;
const riskRate = Math.max(aiRate, suspiciousRate);
```
