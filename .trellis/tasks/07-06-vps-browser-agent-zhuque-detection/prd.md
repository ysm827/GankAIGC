# VPS browser-agent Zhuque detection

## Goal

Make Zhuque AI detection usable on VPS deployments by moving the Zhuque detection execution from the VPS/headless browser to the user's local Chrome browser through a Chrome extension browser agent.

The VPS remains responsible for GankAIGC auth, task orchestration, LLM rewrite/reduce work, persistence, billing, export, and progress UI. The user's local Chrome extension becomes the executor for Zhuque page interactions and result extraction.

## Problem

Current VPS mode uses server-side Playwright/Chromium. Zhuque can identify VPS/headless/server browser environments and trigger CAPTCHA/fraud controls. In practice this makes VPS deployment unusable for `AI检测 + 降重` when the detector requires a real user browser.

Local deployment should not regress: when GankAIGC runs on the user's own Windows/WSL/Linux desktop, the existing auto system-browser path should continue to be used without requiring a Chrome extension.

## Users / Personas

- **VPS operator**: deploys GankAIGC on a remote server and wants users to run Zhuque detection from their own browser to reduce risk controls.
- **End user**: accesses the VPS site, installs a Chrome extension, logs into Zhuque in their own browser, and keeps the extension online while GankAIGC tasks run.
- **Local user**: runs GankAIGC locally and should keep the current auto browser behavior with no extension requirement.

## Requirements

### Deployment mode selection

- Add a configuration contract for selecting Zhuque detection transport:
  - `auto`: default automatic selection.
  - `local_browser`: local desktop/WSL/Linux browser path, current behavior.
  - `browser_agent`: VPS Chrome-extension agent path, new recommended VPS mode.
  - `server_headless`: legacy VPS headless Playwright fallback, explicit only.
- VPS/Docker documentation must recommend `ZHUQUE_DETECT_TRANSPORT=browser_agent` and `ZHUQUE_SERVER_HEADLESS_FALLBACK=false`.
- Local deployment documentation must recommend keeping the current local browser path; local users should not be forced to install the extension.

### Browser agent pairing

- A logged-in GankAIGC user can generate a short-lived pairing code from the workspace.
- The Chrome extension can claim the pairing code and receive an agent token.
- The backend stores agent identity per GankAIGC user and tracks online/offline status through heartbeat.
- Users can revoke an agent.

### Browser agent job dispatch

- When the backend needs Zhuque detection in `browser_agent` mode, it creates a persistent database job.
- The browser extension claims pending jobs for its paired user.
- The extension executes the detection in the user's local Chrome against `https://matrix.tencent.com/ai-detect/`.
- The extension returns normalized Zhuque result payloads to the backend.
- The backend waits for job completion and continues the existing AI detect/reduce pipeline.
- No in-memory-only queue is allowed for this path because Docker uses separate `app` and `worker` processes.

### Local Chrome execution

- The extension must open or reuse one Zhuque detection tab.
- The extension must use the user's local Chrome session, IP, and Zhuque login state.
- If the user is not logged in to Zhuque, the extension/frontend must guide the user to log in in the local Zhuque tab.
- If CAPTCHA/manual verification appears, the extension/backend/frontend must surface `manual_required` and let the user complete it in the local Zhuque tab without failing immediately.

### Security

- Do not expose Chrome DevTools Protocol to the public internet.
- Do not require users to run Chrome with `--remote-debugging-port` for VPS mode.
- Chrome extension host permissions must be scoped to the GankAIGC site and `https://matrix.tencent.com/*`, not `<all_urls>`.
- Agent tokens must be stored hashed server-side and revocable.
- Browser agent APIs must require a valid agent token and must not accept cross-user job claims.
- Detection payloads/results must not be logged with full paper text.

### UX

- Workspace must clearly show browser-agent status in VPS mode:
  - not paired / offline / online / busy / manual required.
- Starting an `AI检测 + 降重` task in VPS browser-agent mode must fail fast or block with an actionable message if no agent is online.
- Session progress must tell the user when the local browser is running Zhuque detection and when manual verification is required.
- Local deployment UI should continue to use the existing local-browser copy and should not claim that a plugin is mandatory.

## Non-Goals / Out of Scope for MVP

- Chrome Web Store publishing.
- Firefox/Safari extensions.
- Multiple simultaneous browser agents per user with manual device selection.
- True same-user parallel Zhuque detections.
- Reading arbitrary user browser cookies or controlling non-Zhuque sites.
- Public CDP tunneling or remote-control desktop streaming.

## Acceptance Criteria

### Planning / documentation

- [x] PRD defines VPS browser-agent goal, local deployment boundary, and security constraints.
- [x] Design document defines API contracts, database tables, state machines, and data flow.
- [x] Implementation plan has step-by-step checkboxes and validation commands.

### Backend contracts

- [ ] Config supports `ZHUQUE_DETECT_TRANSPORT` and explicit fallback behavior.
- [ ] Database has persistent browser-agent pairing/agent/job records.
- [ ] Pairing APIs create, claim, heartbeat, status, and revoke agents.
- [ ] Job APIs let an authorized agent claim, update progress, complete, fail, and heartbeat a job.
- [ ] Browser-agent job claim uses row locking or equivalent to prevent double-claim.
- [ ] `AI检测 + 降重` in `browser_agent` mode creates a browser-agent job and waits for result.
- [ ] Missing/offline agent produces an actionable frontend/API error before spending Zhuque uses or LLM credits.
- [ ] `server_headless` is not used in VPS browser-agent mode unless explicitly configured.

### Chrome extension MVP

- [ ] Extension can store VPS URL and pair with a user through a short-lived code.
- [ ] Extension heartbeat makes the workspace show online.
- [ ] Extension can claim a text detection job.
- [ ] Extension opens/reuses a Zhuque tab in the user's local Chrome.
- [ ] Extension detects not-logged-in state and returns actionable status.
- [ ] Extension executes one Zhuque detection and returns normalized result JSON.
- [ ] Extension detects CAPTCHA/manual verification and reports `manual_required` while continuing to wait.

### Frontend

- [ ] Workspace shows browser-agent connection status in VPS mode.
- [ ] Workspace can generate a pairing code and show installation/connection guidance.
- [ ] Start flow blocks with clear copy when `browser_agent` is required but offline.
- [ ] Session detail/progress shows local-browser detection and manual verification prompts.
- [ ] Local deployments keep current local-browser flow without extension requirement.

### Validation

- [ ] Backend tests cover pairing, token auth, heartbeat online/offline, job claim/complete/fail, and transport selection.
- [ ] Existing Zhuque integration tests still pass.
- [ ] Frontend/static tests cover browser-agent UI states and local-vs-VPS copy.
- [ ] Manual VPS test proves the worker does not launch server headless Playwright for Zhuque detection in `browser_agent` mode.
- [ ] Manual browser-extension test proves detection runs in the user's local Chrome and returns results to VPS.

## Open Questions

- Extension distribution for MVP: use unpacked developer-mode extension first; production distribution can be decided later.
- The production GankAIGC domain must be added to extension `host_permissions` at build/package time.
