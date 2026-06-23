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

## Scenario: Starlette TestClient Requires httpx2

### 1. Scope / Trigger

- Trigger: any change to backend test dependencies, `fastapi`, `starlette`, `httpx`, `httpx2`, or tests using `fastapi.testclient.TestClient`.

### 2. Contract

- Keep `httpx2` declared in both backend dependency manifests while the project uses `fastapi==0.136.1` / `starlette==1.3.1`.
- `httpx[socks]` is still used by runtime services; do not replace it with `httpx2`.
- `httpx2` is required by Starlette's `testclient` path and prevents:
  - `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`

### 3. Validation

```bash
package/venv/bin/python - <<'PY'
import warnings
from starlette.exceptions import StarletteDeprecationWarning
warnings.simplefilter("error", StarletteDeprecationWarning)
from fastapi.testclient import TestClient  # noqa: F401
print("TestClient import OK")
PY
```

---

## Scenario: Admin Operations Status Must Report Real Runtime Metrics

### 1. Scope / Trigger

- Trigger: any change to `package/backend/app/services/operations_service.py`, `GET /api/admin/operations/status`, or the admin operations panel data contract.
- This endpoint is an operations/observability surface; it must report real collected state or explicit unavailability, never invented demo values.

### 2. Signatures

- API:
  - `GET /api/admin/operations/status`.
- Response top-level fields:
  - `collected_at`, `system`, `database`, `worker`, `models`, `jobs`, `events`, `backup`, `onboarding`, `update`, `app`.
- Real metrics:
  - `system.cpu.percent`, `physical_cores`, `logical_cpus`.
  - `system.memory.percent`, `used_label`, `total_label`.
  - `system.disk.percent`, `used_label`, `total_label`, `backup_file_count`.
  - `system.network.rx_rate_label`, `tx_rate_label`, `available`.
  - `system.load.load1`, `load5`, `load15`.
  - `database.average_latency_ms`, `latency_samples_ms`, `slow_query_count`.
  - `models.items[]` with `stage`, `label`, `model`, `base_url`, `ok`, `message`.
  - `jobs.scheduled_count`, `completed_count`, `processing_count`, `queued_count`, `failed_count`.
  - `events[]` with `text`, `badge`, `tone`, `timestamp`.

### 3. Contracts

- Use real runtime sources:
  - Linux `/proc` for CPU, memory, network and uptime when available.
  - `shutil.disk_usage()` for disk usage.
  - `os.getloadavg()` for load when available.
  - PostgreSQL `SELECT 1` timing samples for database latency.
  - `pg_stat_activity` for slow active query count when permission allows; otherwise return `None`/`不可用`.
  - SQLAlchemy queries for worker/session/job/event counts.
- Do not add heavy dependencies such as `psutil` unless the project explicitly accepts the packaging cost; stdlib/procfs collection is preferred.
- First CPU/network requests may take a tiny local sample window; never fabricate stable placeholders.
- If a runtime source is unavailable, return `available=false`, `ok=false` where appropriate, and `不可用` labels. Do not substitute pretty constants.
- If database queries fail after the basic connection check fails, worker/job/event/onboarding helpers must catch the error, roll back the session, and return unavailable/partial status instead of turning the operations endpoint into HTTP 500.
- Model readiness in this endpoint means configuration completeness and placeholder detection only. Actual network/API connectivity remains the explicit `/operations/model-test` action.

### 4. Validation & Error Matrix

- `/proc` missing -> affected `system.*.available=false` or load `available=false`, endpoint still 200.
- PostgreSQL connection fails -> `database.ok=false`; endpoint should still include `system`, `models`, `backup`, `update`, and partial worker/job/onboarding status.
- `pg_stat_activity` permission/query fails -> `database.slow_query_count=null`, not endpoint failure.
- Model API key/base URL has placeholder values (`pwd`, `IP:PORT`, etc.) -> corresponding `models.items[].ok=false`.

### 5. Good/Base/Bad Cases

