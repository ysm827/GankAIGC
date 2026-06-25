# Design: Real Session Monitor Metrics

## Architecture / Boundaries

Use existing backend contracts where possible:

- `GET /api/admin/statistics?range=<today|7d|30d>` provides range-level totals, previous-period comparisons, success rates, average processing time, and time-bucketed series.
- `GET /api/admin/sessions/active` provides current queued/processing rows.
- `GET /api/admin/sessions?limit=100` provides recent history rows.

No new backend endpoint is required for the MVP because the backend already returns enough real data to replace current placeholders. If future product requirements need true live RPM from HTTP request logs, that should be a separate telemetry task.

## Data Flow

`SessionMonitor` will own:

- `statistics` state loaded from `/api/admin/statistics`.
- `statsRange` state with `today`, `7d`, `30d`.
- `loadingStats` state.

Refresh behavior:

- On mount and whenever `statsRange` changes, call `fetchSessionStatistics`.
- Manual refresh calls both the current session list fetch and statistics fetch.
- Active auto refresh refreshes active sessions and statistics every 5s, keeping the existing realtime behavior but avoiding fake values.
- History view loads history rows and still refreshes statistics for selected range.

## UI Contracts

- KPI cards:
  - Online sessions: `activeSessions.length` in active mode, otherwise visible filtered rows count; trend from `statistics.sessions.trend_percent` only if available.
  - Range requests: `statistics.requests.in_range`.
  - Average response/processing time: `statistics.processing.avg_processing_time_in_range`.
  - Success rate: `statistics.sessions.success_rate`.
  - Active models: distinct processing modes from `sessionsToRender` plus fallback to mode rows with nonzero count from statistics.
- Queue:
  - Count = real `activeSessions.filter(status === 'queued').length`.
  - No fallback `6`.
- Throughput:
  - Series = `statistics.processing.series.sessions` for the selected range.
  - Chart scales dynamically to max value and labels show real bucket labels/value.
- Timeline:
  - Real `sessionsToRender.slice(0, 4)` rows.
  - Empty state if zero rows.
- Date range:
  - Replace static text with a real select, shared with statistics query.

## Compatibility / Migration

- Keep existing admin token auth header style.
- Keep existing CSS class names to avoid broad theme drift.
- Keep `aurora-admin-section-head` and current Aurora visual shell.
- Do not change backend response schema in this task.

## Rollback

Rollback is limited to `SessionMonitor.jsx`, any small CSS additions, tests, and synced static assets. Existing `/api/admin/statistics` remains untouched unless later evidence requires backend fixes.
