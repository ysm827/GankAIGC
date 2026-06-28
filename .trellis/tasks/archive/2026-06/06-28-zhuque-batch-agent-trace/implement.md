# Implementation Plan: 朱雀降AI批量优化与Agent可视化日志

## Phase 0: Pre-dev context

- [x] Read `trellis-before-dev` before editing.
- [x] Read relevant specs:
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/frontend/component-guidelines.md`
  - `.trellis/spec/guides/cross-layer-thinking-guide.md`
  - `.trellis/spec/guides/code-reuse-thinking-guide.md`

## Phase 1: Backend configuration and classifier

- [x] Add config fields in `package/backend/app/config.py`:
  - `ZHUQUE_REDUCE_BATCH_ENABLED: bool = True`
  - `ZHUQUE_REDUCE_BATCH_SIZE: int = 3`
  - `ZHUQUE_REDUCE_BATCH_MAX_CHARS: int = 2500`
  - `ZHUQUE_REDUCE_BATCH_SINGLE_SEGMENT_CHARS: int = 1500`
  - `ZHUQUE_REDUCE_FALLBACK_TOP_N: int = 20`
  - `ZHUQUE_REDUCE_SKIP_SHORT_CHARS: int = 80`
- [x] Add segment classifier helpers in `optimization_service.py`:
  - type-code constants
  - `_classify_zhuque_fallback_segments(...)`
  - `_is_zhuque_section_heading(...)` / `_is_zhuque_abstract_heading(...)` / `_is_zhuque_ack_heading(...)`
  - `_is_zhuque_reference_item(...)`
  - `_is_zhuque_caption(...)`
  - `_is_zhuque_formula_or_metric(...)`
- [x] Update `_select_zhuque_reduce_segments(...)`:
  - keep current span mapping when labels exist.
  - on no usable spans, use classifier + top-N fallback.
  - emit `segment_classification` event.

## Phase 2: Batch reduce backend

- [x] Extract old per-stage single-segment logic into reusable helpers:
  - `_process_zhuque_single_stage_segment(...)`
  - keep old retry, credit, status, `_record_change` behavior.
- [x] Add batch planning helper:
  - `_build_zhuque_reduce_batches(segments)`.
- [x] Add prompt builder:
  - `_build_zhuque_batch_stage_prompt(stage_prompt, stage)`.
- [x] Add parser/validator:
  - `_extract_zhuque_batch_json_array(raw)`.
  - `_validate_zhuque_batch_response(raw, expected_segments)`.
  - optional safe numeric/citation sanity check only if deterministic enough.
- [x] Add stage runner:
  - `_process_zhuque_batch_stage(...)` for `polish` and `enhance`.
  - emit `batch_plan`, `batch_stage`, `batch_validation`, `batch_fallback` events.
  - fallback failed segments to single helper.
- [x] Update `_process_zhuque_reduce_round(...)`:
  - if batch disabled, old path.
  - if batch enabled, run batch polish then batch enhance.
  - keep `_repair_zhuque_length_if_needed` after enhance.
  - preserve paper reconstruction metadata behavior; if too risky, batch can auto-disable for `paper_reconstruction` mode and emit trace explaining fallback.

## Phase 3: Trace and frontend visualization

- [x] Extend `_infer_zhuque_event_phase`, `_build_zhuque_event_title`, `_build_zhuque_event_summary` for new event types.
- [x] Ensure trace events contain no full text.
- [x] Update `SessionDetailPage.jsx`:
  - title/status labels for new event types.
  - chips/details for selected counts, skipped counts, batch ids, duration, saved calls, fallback reasons.
  - keep existing live event merge stable.
- [x] Add/adjust CSS in `index.css` only if existing styles are insufficient. (not needed; reused existing styles)

## Phase 4: Tests and validation

- [x] Backend focused tests:
  - classifier skips heading line but reduces abstract/ack body.
  - reference heading starts reference zone and reference items skip.
  - no labels fallback selects body top-N, not all segments.
  - batch parser accepts valid JSON array.
  - batch parser/validator rejects bad ID/empty text and identifies fallback segments.
  - batch fallback does not double-charge segment ids where feasible with current service tests.
  - trace events are compact and do not include full segment text.
- [x] Run focused pytest:
  - `package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q -k "zhuque"` or new focused test file.
- [x] Frontend build:
  - `cd package/frontend && npm run build`.
- [x] Sync static bundle:
  - `rm -rf ../static && cp -R dist ../static` from `package/frontend` or equivalent.
- [x] `git diff --check` before commit.

## Phase 5: Commit

- [ ] `git status --short` review.
- [ ] `git add` backend/frontend/static/task files.
- [ ] commit message suggestion:
  - `feat: batch zhuque reduce with agent trace`

## Rollback Points

- Config rollback: set `ZHUQUE_REDUCE_BATCH_ENABLED=false`.
- Code rollback: old per-segment path remains available.
- UI rollback: new trace event UI can be hidden without affecting backend processing.
