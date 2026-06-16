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


## Scenario: Apple Product Tile Workspace Theme

### 1. Scope / Trigger

- Trigger: any production UI theme or layout change in `package/frontend/src/pages/WorkspacePage.jsx`, `SessionDetailPage.jsx`, or shared app shell styling in `package/frontend/src/index.css`.
- Current visual direction: Apple website product tile language for a paper AI-reduction workspace. Use content-first white/light-gray sections, SF Pro/system typography, low chrome, and one interaction accent: Action Blue `#0066cc`; reserve dark tiles for local product moments rather than the global app chrome.
- This is a CSS/product-language approximation only. Do not copy Apple assets, screenshots, icons, product claims, or private design-system code.

### 2. Signatures

- Shared CSS tokens/classes in `src/index.css`:
  - Compatibility glass tokens that must remain for existing tests and fallbacks: `--glass-bg`, `--glass-bg-strong`, `--glass-bg-solid`, `--glass-border`, `--glass-edge`, `--glass-refraction`, `--glass-shadow`, `--glass-blur`, `--glass-radius-xl`, `--app-accent`.
  - Apple product tokens: `--apple-blue`, `--apple-blue-focus`, `--apple-blue-on-dark`, `--apple-ink`, `--apple-body-muted`, `--apple-canvas`, `--apple-parchment`, `--apple-pearl`, `--apple-hairline`, `--apple-dark-tile`.
  - Apple layout/component classes: `.apple-global-nav`, `.apple-subnav`, `.apple-product-tile`, `.apple-product-tile-dark`, `.apple-action-pill`, `.apple-ghost-pill`, `.apple-utility-card`, `.apple-paper-stage`, `.apple-paper-stage-preview`, `.apple-report-stage`, `.apple-reading-panel`, `.apple-metric-card`, `.apple-config-chip`.
  - Legacy compatibility classes still used by tests/pages: `.gank-app-page`, `.gank-ambient-orb`, `.gank-liquid-panel`, `.gank-liquid-section`, `.gank-text-panel`, `.gank-segmented-control`, `.gank-glass-status-grid`, `.gank-glass-choice-active`, `.gank-glass-choice-warm`, `.gank-agent-scroll`.
- Primary pages using the contract:
  - `src/pages/WorkspacePage.jsx`.
  - `src/pages/SessionDetailPage.jsx`.
- Production static bundle location:
  - Build output: `package/frontend/dist`.
  - Served bundle: `package/static`.

### 3. Contracts

- Use Action Blue `#0066cc` as the only interactive accent for primary CTAs, active choices, links, and product-stage highlights. Do not reintroduce warm orange/black pill CTA as the main theme.
- Workspace must include a light frosted `.apple-global-nav` plus frosted light `.apple-subnav`, followed by a full-width `.apple-product-tile.apple-paper-stage` hero containing `AI PAPER RECONSTRUCTION` and the paper flow chips: `Zhuque detection`, `paper reconstruction`, `full-text recheck`. Do not use a full-width black top bar for the workspace chrome.
- Use product-tile contrast intentionally: light/parchment paper stage for the main workspace, optional local dark tile (`.apple-product-tile-dark`) only inside hero/report content, and white utility cards for forms/report metrics.
- Primary actions should use `.apple-action-pill` and active press `scale(0.95)`. Secondary actions should use `.apple-ghost-pill` or a low-chrome text/link treatment.
- Utility/report cards should be low chrome: `18px` radius, hairline borders, minimal/no shadow. Heavy generic shadows and decorative gradients are not part of this direction except the single product-preview resting shadow.
- Keep legacy `.gank-*` class strings where tests or existing pages depend on them, but the visual source of truth for new theme work is the `.apple-*` class set above.
- Long reading surfaces, especially original/final paper text panels, must use `.gank-text-panel` plus `.apple-reading-panel` or an equally opaque background. Do not make paper body text translucent.
- Long Agent histories must remain inside `.gank-agent-scroll` plus `custom-scrollbar` and `max-h-[560px]` so the result/original text panels stay reachable.
- The app remains light-mode-first for readability; do not add automatic dark-mode overrides that make Tailwind `text-black`, `bg-white`, or `text-gray-*` content unreadable unless the pages are audited end-to-end.
- All translucent surfaces must have solid fallbacks through both:
  - `@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)))`.
  - `@media (prefers-reduced-transparency: reduce)`.
- After any production frontend change, run `npm.cmd run build`, sync `package/frontend/dist` into `package/static`, force-stage new ignored static assets, and stage old hashed assets as deletions.

### 4. Validation & Error Matrix

- Missing Apple tokens/classes in source -> `test_frontend_uses_apple_glass_theme_tokens` fails.
- Static bundle not synced after build -> the same test fails because it reads the CSS bundle referenced by `package/static/index.html`.
- Browser lacks `backdrop-filter` -> UI must fall back to solid readable surfaces, not transparent unreadable panels.
- User has reduced transparency enabled -> ambient orbs are hidden and surfaces become solid.
- Warm Tabbit/orange remnants become primary visual language -> visual review fails even if static string tests pass.
- Long Agent trace -> keep a bounded scroll container so final/original paper text remains reachable.

### 5. Good/Base/Bad Cases

