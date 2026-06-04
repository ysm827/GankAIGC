# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)

---

## Scenario: Zhuque AI Detect-Reduce Pipeline Contract

### 1. Scope / Trigger

- Trigger: any change to `ai_detect_reduce`, Zhuque CDP integration, optimization billing, retry flow, SSE progress, or session export.
- This is a cross-layer contract: database fields, backend service flow, API schemas, browser launcher endpoints, frontend report rendering, and tests must stay aligned.

### 2. Signatures

- API:
  - `POST /api/optimization/start` accepts `processing_mode="ai_detect_reduce"`.
  - `POST /api/optimization/sessions/{session_id}/retry` must preserve Zhuque retry state.
  - `POST /api/optimization/zhuque/browser/start` returns `{status, port, url, user_data_dir}`.
  - `GET /api/optimization/zhuque/browser/status` returns `{status, connected, port, url, message}`.
  - `GET /api/optimization/zhuque/readiness` returns Zhuque page readiness without consuming a detection use.
  - `POST /api/optimization/zhuque/preflight` accepts `{original_text, processing_mode, billing_mode}` and returns readiness plus cost estimates without creating a session.
- DB:
  - `users.zhuque_free_uses_remaining`, `users.zhuque_total_uses`.
  - `optimization_sessions.zhuque_agent_trace` stores compact JSON trace for Zhuque Agent decisions.
  - `optimization_segments.zhuque_detect_rate`, `zhuque_detect_result`, `zhuque_detect_count`, `zhuque_reduce_attempt`, `zhuque_reduced_text`.
- Service:
  - `OptimizationService._process_ai_detect_reduce()` owns the full-text detect → selective reduce → full-text recheck loop.
  - `ZhuqueService.detect(text)` is serialized through the singleton queue.

### 3. Contracts

- Detection is a Zhuque-side quota operation and must not create GankAIGC beer transactions.
- Start/retry in `platform` mode for `ai_detect_reduce` must leave `charge_status="not_charged"` and `charged_credits=0`; only actual LLM reduce calls create `reason="zhuque_reduce"` transactions.
- `ai_detect_reduce` start must run a preflight before creating a session:
  - text shorter than 350 chars -> HTTP 400, no session, no transaction
  - Zhuque unready -> HTTP 400 with actionable message, no session, no transaction
  - `byok` without saved/request provider config -> HTTP 400 before touching Zhuque readiness
- Each reduce operation charges 10 beers per segment before calling polish/enhance. If the user lacks enough beers, the LLM call must not run.
- The pipeline detects the joined full text once first. Risk rate is `max(labels_ratio["1"], labels_ratio["2"]) * 100` when `labels_ratio` is present; fallback to `rate`.
- Zhuque `segment_labels[].position` is relative to the joined text using `"\n\n"` separators. Only labels `1` (AI) and `2` (suspicious) select segments for rewrite. If usable positions are absent, rewrite all segments as a safe fallback.
- Retry after failure must detect `zhuque_reduced_text` first when present and continue from `max(zhuque_reduce_attempt) + 1`; it must not restart from original text.
- Export and session detail final text must prefer `zhuque_reduced_text`, then `enhanced_text`, then `polished_text`, then `original_text`.
- `zhuque_agent_trace` must be compact metadata only: event kind, round, strategy, rates, selected segment indices, decision, message, and final diagnosis. Do not store full text in trace.

### 4. Validation & Error Matrix

- Chrome CDP unreachable -> task `failed`, error mentions the configured CDP port and the browser-launch guidance.
- Readiness endpoint CDP unreachable -> HTTP 200 with `ready=false`, `connected=false`, message/actions; it must not throw a blocking 500 for normal user setup issues.
- Preflight endpoint must not click Zhuque detect or consume Zhuque quota.
- Zhuque page/button unusable or quota exhausted -> task `failed`, error tells the user to login/switch accounts/wait for quota restoration.
- Initial full-text detection returns `success=false` -> task `failed`; do not initialize or call LLM services.
- Full-text risk rate <= threshold -> complete without beer transactions and without modifying segment text.
- Risk rate remains above threshold after `ZHUQUE_MAX_REDUCE_ROUNDS` -> task `failed`; error includes current rate, threshold, per-run round count, and cumulative round count.
- Platform beer balance below 10 during an actual reduce call -> fail before polish/enhance; no partial LLM output should be written for that segment.
- Trace JSON invalid/missing on older sessions -> session detail API still returns `zhuque_agent_trace=null`; frontend handles it as absent.

### 5. Good/Base/Bad Cases

- Good: full text returns labels for only segments 1 and 3; only those segments run polish/enhance, two `zhuque_reduce` transactions are recorded, and the recheck writes the final report to all segments.
- Good: Workspace preflight sees ready Zhuque page and returns estimates, then start creates an `ai_detect_reduce` session with no `optimization_start` hold.
- Good: A high-risk session records trace events for initial detect and each reduce/recheck round, including strategy and risk-rate change.
- Base: full text risk rate is below threshold; all segments keep original text, detect count is 1, and no beer transaction exists.
- Bad: retrying a failed `ai_detect_reduce` session with 0 beers pre-holds `optimization_start` or redetects original text; both violate the contract.
- Bad: `byok` start with no provider config calls Zhuque readiness first; this leaks setup order and can produce confusing Zhuque errors before the API config error.

### 6. Tests Required

- Billing: start and retry do not pre-hold platform credit for `ai_detect_reduce`; actual reduce charges `zhuque_reduce`.
- Pipeline: low-risk skip, high-risk selective rewrite by `segment_labels`, suspicious-label rewrite, no-label fallback, max-round failure, retry from latest reduced text, cumulative retry rounds.
- Zhuque API: WebSocket success parsing, label mapping (`0=human`, `1=AI`, `2=suspicious`), and non-terminal frame ignore.
- Browser launcher: configured port/profile in launched Chrome args, missing Chrome error, status endpoint connected/disconnected shapes.
- API/detail/export: `zhuque_detect_result` is serialized and final text prefers `zhuque_reduced_text`.
- Readiness/preflight: actionable response fields, 350-char blocking, no session/transaction on failure, `byok` config checked before Zhuque readiness.
- Trace: schema/migration includes `zhuque_agent_trace`; high-risk flow records detect + reduce events; detail response includes trace.

### 7. Wrong vs Correct

#### Wrong

```python
# Pre-holds beers at start/retry even though Zhuque may pass without LLM rewrite.
required_credits = calculate_optimization_credits(session.original_text, session.processing_mode)
CreditService(db).hold_platform_credit(user, reason="optimization_start", amount=required_credits)
```

#### Correct

```python
# Detect stage is free in GankAIGC; charge only immediately before an LLM reduce call.
if session.processing_mode == "ai_detect_reduce":
    session.charge_status = "not_charged"
    session.charged_credits = 0

CreditService(db).hold_platform_credit(
    user,
    reason="zhuque_reduce",
    session_id=session.id,
    amount=10,
)
```
