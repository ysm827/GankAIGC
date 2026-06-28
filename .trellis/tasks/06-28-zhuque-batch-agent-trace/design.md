# Design: 朱雀降AI批量优化与Agent可视化日志

## Architecture Overview

This task keeps the existing Zhuque reduce architecture intact:

```
full-text detect -> select segments -> reduce round(s) -> full-text recheck -> rollback/strategy reflection
```

P0 changes only two execution surfaces:

1. fallback segment selection when Zhuque has no usable `segment_labels`.
2. per-stage reduce execution from per-segment calls to small batch calls, guarded by validation and old-path fallback.

Observability is extended through the existing `zhuque_agent_trace` and SSE `zhuque_agent_event` channel.

## Backend Boundaries

Primary file:

- `package/backend/app/services/optimization_service.py`

Supporting files:

- `package/backend/app/config.py` for new settings.
- `package/backend/app/schemas.py` only if the frontend needs typed fields already absent from `SessionResponse`; current `zhuque_agent_trace` exists.
- `package/backend/tests/test_zhuque_integration.py` or a focused new test module for classifiers/batch parsing.

## Frontend Boundaries

Primary file:

- `package/frontend/src/pages/SessionDetailPage.jsx`

Supporting file:

- `package/frontend/src/index.css` if new styles are needed.
- `package/static` must be regenerated after frontend build.

## Data Flow

### Current Trace Flow

```
OptimizationService._emit_zhuque_trace_event(event)
  -> _append_zhuque_trace_event(event)
  -> optimization_sessions.zhuque_agent_trace JSON
  -> stream_manager.broadcast(type='zhuque_agent_event')
  -> SessionDetailPage zhuqueLiveEvents
  -> Agent 决策轨迹 UI
```

### New Trace Event Types

Add compact event types:

- `segment_classification`
  - round, label_source, selected_count, skipped_count, type_counts, selected_segment_indices, skipped_summary.
- `batch_plan`
  - round, stage, batch_count, selected_segment_count, estimated_old_calls, estimated_new_calls.
- `batch_stage`
  - round, stage, batch_id, segment_indices, input_lengths, output_lengths, duration_ms, status, fallback_count.
- `batch_fallback`
  - round, stage, batch_id, segment_indices, reason, fallback_segment_indices.
- `batch_validation`
  - round, stage, batch_id, status, missing_ids, duplicate_ids, empty_ids, unknown_ids.

All events must avoid full text.

## Segment Classification Contract

Classifier input:

- ordered `OptimizationSegment[]`
- current original/reduced text preference
- optional context state (`current_section`, `reference_zone`)

Classifier output per segment:

```json
{
  "segment_index": 7,
  "type_code": "BODY",
  "section": "BODY",
  "action": "reduce",
  "confidence": 0.82,
  "reason": "body_length_and_sentence_shape",
  "length": 96
}
```

Type codes:

- `TITLE`
- `SECTION_HEADING`
- `ABSTRACT_HEADING`
- `KEYWORDS_HEADING`
- `ACK_HEADING`
- `REFERENCE_HEADING`
- `ABSTRACT_BODY`
- `ACK_BODY`
- `BODY`
- `KEYWORDS`
- `CAPTION`
- `FORMULA`
- `REFERENCE_ITEM`
- `META`
- `SHORT_TEXT`
- `UNKNOWN`

Actions:

- `reduce`
- `skip`
- `candidate_low_priority`

Rules:

- Heading rows are skipped; section bodies remain reducible.
- `REFERENCE_HEADING` starts `reference_zone`; reference items are skipped.
- `UNKNOWN` remains reducible to avoid false negatives.
- Heuristics are only used when Zhuque labels are unavailable/unusable.

## Batch Reduce Contract

### Batch Build

Inputs:

- selected segments for this round
- stage: `polish` or `enhance`
- per-stage prompt already produced by `_with_zhuque_strategy(...)`

Constraints:

- max segments per batch: `ZHUQUE_REDUCE_BATCH_SIZE` default 3.
- max aggregate length: `ZHUQUE_REDUCE_BATCH_MAX_CHARS` default 2500.
- single segment threshold: `ZHUQUE_REDUCE_BATCH_SINGLE_SEGMENT_CHARS` default 1500.

### Prompt Contract

Batch prompt wraps the existing stage prompt and appends a JSON-only contract:

- input is JSON array of `{id, text}`.
- output must be JSON array of same ids and count.
- each `text` is independently rewritten.
- preserve facts, numbers, citations, terminology, research object, conclusions.
- no markdown, no explanation.

### Parse / Validate Contract

Validation levels:

1. Structure-level failure:
   - not JSON array
   - no usable objects
   - no valid ids
   -> batch falls back to old single-segment path.

2. Segment-level failure:
   - missing id
   - duplicate id
   - unknown id
   - empty text
   - obvious numeric/citation loss if implemented safely
   -> failed segments fall back to old single-segment path; successful segments are kept.

3. Length violation:
   - output outside ±10%
   -> keep candidate and route through existing `_repair_zhuque_length_if_needed`; do not fail whole batch.

## Credit and Transaction Design

P0 should preserve current user-visible charge rule:

- each reduced segment costs 10 beers per reduce operation.

Implementation must avoid double-charging fallback:

- maintain an in-round charged set keyed by `segment.id` or `segment.segment_index`.
- batch path charges selected segments once before or at successful processing, following the smallest safe change from current code.
- fallback old single path must accept a `charged_segment_ids` set and skip hold when already charged.

Do not introduce a new refund model in P0.

## Frontend Visualization Design

Use existing Agent panel in `SessionDetailPage.jsx` and add display support for new event types:

- `segment_classification`: show selected count, skipped count, type breakdown, reason summary.
- `batch_plan`: show planned batch count and estimated call savings.
- `batch_stage`: show stage, batch id, segment indices, duration, status.
- `batch_fallback`: show fallback reason and affected segment ids.
- `batch_validation`: show JSON/ID validation failures compactly.

UI principles:

- show compact timeline by default.
- details expandable.
- do not render raw manuscript text from trace.
- preserve existing reflection / prompt evolution drawer behavior.

## Logging Design

Use Python logger, not print, for new structured logs.

Example fields:

```json
{
  "session_id": "...",
  "round": 1,
  "stage": "polish",
  "batch_id": "r1-polish-b2",
  "segment_indices": [2, 5, 7],
  "duration_ms": 18432,
  "status": "success"
}
```

Existing print logs may remain, but new functionality should prefer `logger.info/warning`.

## Compatibility and Rollback

- `ZHUQUE_REDUCE_BATCH_ENABLED=false` restores old per-segment two-stage path.
- If batch parsing fails, fallback old path handles the same segments.
- Existing full-text recheck, rollback snapshots, plateau recovery, prompt evolution, and final export remain unchanged.
- Existing `zhuque_agent_trace` consumers tolerate unknown event fields; frontend should ignore unsupported fields gracefully.

## Risks

- LLM may not return strict JSON. Mitigation: robust extraction + old-path fallback.
- Batch prompt may alter style consistency. Mitigation: small batch size, existing stage prompts, independent segment contract.
- Segment classifier can misclassify正文 as skip. Mitigation: conservative rules, `UNKNOWN` reduces, only fallback mode.
- Credit double-charge in fallback. Mitigation: charged set and focused tests.
- Trace growth. Mitigation: compact metadata, no full text.
