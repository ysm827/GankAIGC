# Implement Plan: VPS Browser-Agent Zhuque Detection

## Operating Rule

Complete one step at a time:

1. implement the step,
2. run that step's validation commands,
3. record the result in this file,
4. tick the checkbox before moving to the next step.

Do not batch multiple phases without validation.

## Current Status

- [x] PRD written.
- [x] Design written.
- [x] Implementation plan written.
- [x] Phase 1 complete: backend data model + migrations.
- [x] Phase 2 complete: browser-agent pairing/status APIs.
- [x] Phase 3 complete: browser-agent job APIs/state machine.
- [x] Phase 4 complete: Zhuque transport selection + backend pipeline integration.
- [x] Phase 5 complete: Chrome extension MVP.
- [x] Phase 6 complete: frontend browser-agent UX.
- [x] Phase 7 complete: docs/config/deployment update.
- [ ] Phase 8 complete: end-to-end VPS/browser manual validation.

## Phase 0: Planning Artifacts

### Checklist

- [x] Create Trellis task directory.
- [x] Capture requirements in `prd.md`.
- [x] Define API contracts, database schema, and state machines in `design.md`.
- [x] Define step-by-step implementation and validation in `implement.md`.

### Validation

```bash
ls .trellis/tasks/07-06-vps-browser-agent-zhuque-detection
```

Expected files:

```text
prd.md
design.md
implement.md
```

---

## Phase 1: Backend Data Model + Migration

### Goal

Create durable database storage for browser-agent pairing, agent identity, and Zhuque agent jobs.

### Files

Likely files:

```text
package/backend/app/models/models.py
package/backend/app/database.py
package/backend/migrations/versions/*.py
package/backend/tests/test_browser_agent.py
```

### Checklist

- [x] Add `BrowserAgentPairing` model.
- [x] Add `BrowserAgent` model.
- [x] Add `ZhuqueAgentJob` model.
- [x] Add indexes for `user_id`, `agent_id`, `job_id`, `status`, `expires_at`.
- [x] Add migration or startup-safe schema sync consistent with project conventions.
- [x] Add model-level constants/enums for statuses in one shared backend module.
- [x] Add tests proving tables/fields are available in test DB.

### Status Constants

Define one source of truth, e.g.:

```python
BROWSER_AGENT_ONLINE = "online"
BROWSER_AGENT_OFFLINE = "offline"
BROWSER_AGENT_REVOKED = "revoked"

ZHUQUE_AGENT_JOB_PENDING = "pending"
ZHUQUE_AGENT_JOB_CLAIMED = "claimed"
ZHUQUE_AGENT_JOB_RUNNING = "running"
ZHUQUE_AGENT_JOB_MANUAL_REQUIRED = "manual_required"
ZHUQUE_AGENT_JOB_COMPLETED = "completed"
ZHUQUE_AGENT_JOB_FAILED = "failed"
ZHUQUE_AGENT_JOB_EXPIRED = "expired"
ZHUQUE_AGENT_JOB_CANCELLED = "cancelled"
```

### Validation

```bash
package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q -k 'models or schema'
package/venv/bin/python -m pytest package/backend/tests/test_task_queue.py -q
```

### Tick After Passing

- [x] Phase 1 tests passed. Validation: `package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q` -> 3 passed; `package/venv/bin/python -m pytest package/backend/tests/test_task_queue.py -q` -> 6 passed.

---

## Phase 2: Browser-Agent Pairing and Status APIs

### Goal

Allow a web user to generate a pairing code and a Chrome extension to claim it, then heartbeat online status.

### Files

Likely files:

```text
package/backend/app/schemas.py
package/backend/app/routes/browser_agent.py
package/backend/app/services/browser_agent_service.py
package/backend/app/main.py or route registration file
package/backend/tests/test_browser_agent.py
```

### API Contract

Web user:

```text
POST /api/browser-agent/pairings
GET  /api/browser-agent/status
POST /api/browser-agent/revoke
```

Extension:

```text
POST /api/browser-agent/claim
POST /api/browser-agent/heartbeat
```

### Checklist

- [x] Add request/response schemas.
- [x] Add pairing code generation with TTL.
- [x] Store only pairing code hash.
- [x] Add claim flow that creates/updates agent and returns opaque token.
- [x] Store only agent token hash server-side.
- [x] Add bearer-token auth helper for extension routes.
- [x] Add heartbeat update and computed online/offline status.
- [x] Add revoke endpoint.
- [x] Register route under `/api/browser-agent`.
- [x] Add tests for success and auth failures.

