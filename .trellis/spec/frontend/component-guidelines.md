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
- Base: no report yet; result page still shows original/optimized text and a non-crashing empty report.
- Bad: UI treats `labels_ratio[0]` as AI, shows a fixed "20%" threshold unrelated to backend config without matching tests, or marks browser connected just because launch was attempted.
- Bad: UI calls `startOptimization` after preflight returns `ready=false`, or displays estimated max credits as already charged beer.

### 6. Tests Required

- Static/frontend tests should assert mode option text, launcher/status endpoint strings, browser status polling state usage, report field rendering, and `zhuque_reduced_text` final-text priority.
- Static/frontend tests should assert readiness/preflight endpoint strings, readiness field rendering, preflight usage before start, Agent trace panel strings, and `zhuque_detect` / `zhuque_reduce` SSE handling.
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