- Good: page shows current host CPU/memory/disk/load, real DB latency samples, real worker queue counts, and recent task/backup events.
- Base: Windows/non-Linux runtime has no `/proc`; page shows explicit unavailable states for procfs-only metrics.
- Bad: API or frontend hardcodes `18%`, `46%`, `3.6 GB / 7.8 GB`, `↑ 1.2 MB/s ↓ 2.4 MB/s`, `2.42 ms`, static model provider rows, or fake recovery events.

### 6. Tests Required

- Backend tests should assert `/operations/status` includes `collected_at`, `system`, `database.average_latency_ms`, `latency_samples_ms`, `worker.capacity`, `models.items`, `jobs`, and `events`.
- Backend tests should assert helper functions return unavailable/partial status when DB query calls raise.
- Frontend static tests should assert operations panel reads backend status fields and rejects fake constants.

### 7. Wrong vs Correct

#### Wrong

```jsx
{ icon: Cpu, title: 'CPU 使用率', value: '18%', meta: '4 核 / 8 线程' }
{ icon: Globe2, title: '网络状态', value: '正常', meta: '↑ 1.2 MB/s ↓ 2.4 MB/s' }
```

#### Correct

```jsx
value: percentValue(status?.system?.cpu?.percent)
meta: `↑ ${status?.system?.network?.tx_rate_label || '不可用'} ↓ ${status?.system?.network?.rx_rate_label || '不可用'}`
```

---

## Scenario: Zhuque AI Detect-Reduce Pipeline Contract

### 1. Scope / Trigger

- Trigger: any change to `ai_detect_reduce`, Zhuque 无头 API integration, optimization billing, retry flow, SSE progress, or session export.
- This is a cross-layer contract: database fields, backend service flow, API schemas, legacy credential endpoint URLs, frontend report rendering, and tests must stay aligned.

### 2. Signatures

- API:
  - `POST /api/optimization/start` accepts `processing_mode="ai_detect_reduce"`.
  - `PATCH /api/optimization/sessions/{session_id}/project` accepts `{project_id: int | null}` and moves one session into an active paper project or back to unfiled.
  - `POST /api/optimization/sessions/{session_id}/retry` must preserve Zhuque retry state.
  - `POST /api/optimization/zhuque/browser/start` is a legacy URL name; by default it starts the Zhuque real-page session sync window with `sync_session=true` and returns `{status, auth_mode="headless_api", login_mode="wechat_qr", credential_file, sync_session, command?, message}`.
  - `GET /api/optimization/zhuque/browser/status` is a legacy URL name; it returns credential status `{status, connected, ready, has_token, remaining_uses, button_enabled, auth_mode, login_mode, credential_file, user_name, quota_text, captured_at, message}`.
  - `GET /api/optimization/zhuque/readiness` returns Zhuque credential/API readiness without consuming a detection use.
  - `POST /api/optimization/zhuque/preflight` accepts `{original_text, processing_mode, billing_mode}` and returns readiness plus cost estimates without creating a session.
- DB:
  - `users.zhuque_free_uses_remaining`, `users.zhuque_total_uses`.
  - `optimization_sessions.zhuque_agent_trace` stores compact JSON trace for Zhuque Agent decisions.
  - `optimization_segments.zhuque_detect_rate`, `zhuque_detect_result`, `zhuque_detect_count`, `zhuque_reduce_attempt`, `zhuque_reduced_text`.
  - `zhuque_prompt_memories` stores Prompt Evolution metadata: failure signature, prompt patch, source, before/after rates, success/failure counters, and enabled state.
- Service:
  - `OptimizationService._process_ai_detect_reduce()` owns the full-text detect → selective reduce → full-text recheck loop.
  - `ZhuqueService.detect(text)` is serialized through the singleton queue.

### 3. Contracts

