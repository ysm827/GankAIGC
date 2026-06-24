# PRD: Sync Zhuque Detected Anonymous Quota FP

## Goal

After a Zhuque anonymous/free detection consumes a use and returns a new `remaining_uses`, the workspace free-quota refresh must report the same identity and count instead of falling back to a legacy browser fp with stale/higher count.

## Problem

The previous fix made page probes prefer token-free legacy `zhuque_pkg/browser_state.json` so free quota could be read. However, real detections may run with the per-user `session_status.json` anonymous fp while refresh probes read the legacy fp. This creates inconsistent UI: session detail shows `朱雀剩余 3 次`, but workspace refresh still says `4 次`.

## Requirements

1. When `ZhuqueService.detect()` completes successfully, persist the exact fp used by the API and the returned `remaining_uses` to the current user's logged-out `session_status.json` when the detection used anonymous fp (no access token).
2. Page probe identity priority must prefer current user state over legacy state after a successful detection:
   - current user's token-free sibling `browser_state.json` if present;
   - current user's `session_status.json.anonymous_fp` / logged-out creds;
   - token-free legacy `zhuque_pkg/browser_state.json` only as fallback when the current user has no anonymous fp.
3. Never persist access tokens/cookies in logged-out quota status.
4. Preserve current ability to use legacy token-free browser state for first-time local anonymous quota discovery.
5. Add regression tests for successful anonymous detection updating quota status and for page-probe source priority.

## Acceptance Criteria

- Zhuque integration tests pass.
- Backend tests pass.
- After anonymous detection returns `remaining_uses=3`, `session_status.json` stores that count and fp.
- Subsequent free-quota refresh uses the current user's anonymous fp before legacy browser state, so it cannot bounce back to the old `4 次` identity.

## Out of Scope

- Changing logged-in token handling.
- Changing frontend layout.
- Forcing Zhuque to merge counts across different anonymous fps.