### Required Tests

- [x] Authenticated user can create pairing code.
- [x] Expired pairing cannot be claimed.
- [x] Claimed pairing cannot be reused.
- [x] Invalid pairing code fails.
- [x] Claim returns token only once.
- [x] Heartbeat updates `last_seen_at`.
- [x] `GET /status` reports online when heartbeat fresh.
- [x] `GET /status` reports offline when heartbeat stale.
- [x] Revoked agent cannot heartbeat or claim jobs.
- [x] User A cannot see/revoke User B's agent.

### Validation

```bash
package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q -k 'pairing or heartbeat or revoke or status'
package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q -k 'browser_start or zhuque_remote_login'
```

### Tick After Passing

- [x] Phase 2 tests passed. Validation: `package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q -k 'pairing or heartbeat or revoke or status'` -> 4 passed; `package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q -k 'browser_start or zhuque_remote_login'` -> 8 passed.

---

## Phase 3: Browser-Agent Job APIs and State Machine

### Goal

Add persistent job dispatch so the worker can create a Zhuque detection job and the extension can claim/complete/fail it.

### Files

Likely files:

```text
package/backend/app/schemas.py
package/backend/app/routes/browser_agent.py
package/backend/app/services/browser_agent_service.py
package/backend/tests/test_browser_agent.py
```

### API Contract

Extension:

```text
POST /api/browser-agent/jobs/claim
POST /api/browser-agent/jobs/{job_id}/progress
POST /api/browser-agent/jobs/{job_id}/complete
POST /api/browser-agent/jobs/{job_id}/fail
```

Internal service:

```python
create_zhuque_job(user_id, text, session_id=None, segment_id=None, timeout=None)
wait_for_zhuque_job(job_id, timeout)
expire_stale_jobs()
```

### Checklist

- [x] Add job creation service method.
- [x] Add atomic job claim using row lock / skip locked where supported.
- [x] Add progress endpoint for `running` and `manual_required`.
- [x] Add complete endpoint with result JSON validation.
- [x] Add fail endpoint with `error_code`, `message`, `retryable`.
- [x] Add job heartbeat/progress timestamp update.
- [x] Add expiry handling.
- [x] Enforce user/agent/job ownership on every extension endpoint.
- [x] Ensure full `payload_text` is never logged.

### Required State Tests

- [x] `pending -> claimed -> running -> completed`.
- [x] `running -> manual_required -> running -> completed`.
- [x] `pending -> expired`.
- [x] `running -> failed`.
- [x] `running -> cancelled` if session cancelled.
- [x] Two agents cannot claim the same job.
- [x] Agent for User A cannot claim User B's job.
- [x] Completing a non-owned or terminal job fails.

### Validation

```bash
package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q -k 'job or claim or complete or fail or manual_required'
```

### Tick After Passing

- [x] Phase 3 tests passed. Validation: `package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q -k 'job or claim or complete or fail or manual_required'` -> 7 passed; full `test_browser_agent.py` -> 10 passed.

---

## Phase 4: Zhuque Transport Selection + Pipeline Integration

### Goal

Make `AI检测 + 降重` use browser-agent jobs on VPS while preserving local browser behavior for local deployments.

### Files

Likely files:

```text
package/backend/app/config.py
package/backend/app/services/zhuque_service.py
package/backend/app/services/zhuque_api.py
package/backend/app/services/zhuque_browser_agent_transport.py
package/backend/app/services/optimization_service.py
package/backend/tests/test_zhuque_integration.py
package/backend/tests/test_browser_agent.py
```

### Checklist

- [x] Add config: `ZHUQUE_DETECT_TRANSPORT`.
- [x] Add config: `ZHUQUE_SERVER_HEADLESS_FALLBACK`.
- [x] Add config: browser-agent timeout/heartbeat/long-poll values.
- [x] Create a transport selector at the Zhuque service boundary.
- [x] Implement `BrowserAgentZhuqueTransport.detect()` using job creation + wait.
- [x] Ensure `browser_agent` mode does not call server Playwright detection by default.
- [x] Keep existing local-browser path untouched for local deployments.
- [x] Return actionable error when no online agent is available.
- [x] Emit compact progress/SSE metadata for `manual_required`.
- [x] Normalize returned browser-agent result through existing Zhuque result contracts.