- Detection is a Zhuque-side quota operation and must not create GankAIGC beer transactions.
- Login/setup uses `zhuque_pkg/capture_zhuque_creds.py --sync-session` from the workspace button. This opens the real Zhuque page and watches the page state: when Zhuque is logged in it saves/updates `creds_latest.json`; when the Zhuque page itself shows logged out for consecutive polls it removes `creds_latest.json` and persists the logged-out `browser_state.json`. Clicking GankAIGC's already-logged-in button must not pre-delete credentials or auto-logout the page; only a real logout inside the Zhuque page counts as logout. After `creds_latest.json` exists, detection must go directly through the Zhuque WebSocket API. Do not resurrect local page-control/CDP detection logic.
- The credential file default search order must prefer the repo-level `zhuque_pkg/creds_latest.json` so `cd package && python main.py` and repo-root tooling agree. `ZHUQUE_CREDENTIALS_FILE` may override it.
- Zhuque remaining-use values are not guaranteed to exist in `quotaText`; current live pages can expose quota via `availableUses`, `remainingUses`, `remaining_uses`, button text such as `Detect now(18 left)`, or Chinese quota copy. Backend code must normalize all of these. `creds_latest.json` captures quota at login time and is stale after detections; `ZhuqueService.readiness()` and `start()` must refresh quota through `ZhuqueAPI.peek_remaining_uses()` when a token exists. The peek sends only auth data and closes before captcha/text submission, so it must not consume a detection use. Throttle passive workspace probes (current guard: `ZHUQUE_QUOTA_REFRESH_INTERVAL_SECONDS`) and force-refresh preflight/start paths with real text. A displayed `-1` means unknown, not zero.
- `POST /zhuque/browser/start` may return `manual_required` when the Python `playwright` package or a controllable Chromium/Chrome browser is missing. On WSL, a Windows-installed Chrome/Edge/Brave under `/mnt/c/.../*.exe` counts as controllable: the capture script must launch it as a small app window with a dedicated `--remote-debugging-port` and connect via Chrome DevTools Protocol so the visible QR window appears on the user's Windows desktop while GankAIGC can still sync cookies/localStorage. It must not return `started` if the real-page sync window cannot open; otherwise users see a false positive while no login/logout state can be synced.
- Start/retry in `platform` mode for `ai_detect_reduce` must leave `charge_status="not_charged"` and `charged_credits=0`; only actual LLM reduce calls create `reason="zhuque_reduce"` transactions.
- Session project assignment is a metadata move only: it must verify the session belongs to the current user, verify the target `PaperProject` belongs to the same user and is not archived, update only `OptimizationSession.project_id/updated_at`, and never mutate segment text, billing fields, or task status. `project_id=null` means move the session back to unfiled.
- `ai_detect_reduce` start must run a preflight before creating a session:
  - text shorter than 350 chars -> HTTP 400, no session, no transaction
  - Zhuque unready -> HTTP 400 with actionable message, no session, no transaction
  - `byok` without saved/request provider config -> HTTP 400 before touching Zhuque readiness
