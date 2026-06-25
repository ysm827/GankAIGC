# Implementation Plan

1. Load frontend/backend specs relevant to admin dashboard and API contracts.
2. Update `SessionMonitor.jsx`:
   - Add statistics/range/loading state.
   - Add `fetchSessionStatistics` using `/api/admin/statistics`.
   - Replace static date label with functional range select.
   - Replace fake KPI/trend values with real values or neutral unavailable states.
   - Replace static throughput SVG with real series chart.
   - Remove fake queue fallback and add empty state.
   - Add empty timeline state.
   - Fix table footer copy.
3. Add/adjust focused static tests in `package/backend/tests/test_frontend_redeem_entry.py` to reject known fake strings and assert statistics API usage.
4. Run focused tests.
5. Build frontend with `npm run build`.
6. Sync `package/frontend/dist` to `package/static`.
7. Verify source/static bundles do not contain fake placeholders.

## Validation Commands

- `cd package/backend && package/venv/bin/python -m pytest tests/test_frontend_redeem_entry.py -q`
- `cd package/frontend && npm run build`
- `rg -n "较昨日|1.28|请求数 2,431|queuedCount \|\| 6|共 12 个模型|今日 00:00" package/frontend/src package/static || true`

## Risk / Rollback Points

- Auto refresh may increase `/statistics` calls; keep same 5s active cadence and only active mode auto-refreshes.
- Statistics range and active list are not identical concepts; labels must say selected range where relevant.
- If build changes many hashed static assets, stage/sync all generated changes together.