### Transport Selection Rules

```text
ZHUQUE_DETECT_TRANSPORT=browser_agent
  -> require browser agent unless explicit fallback enabled

ZHUQUE_DETECT_TRANSPORT=local_browser
  -> use existing local/browser/CDP behavior

ZHUQUE_DETECT_TRANSPORT=server_headless
  -> use existing server Playwright behavior

ZHUQUE_DETECT_TRANSPORT=auto
  -> local desktop/visible env may use local_browser
  -> Docker/VPS docs/config should set browser_agent explicitly
```

### Required Tests

- [x] `browser_agent` mode with no online agent returns actionable readiness/preflight/start error.
- [x] `browser_agent` mode with online agent creates a `zhuque_agent_jobs` row.
- [x] Browser-agent completed job continues pipeline with returned result.
- [x] Browser-agent failed job fails with user-facing message.
- [x] Browser-agent manual-required job keeps waiting until complete or timeout.
- [x] Server Playwright detect function is not called in `browser_agent` mode when fallback disabled.
- [x] Existing local-window/browser reuse tests still pass.

### Validation

```bash
package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q
package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q
package/venv/bin/python -m py_compile package/backend/app/services/zhuque_service.py package/backend/app/services/zhuque_api.py
```

### Tick After Passing

- [x] Phase 4 tests passed. Validation: `package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q` -> 14 passed; `package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q` -> 126 passed.

---

## Phase 5: Chrome Extension MVP

### Goal

Create an unpacked Chrome extension that can pair with the VPS, stay online, claim a Zhuque job, execute it in the user's local Chrome, and return a result.

### Files

New directory:

```text
browser-extension/
├── manifest.json
├── background.js
├── content-zhuque.js
├── injected-zhuque.js
├── popup.html
├── popup.js
├── styles.css
└── README.md
```

### Checklist

- [x] Add Manifest V3 extension skeleton.
- [x] Add popup for server URL, pairing code, connection status, and reconnect/revoke actions.
- [x] Store server URL and agent token in `chrome.storage.local`.
- [x] Implement claim pairing API call.
- [x] Implement heartbeat alarm.
- [x] Implement long-poll job claim loop.
- [x] Implement opening/reusing Zhuque tab.
- [x] Implement content script command channel.
- [x] Implement page logic to clear input, set text, click detect.
- [x] Implement result observation via network payload and DOM fallback.
- [x] Implement `manual_required` detection for CAPTCHA/login.
- [x] Implement complete/fail/progress API calls.
- [x] Add extension README with developer-mode loading instructions.

### Manual Validation

1. Open Chrome:

```text
chrome://extensions
```

2. Enable developer mode.
3. Load `browser-extension/` unpacked.
4. Pair with local/VPS backend.
5. Confirm backend status shows online.
6. Create a fake browser-agent job through test/debug endpoint or running a task.
7. Confirm extension claims it.
8. Confirm Zhuque tab opens locally.
9. Confirm result is sent back or manual-required is shown.

### Tick After Passing

- [x] Phase 5 manual extension MVP passed. Local syntax validation passed: `node --check browser-extension/background.js browser-extension/content-zhuque.js browser-extension/injected-zhuque.js browser-extension/popup.js`; manual WSL + Windows Chrome validation passed with pairing, heartbeat, job claim, Zhuque tab execution, result completion, and corrected result normalization.

---

## Phase 6: Frontend Browser-Agent UX

### Goal

Expose browser-agent state in the workspace and block/guide users correctly in VPS mode.

### Files

Likely files:

```text
package/frontend/src/api/index.js
package/frontend/src/pages/WorkspacePage.jsx
package/frontend/src/pages/SessionDetailPage.jsx
package/frontend/src/index.css
package/backend/tests/test_frontend_*.py
```

### Checklist

- [x] Add API client functions for browser-agent pairings/status/revoke.
- [x] Workspace Zhuque card branches by transport.
- [x] Add pairing code UI.
- [x] Add plugin install/load instructions.
- [x] Add online/offline/busy/manual-required states.
- [x] Start/preflight blocks when `browser_agent` is required but offline.
- [x] Session detail shows browser-agent progress/manual-required messages.
- [x] Local deployment copy remains local-browser oriented.
- [x] Keep Apple workspace visual conventions.
- [x] If frontend source changes, rebuild and sync `package/static`.