- Each reduce operation charges 10 beers per segment before calling polish/enhance. If the user lacks enough beers, the LLM call must not run.
- The pipeline detects the joined full text once first. Risk rate is `max(labels_ratio["0"], labels_ratio["2"]) * 100` when `labels_ratio` is present; fallback to `rate`. `zhuque_pkg` v2 maps `0=AI`, `1=human`, `2=suspicious/mixed`; do not reuse the old `0=human,1=AI` mapping.
- Zhuque `segment_labels[].position` is relative to the joined text using `"\n\n"` separators. Only labels `0` (AI) and `2` (suspicious) select segments for rewrite. If usable positions are absent, rewrite all segments as a safe fallback.
- Retry after failure must detect `zhuque_reduced_text` first when present and continue from `max(zhuque_reduce_attempt) + 1`; it must not restart from original text.
- Export and session detail final text must prefer `zhuque_reduced_text`, then `enhanced_text`, then `polished_text`, then `original_text`.
- `POST /api/optimization/sessions/{session_id}/export` also supports `export_format="aigc_report_docx"` and `export_format="aigc_report_md"` for completed `ai_detect_reduce` sessions. The report must not replace the final-text export; it is a separate AIGC report artifact. It must include a summary and a per-segment table with segment index, length, risk/AI rate, AI-label rate, suspicious-label rate, human-label rate, and status. If Zhuque `segment_labels[].position` exists, map positions back to final exported segment text using the same `"\n\n"` separator convention; if positions are absent, fall back to the full-text risk/labels ratio for each segment and mark it as fallback-derived.
- Zhuque reduce output length is a hard service-side contract, not prompt-only guidance. For each rewritten segment, compare the final reduced text against `original_text` with `count_text_length`; accepted output must stay within ±10%. Retry may still start detection/rewrite from latest `zhuque_reduced_text`, but the length baseline remains the original segment to avoid carrying forward already-bloated text. If polish/enhance output exceeds the bound, run one `enhance_text` length-repair call using a "Zhuque length correction" prompt, still preserving facts, terminology, data, citations, and conclusions. If the repair still fails, fall back to the length-compliant polished result, original segment, or original round input; do not blindly truncate text.
- `zhuque_agent_trace` must be compact metadata only: event kind, round, strategy, rates, selected segment indices, decision, convergence reflection, message, and final diagnosis. Do not store full text in trace.
- Reduce trace/SSE events may include `length_adjustments`, containing compact per-segment metadata only: segment index, round, original length, before/after lengths, bounds, and repair acceptance. Do not store full original or repaired text in trace.
- Convergence reflection treats `old_rate - new_rate >= 1.0` as meaningful progress. Smaller positive drops and non-drops are stagnation signals, increment `stagnation_count`, mark repeated `stubborn_segment_indices`, and force the next stronger Zhuque strategy.
- Reflection trace events use `type="reflection"` and may include `rate_delta`, `stagnation_count`, `current_strategy`, `next_strategy`, `selected_segment_indices`, `stubborn_segment_indices`, `action`, and `message`.
- Reflection prompt notes may be appended to existing polish/enhance prompts when stagnation is observed, but the pipeline must still call the existing `polish_text` and `enhance_text` methods; do not add a separate planner/reducer LLM call for this agent.
- Prompt Evolution Agent may generate or reuse a safe `prompt_patch` when repeated stagnation/stubborn segments are present. It must derive a compact failure signature from trace/result metadata and must not store full original/reduced paper text in `zhuque_prompt_memories`.
- Prompt Evolution trace events use `type="prompt_evolution"` and may include `failure_signature`, `root_causes`, `prompt_patch`, `memory_id`, `source`, `safety_status`, and `blocked_reasons`.
- Prompt patch safety validation must reject detector-hacking tactics: zero-width/invisible characters, deliberate typos, homoglyphs, random punctuation, intentional grammar errors, and changing data/citations/conclusions. Unsafe generated patches fall back to the built-in safe strong-rewrite patch.
- Breakthrough Rewrite mode must activate after repeated stagnation reaches the strongest Zhuque strategy. In this mode the pipeline still calls `polish_text` and `enhance_text`, but it must use Zhuque-specific anti-template base prompts instead of the default "Nature/Science editor" or "style mimicry" prompts, because those default prompts can reinforce the exact regular academic tone Zhuque flags. Reduce trace/SSE events should include `rewrite_mode="breakthrough"` when active.
- Paper Reconstruction mode must activate after deeper repeated stagnation in the strongest Zhuque strategy. It is still implemented through the existing `polish_text` and `enhance_text` calls: `polish_text` generates paper-specific candidates, local scoring selects a candidate, and `enhance_text` finalizes it. It must not introduce a separate body-rewrite API. Trace/SSE events should include `rewrite_mode="paper_reconstruction"` plus compact metadata only: `paper_language`, `paper_section`, `paper_ai_patterns`, `candidate_count`, `candidate_selector`, selected candidate ids, and `fact_card_count`.
- Paper Reconstruction must support Chinese and English academic writing without casualizing the paper. It should preserve terms, numbers, citations, formulas, methods, results, and conclusions; identify common paper AI patterns such as template transitions, inflated significance, abstract noun stacks, generic contribution claims, and uniform sentence rhythm; and keep the existing ±10% Zhuque length contract.
- Zhuque reduce must be strictly monotonic-protected across rounds. Before each rewrite round, snapshot the selected segments. Accept the new rewrite only when the full-text recheck risk rate is lower than the previous round's risk rate. If the rate is equal or higher, restore the snapshot and record compact rollback metadata (`rollback_applied`, `rollback_reason="not_improved"`, `rolled_back_from_rate`, `rolled_back_to_rate`, `restored_segment_indices`). Do not spend an extra Zhuque detection just to recheck the restored snapshot; restore the previous saved text and previous detection metadata.
- If a task is already on the strongest strategy, has repeated stagnation, and a strict rollback still leaves the risk above threshold, run Plateau Auto-Recovery before giving up. The recovery pass must first generate up to three safe bulk candidates (`A/B/C`) through the existing `polish_text` + `enhance_text` path, run a full-text Zhuque recheck after each candidate, and accept only candidates with a lower risk rate than the current saved best. If all bulk candidates fail to lower risk, run a bounded segment-sweep phase over stubborn segments (highest-priority stubborn indices first, limited to the configured small segment count) with safe single-segment candidates, rechecking the joined full text after each attempt. Stop candidate search early when a candidate reaches the threshold; otherwise continue the main loop with the best lower-risk candidate.
- If bulk and segment-sweep candidates still cannot lower the risk, run Deep Reconstruction v2 before final exit. Deep Reconstruction must rebuild the paragraph from protected paper fact cards instead of synonym-level editing, using safe routes such as `evidence_first`, `method_first`, and `constraint_first`; it must still call the existing `polish_text` + `enhance_text` path, enforce the ±10% length contract, and record only compact trace metadata (`type="plateau_deep_reconstruction"`, routes, selected route, local scores, fact-card count, candidate rates, and status). It may accept only a candidate whose full-text Zhuque recheck rate is lower than the current saved best.
- If Plateau Auto-Recovery plus Deep Reconstruction v2 all flatline near the threshold, calibrate a detector floor instead of continuing to spend Zhuque uses and beer. A detector floor may be recorded when the current rate remains just above threshold, enough safe candidates have been tried, and candidate rates have near-zero spread. Trace must include `type="detector_floor"`, `rate`, `threshold`, `recommended_threshold`, `candidate_count`, `rate_spread`, and a message explaining that the best saved reduced text was preserved. The task remains `failed` unless the rate reaches the configured threshold; `plateau_exit.action` should be `detector_floor` when this diagnosis applies.

