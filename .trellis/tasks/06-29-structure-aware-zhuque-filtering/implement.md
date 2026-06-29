# Implementation Plan

## Phase 0: Baseline verification

- Run current Zhuque integration tests before implementation.
- Inspect parse-document API and session creation flow.
- Confirm exact segment splitting and MarkItDown conversion contracts.

## Phase 1: Semantic classifier foundation

- Create `package/backend/app/services/document_structure_service.py` or equivalent.
- Move/reuse current Zhuque text-rule classification into a reusable semantic classifier.
- Define semantic type/source constants.
- Add unit tests for text-rule classification:
  - headings h1-h4
  - abstract/keywords
  - TOC heading/items
  - acknowledgement heading/body
  - references
  - mixed heading+body treated as body
  - short text skip

## Phase 2: Persistence and API contract

- Add Alembic migration for segment/session semantic fields if accepted.
- Update models and schemas as needed.
- Update parse-document response to include segment structure summary.
- Preserve backward compatibility for clients that only send `original_text`.

## Phase 3: DOCX style parser

- Use `python-docx` to classify paragraph styles.
- Implement style mapping for Title, Heading 1-4, TOC 1-4, headers/footers if feasible.
- Fallback/enrich with text rules for Normal/custom styles.
- Add tests with generated DOCX fixtures.

## Phase 4: PDF Docling parser with MarkItDown fallback

- Add optional Docling dependency/config plan.
- Implement lazy import.
- Add timeout wrapper.
- Convert Docling output into parsed segments with semantic metadata.
- Fallback to MarkItDown on import failure, timeout, exception, or empty text.
- Add tests by monkeypatching fake Docling success/failure paths; avoid requiring heavy real Docling in core CI unless dependency is installed.

## Phase 5: Zhuque selection integration

- Update `_select_zhuque_reduce_segments()` to use semantic decisions after Zhuque label/position mapping.
- Preserve current non-fallback-all safety behavior.
- Add `segment_filter_audit` trace event.
- Ensure trace remains compact and text-free.

## Phase 6: Validation

Run at minimum:

```bash
package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q
package/venv/bin/python -m pytest package/backend/tests/test_optimization_billing.py -q
```

If frontend schema changes:

```bash
cd package/frontend && npm run build
```

## Risk files / rollback points

- `package/backend/app/routes/optimization.py`
- `package/backend/app/services/optimization_service.py`
- `package/backend/app/services/document_structure_service.py` (new)
- `package/backend/app/models/models.py`
- `package/backend/app/schemas.py`
- Alembic migration files
- `package/backend/requirements.txt` / packaging scripts if Docling is added

## Decisions

- First implementation includes the real Docling dependency and defaults PDF parsing to Docling.
- Tests should still cover fallback behavior by monkeypatching import/parse failure or timeout.

## Completion Status

- [x] Baseline/source inspection completed.
- [x] Semantic classifier foundation implemented in `document_structure_service.py`.
- [x] Session/segment metadata migration and schemas added.
- [x] DOCX `python-docx` style parser implemented.
- [x] PDF Docling default parser implemented with MarkItDown fallback.
- [x] Zhuque `segment_labels` selection now gates through semantic metadata.
- [x] Trace audit includes compact parser/filter metadata.
- [x] Frontend upload/start flow carries `document_parse`; manual edits clear stale parse metadata.
- [x] Real Docling dependency installed in local venv with CPU-only PyTorch pins.
- [x] Backend focused tests passed: `126 passed` for billing, Zhuque integration, Alembic migration, and harness smoke suites.
- [x] Frontend production build passed and `package/static` was synced from `package/frontend/dist`.
- [x] Final `git diff --check` after spec/requirements edits.
- [ ] Final commit / archive flow.