### Validation

```bash
cd package/frontend && npm run build
cd /home/dev/code/GankAIGC && package/venv/bin/python -m pytest package/backend/tests/test_frontend_redeem_entry.py -q
```

If static sync is required:

```bash
rm -rf package/static/*
cp -a package/frontend/dist/. package/static/
git add package/frontend package/static
```

### Tick After Passing

- [x] Phase 6 frontend build/tests passed. Validation: `cd package/frontend && npm run build` -> passed; synced `package/frontend/dist` to `package/static`; `package/venv/bin/python -m pytest package/backend/tests/test_frontend_redeem_entry.py -q` -> 71 passed.

---

## Phase 7: Docs and Deployment Config

### Goal

Document the new VPS/browser-agent requirement and preserve local deployment instructions.

### Files

```text
README.md
package/README.md
.env.docker.example
browser-extension/README.md
.trellis/spec/backend/quality-guidelines.md
.trellis/spec/frontend/component-guidelines.md
```

### Checklist

- [x] Document VPS requires Chrome extension for reliable Zhuque detection.
- [x] Document local deployment still uses automatic local browser.
- [x] Document extension installation and pairing.
- [x] Document config values:
  - `ZHUQUE_DETECT_TRANSPORT=browser_agent` for VPS.
  - `ZHUQUE_SERVER_HEADLESS_FALLBACK=false`.
  - local `ZHUQUE_DETECT_TRANSPORT=local_browser` or `auto`.
- [x] Document no public CDP / no `--remote-debugging-port` requirement.
- [x] Update specs with final contracts learned during implementation.

### Validation

```bash
git diff --check
rg -n "ZHUQUE_DETECT_TRANSPORT|browser_agent|Chrome 插件|本机浏览器" README.md package/README.md .env.docker.example browser-extension/README.md
```

### Tick After Passing

- [x] Phase 7 docs/config passed. Validation: `git diff --check` passed; `rg -n "ZHUQUE_DETECT_TRANSPORT|browser_agent|Chrome 插件|本机浏览器" README.md package/README.md .env.docker.example browser-extension/README.md` confirmed docs/config coverage.

---

## Phase 8: End-to-End VPS/Browser Manual Validation

### Goal

Prove the feature works in the deployment mode it is meant for.

### Setup

VPS `.env.docker`:

```env
ZHUQUE_DETECT_TRANSPORT=browser_agent
ZHUQUE_SERVER_HEADLESS_FALLBACK=false
INLINE_TASK_WORKER_ENABLED=false
```

Deploy:

```bash
docker compose --env-file .env.docker up -d --build
```

Watch logs:

```bash
docker compose --env-file .env.docker logs -f app worker
```

### Checklist

- [ ] User can load VPS web app.
- [ ] Workspace says browser-agent is required/offline before pairing.
- [ ] User generates pairing code.
- [ ] Chrome extension pairs successfully.
- [ ] Workspace shows plugin online.
- [ ] User opens/logs into Zhuque in local Chrome.
- [ ] User starts `AI检测 + 降重`.
- [ ] VPS worker creates browser-agent job.
- [ ] Extension claims job and runs Zhuque in local Chrome.
- [ ] If CAPTCHA appears, frontend shows manual-required and task waits.
- [ ] After Zhuque result, backend continues reduce pipeline.
- [ ] Final session completes or fails for expected reduce reasons, not server-headless CAPTCHA.
- [ ] VPS logs do not show server headless Playwright Zhuque detection in browser-agent mode.

### Tick After Passing

- [ ] Phase 8 E2E validation passed.

---

## Final Quality Gate Before Commit

Run:

```bash
package/venv/bin/python -m pytest package/backend/tests/test_browser_agent.py -q
package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q
package/venv/bin/python -m pytest package/backend/tests/test_task_queue.py -q
cd package/frontend && npm run build
cd /home/dev/code/GankAIGC && git diff --check
```

Final checklist:

- [ ] All backend tests passed.
- [ ] Frontend build passed.
- [ ] Static assets synced if needed.
- [ ] README/package README updated.
- [ ] Extension README updated.
- [ ] Specs updated for any learned contracts.
- [ ] `implement.md` phase checkboxes reflect actual completion.
- [ ] Commit created.
- [ ] Push only after user approval.
