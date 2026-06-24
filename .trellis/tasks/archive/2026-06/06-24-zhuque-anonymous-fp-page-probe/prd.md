# PRD: Fix Zhuque Anonymous FP Page Probe

## Goal

Make Zhuque free-quota refresh reuse the persisted anonymous `fp` when opening the headless page probe, so the page initializes under the same anonymous identity that users see in a normal browser and can expose the free-use count when Tencent provides it.

## Confirmed Facts

- `session_status.json` can persist `anonymous_fp` while logged out.
- Current `_peek_quota_status_with_page()` loads `browser_state.json` when present, but if that file is absent it opens a fresh browser context.
- A fresh context gets a new `localStorage.fp`, which may return `aiGenTxtRemainingCount=-1` and only show `Detect now`.
- Manual browser visits can show the free-use count without login, so the backend should reuse the existing anonymous identity instead of always generating a new one.

## Requirements

1. Before navigating to Zhuque in `_peek_quota_status_with_page()`, seed Playwright storage with persisted anonymous `fp` when no compatible `browser_state.json` is available.
2. The fp source order must be non-secret and logged-out safe:
   - sibling `browser_state.json` with matrix.tencent.com localStorage remains preferred;
   - otherwise token-free legacy repo-level `zhuque_pkg/browser_state.json` may be used as a local-compatibility anonymous source;
   - otherwise `session_status.json.anonymous_fp` / `fp` when `has_token=false`;
   - otherwise anonymous credentials loaded from existing logged-out `creds_latest.json`.
3. Seeded storage must not include login tokens or cookies.
4. Preserve current fallback behavior when no persisted fp exists.
5. Add regression tests proving page probe context receives the persisted anonymous fp without requiring a numeric quota.

## Acceptance Criteria

- Unit tests pass for Zhuque integration.
- Backend tests pass.
- `refresh_free_quota()` still returns ready when `remaining_uses=-1 && button_enabled=true`.
- A headless page probe can initialize localStorage with a sibling or token-free legacy anonymous fp instead of minting a new identity.

## Out of Scope

- Changing Zhuque detection submission flow.
- Forcing Tencent to reveal a numeric quota when it returns `-1` for an identity.
- UI redesign beyond whatever is required by backend contract.