### 4. Validation & Error Matrix

- 微信扫码凭证 missing/expired -> task `failed`, error mentions WeChat QR login and credential capture guidance.
- Readiness endpoint credential missing/browser setup incomplete -> HTTP 200 with `ready=false`, `connected=false`, message/actions; it must not throw a blocking 500 for normal user setup issues.
- Start real-page session sync with missing Playwright package -> `{status:"manual_required"}` and command includes `pip install playwright`.
- Start real-page session sync with missing Chromium/Chrome -> `{status:"manual_required"}` and command includes `playwright install chromium`; do not report `started`. On WSL with Windows Chrome installed, this case should not fire; the launch env should include `ZHUQUE_CHROME_EXECUTABLE=/mnt/c/.../chrome.exe` and `ZHUQUE_CDP_PORT`.
- User clicks the workspace `已登录` button -> backend starts `capture_zhuque_creds.py --sync-session`; old `creds_latest.json` remains until the Zhuque page itself is observed as logged out.
- User logs in inside the Zhuque page and closes the sync window -> latest observed logged-in state remains saved, and the workspace status endpoint should continue to report logged in from `creds_latest.json`.
- Preflight endpoint must not click Zhuque detect or consume Zhuque quota.
- Zhuque page/button unusable or quota exhausted -> task `failed`, error tells the user to login/switch accounts/wait for quota restoration.
- Initial full-text detection returns `success=false` -> task `failed`; do not initialize or call LLM services.
- Full-text risk rate <= threshold -> complete without beer transactions and without modifying segment text.
- Risk rate remains above threshold after `ZHUQUE_MAX_REDUCE_ROUNDS` -> task `failed`; error includes current rate, threshold, per-run round count, and cumulative round count; trace final diagnosis should include stubborn segment indices when reflection identified them. Repeated strongest-strategy strict rollbacks must first try Plateau Auto-Recovery, Deep Reconstruction v2, and detector-floor calibration before final failure.
- Platform beer balance below 10 during an actual reduce call -> fail before polish/enhance; no partial LLM output should be written for that segment.
- Zhuque reduce output length drifts beyond ±10% -> length-repair call must run before saving `zhuque_reduced_text`; the recheck must detect the repaired/fallback text, not the bloated intermediate output.
- A reduce round lowers risk and a later round is equal or higher -> rollback protection restores the previous segment text/detection metadata and the trace marks `rollback_applied=true`.
- Trace JSON invalid/missing on older sessions -> session detail API still returns `zhuque_agent_trace=null`; frontend handles it as absent.
- Moving a session into another user's or archived project -> HTTP 404 "论文项目不存在"; moving another user's session -> HTTP 404 "会话不存在".
- AIGC report export requested for a non-`ai_detect_reduce` session -> HTTP 400 with a clear message; requested before any Zhuque detection metadata exists -> HTTP 400. `txt` and `pdf` remain rejected by schema unless explicitly reintroduced with tests.
- Prompt memory must survive startup schema creation and Alembic upgrade; missing table on existing deployments should be created by `Base.metadata.create_all()` during startup before migrations add indexes/columns.

