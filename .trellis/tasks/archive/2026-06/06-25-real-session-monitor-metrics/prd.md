# Make session monitor metrics real

## Goal

Replace placeholder/fabricated values in the admin Session Monitor page with real values derived from backend APIs and loaded session data, so admins no longer see misleading fake KPI, queue, throughput, timeline, or date-range information.

## Confirmed Facts

- The affected UI is `package/frontend/src/components/SessionMonitor.jsx`.
- Existing fake/placeholder values include hard-coded trend labels, fixed average response time, synthetic requests-per-minute, default queue/model counts, static date-range text, static throughput SVG/value, and non-functional pagination copy.
- The backend already exposes `GET /api/admin/statistics?range=today|7d|30d` with real `sessions`, `requests`, and `processing.series` data.
- Existing session endpoints return real active/history/user session lists:
  - `GET /api/admin/sessions/active`
  - `GET /api/admin/sessions?limit=100&status=...`
  - `GET /api/admin/users/{user_id}/sessions`
- The admin dashboard source and static bundle were already modified in this working tree to remove inert `i` info icons; this task must preserve those changes.

## Requirements

- Session Monitor must not display fabricated metrics, trends, charts, or counts.
- KPI cards must show real values from `/api/admin/statistics` and loaded session data.
- The date range control must be functional and drive statistics loading; it must not be a static label.
- Mode and status filters may remain client-side filters over loaded rows, but their labels/counts must not imply backend filtering when they do not.
- The activity queue count must use real queued sessions only and show an empty state when no queued sessions exist.
- The throughput chart must be rendered from real series data. If no data exists, show an empty state or zero baseline rather than a fake spike.
- The recent task timeline must show real recent sessions and a clear empty state when none exist.
- Table footer must describe actual loaded/displayed rows, not fake pagination.
- Existing working features must continue to function: realtime/history toggle, manual refresh, active auto refresh, filters, search, stop session, and user-session drawer.
- Production frontend build must be synced from `package/frontend/dist` to `package/static`.

## Acceptance Criteria

- [ ] `SessionMonitor.jsx` contains no hard-coded fake metric strings such as `较昨日 +18%`, `1.28`, `* 37`, `queuedCount || 6`, `|| 6`, `共 12 个模型`, `请求数 2,431`, or static `今日 00:00 ~ 23:59`.
- [ ] The Session Monitor calls `/api/admin/statistics` with the selected range.
- [ ] Date range selection offers today / 7d / 30d and updates statistics/chart labels.
- [ ] KPI values and trends are computed from real `statistics` fields or current loaded sessions.
- [ ] Throughput chart uses real `statistics.processing.series.sessions` data.
- [ ] Queue and timeline sections show real rows or empty states, with no fabricated fallback rows/counts.
- [ ] `npm run build` passes and `package/static` is synchronized.
- [ ] Relevant backend/frontend tests or static checks pass where feasible.

## Out of Scope

- Adding a new realtime QPS/RPM backend collector beyond existing session/statistics data.
- Adding server-side pagination to admin session history.
- Redesigning the whole admin page beyond replacing fake data.