- Good: Workspace uses `.apple-global-nav`, `.apple-subnav`, `.apple-product-tile.apple-paper-stage`, `.apple-action-pill`, `.apple-config-chip`, and keeps the existing task form, project list, billing copy, and Zhuque readiness flow.
- Good: Session detail shows a distinct `.apple-report-stage` "Detection report preview" shell, `.apple-utility-card` metric tiles, `.apple-reading-panel` text panes, and keeps Agent trace rows inside `.gank-agent-scroll`.
- Good: New CSS bundle in `package/static/index.html` references current hashed `assets/index-*.css` and contains the Apple + fallback tokens.
- Base: A small legacy `.gank-liquid-panel` wrapper can remain for compatibility if the visible card is governed by the Apple low-chrome tokens/classes.
- Bad: Editing only `frontend/dist` or only `package/static` without source changes.
- Bad: Copying Apple screenshots, icons, marketing claims, reference-site logos, or fake product imagery into GankAIGC.
- Bad: Reintroducing multiple accent colors, warm orange primary states, black primary pill buttons, full-width black workspace chrome, or decorative mesh gradients.
- Bad: Shipping only token changes that still look like the previous white-card workspace in screenshots.

### 6. Tests Required

- Static frontend test must assert source tokens/classes and page class usage.
- Static frontend test must also read the CSS bundle referenced by `package/static/index.html` to prove static sync happened.
- Run:
  - `cd package/frontend; npm.cmd run build`
  - `cd package/backend; python -m pytest tests/test_frontend_redeem_entry.py -q --basetemp D:\AI\TOOL\GankAIGC\package\backend\tmp-pytest`

### 7. Wrong vs Correct

#### Wrong

```jsx
<section className="gank-tabbit-hero rounded-[38px] bg-orange-50">
  <button className="gank-pill-button bg-black text-white">Start optimization</button>
</section>
```

#### Correct

```jsx
<section className="apple-product-tile apple-paper-stage gank-tabbit-hero">
  <p className="gank-eyebrow">AI PAPER RECONSTRUCTION</p>
  <a href="#new-task" className="apple-action-pill">Start optimization</a>
</section>
```

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
- Zhuque report risk rate in UI must use `max(labels_ratio[0], labels_ratio[2]) * 100` when `labels_ratio` is present, matching backend threshold semantics. `zhuque_pkg` v2 maps `0=AI`, `1=human`, `2=suspicious/mixed`.
- Session detail must parse `zhuque_agent_trace` defensively and render the "Agent 决策轨迹" panel when trace or live Zhuque SSE events exist. The trace list must live in a bounded-height scroll container so long multi-round histories do not push the final/original text panels off the page.
- When trace contains `type="reflection"` events, render them as "收敛反思" rows and show `stubborn_segment_indices`, `stagnation_count`, `current_strategy`, `next_strategy`, and `action` when present.
- When trace contains `type="prompt_evolution"` events, render them as "Agent 学习结果" rows and show root causes, source, safety status, and a collapsible `prompt_patch`.
- When trace or live `zhuque_reduce` events contain `length_adjustments`, render a "长度校正" summary with segment index, original length, before/after lengths, and bounds. This is metadata only; UI must not expect full text in the trace payload.
- When trace or live `zhuque_reduce` events contain `rewrite_mode`, render the mode. `rewrite_mode="breakthrough"` should be shown as "逃逸改写" so users can tell the agent has stopped using the default academic-polish base prompt after stagnation.
- When trace or live `zhuque_reduce` events contain `rewrite_mode="paper_reconstruction"`, render it as "论文重构" and show compact paper metadata when present: `paper_language`, `paper_section`, `paper_ai_patterns`, `candidate_count`, `candidate_selector`, and `fact_card_count`.
- When trace or live `zhuque_reduce` events contain `rollback_applied=true`, render a "回滚保护" summary with `rollback_reason`, `rolled_back_from_rate`, `rolled_back_to_rate`, and `restored_segment_indices` so users can see that an equal-or-worse rewrite did not overwrite a better previous version.
- When trace contains `type="plateau_exit"`, render it as "卡点退出" and explain that the best reduced text was preserved and the user should manually adjust stubborn paragraphs or change the threshold before retrying.
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
- Good: a long Agent trace is scrollable inside the trace card, and `plateau_exit` appears as "卡点退出" with manual-review guidance.
- Base: no report yet; result page still shows original/optimized text and a non-crashing empty report.
- Bad: UI treats `labels_ratio[1]` as AI, shows a fixed "20%" threshold unrelated to backend config without matching tests, or marks browser connected just because launch was attempted.
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
const aiRate = Number(result.labels_ratio?.[1] || 0) * 100;
```

#### Correct

```jsx
const finalText = segments.map(
  seg => seg.zhuque_reduced_text || seg.enhanced_text || seg.polished_text || seg.original_text
);
const aiRate = Number(result.labels_ratio?.[0] ?? result.labels_ratio?.["0"] ?? 0) * 100;
const suspiciousRate = Number(result.labels_ratio?.[2] ?? result.labels_ratio?.["2"] ?? 0) * 100;
const riskRate = Math.max(aiRate, suspiciousRate);
```