### 5. Good/Base/Bad Cases

- Good: full text returns labels for only segments 1 and 3; only those segments run polish/enhance, two `zhuque_reduce` transactions are recorded, and the recheck writes the final report to all segments.
- Good: Workspace preflight sees ready Zhuque credentials and returns estimates, then start creates an `ai_detect_reduce` session with no `optimization_start` hold.
- Good: an unfiled session can be moved into `test1` through `PATCH /sessions/{session_id}/project`, disappears from `project_id=0`, appears under `project_id=<test1>`, and can be moved back with `project_id=null`.
- Good: Workspace `已登录` opens a sync window without deleting the old credential; if the user only closes the Zhuque page, GankAIGC remains logged in; if the user logs out in the Zhuque page, `creds_latest.json` is removed and the workspace becomes logged out.
- Good: QR capture is needed only before credentials exist; subsequent detections use WebSocket API and never need a local browser/debug port.
- Good: A high-risk session records trace events for initial detect and each reduce/recheck round, including strategy and risk-rate change.
- Good: A high-risk session whose first reduced output is too long records `length_adjustments`, saves a repaired/fallback text within ±10%, and rechecks that text.
- Good: A session with repeated minor drops records reflection events, upgrades strategy despite nominal rate decreases, and shows stubborn segments in final diagnosis if still above threshold.
- Good: A session with repeated stagnation records a `prompt_evolution` trace event, appends a safe strong-rewrite prompt patch to existing polish/enhance prompts, and records a compact prompt memory.
- Good: A session stuck at 100% for multiple rounds enters `rewrite_mode="breakthrough"`, stops using the default polish/enhance base prompts for that round, and records the rewrite mode in trace.
- Good: A session that remains stuck after breakthrough enters `rewrite_mode="paper_reconstruction"`, records Chinese/English paper pattern metadata, selects among 2-3 candidates by local AI-pattern score, preserves facts, and still enforces the ±10% length contract before Zhuque recheck.
- Good: A session reaches 34.9% and the next rewrite rechecks at 100%; the pipeline restores the 34.9% text instead of saving the 100% rewrite.
- Good: A session stuck near 25% after repeated strongest-strategy rollbacks records `type="plateau_recovery"` candidate rates, tries bulk candidates first, then bounded stubborn-segment sweep candidates, and accepts a lower-risk candidate when found. If those fail, it records `type="plateau_deep_reconstruction"` and may accept a lower-risk route such as `evidence_first`.
- Good: A session flatlining at `24.52%` against a `20%` threshold after bulk, segment-sweep, and deep-reconstruction candidates records `type="detector_floor"`, recommends a threshold such as `26%`, exits with `plateau_exit.action="detector_floor"`, and preserves the best saved text.
- Good: a completed `ai_detect_reduce` export with `aigc_report_docx`/`aigc_report_md` returns a separate "AIGC检测报告" filename, includes each final segment's text and per-segment AI rate, and still lets normal `docx`/`md` export return only the final paper text.
- Base: full text risk rate is below threshold; all segments keep original text, detect count is 1, and no beer transaction exists.
- Bad: retrying a failed `ai_detect_reduce` session with 0 beers pre-holds `optimization_start` or redetects original text; both violate the contract.
- Bad: AIGC report export uses `labels_ratio[1]` as AI, writes the report over the final paper export, omits segment rows, or reports raw `-1` remaining uses as a negative quota.
- Bad: `byok` start with no provider config calls Zhuque readiness first; this leaks setup order and can produce confusing Zhuque errors before the API config error.

### 6. Tests Required

- Billing: start and retry do not pre-hold platform credit for `ai_detect_reduce`; actual reduce charges `zhuque_reduce`.
- Pipeline: low-risk skip, high-risk selective rewrite by `segment_labels`, suspicious-label rewrite, no-label fallback, max-round failure, retry from latest reduced text, cumulative retry rounds, and length repair for bloated reduce output.
- Zhuque API: WebSocket success parsing, label mapping (`0=AI`, `1=human`, `2=suspicious`), and non-terminal frame ignore.
- WeChat credential capture: missing script, missing Playwright, missing browser runtime, subprocess env (`PLAYWRIGHT_BROWSERS_PATH`), and credential status endpoint connected/disconnected shapes.
- API/detail/export: `zhuque_detect_result` is serialized and final text prefers `zhuque_reduced_text`.
- Project assignment: tests must cover unfiled -> project, project -> unfiled, and rejection of another user's/archived project.
- AIGC report export: `aigc_report_docx` and `aigc_report_md` return distinct filenames, MIME types, and per-segment AI-rate rows mapped from `segment_labels[].position`; non-Zhuque sessions and missing report metadata return HTTP 400.
- Readiness/preflight: actionable response fields, 350-char blocking, no session/transaction on failure, `byok` config checked before Zhuque readiness.
- Remaining-use parsing: numeric API fields, `quotaText`, English button text (`left`), credential `remainingUses`, and live `peek_remaining_uses()` fallback. Tests must prove stale credential quota is replaced by live peek quota in readiness, and that repeated passive readiness calls are throttled instead of opening a WebSocket on every poll.
- Trace: schema/migration includes `zhuque_agent_trace`; high-risk flow records detect + reduce + reflection + prompt_evolution events; repeated-stagnation reduce events include `rewrite_mode`; detail response includes trace.
- Paper Reconstruction: repeated paper stagnation records `rewrite_mode="paper_reconstruction"`, language/section/pattern metadata, candidate selection metadata, and fact-card counts without storing full candidate text in trace.
- Rollback protection: regression after a previously improved round restores saved text and records rollback metadata in trace/SSE.
- Plateau Auto-Recovery: repeated strongest-strategy rollback first evaluates bulk automatic candidates, then bounded stubborn-segment sweep candidates if bulk fails, accepts the best lower-risk candidate, restores snapshots when candidates fail, and only exits after Deep Reconstruction v2 and detector-floor calibration have also been evaluated.
- Deep Reconstruction / Detector Floor: bulk+segment-sweep failure can still be rescued by `plateau_deep_reconstruction`; when all safe candidates flatline near threshold, trace records `detector_floor` with recommended threshold and keeps the session failed but diagnosable.
- Prompt Evolution: memory table exists after Alembic/startup; signature builder, safety validator, memory selection, and pipeline prompt patch insertion have regression tests.

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

#### Wrong

```python
def _start_zhuque_wechat_capture(*, switch_account: bool = False):
    if switch_account:
        Path("zhuque_pkg/creds_latest.json").unlink()  # GankAIGC click is not a real Zhuque logout
    subprocess.Popen([sys.executable, "capture_zhuque_creds.py", "--switch"])
```

#### Correct

```python
def _start_zhuque_wechat_capture(*, sync_session: bool = True):
    args = ["--sync-session"] if sync_session else []
    subprocess.Popen([sys.executable, "capture_zhuque_creds.py", *args])
# capture script deletes creds_latest.json only after the Zhuque page is observed as logged out.
```
