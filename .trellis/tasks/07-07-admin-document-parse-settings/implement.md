# Implementation Plan: 后台文档解析设置与 TXT 上传支持

## Checklist

- [x] Backend config API
  - [x] Add document_parse block to `GET /api/admin/config`.
  - [x] Treat empty `MINERU_API_TOKEN` as no-op on save.
  - [x] Validate `PDF_STRUCTURE_ENGINE` values.
- [x] Document parser
  - [x] Add `.txt` to allowed extensions and MIME list.
  - [x] Add explicit `.doc` rejection hint.
  - [x] Add TXT decode/local parse branch.
- [x] Frontend admin
  - [x] Extend `ConfigManager.jsx` form state/fetch/save for document_parse fields.
  - [x] Add “文档解析设置” card with MinerU token masked status and explanatory copy.
- [x] Frontend workspace
  - [x] Update upload accept/help copy for PDF/DOCX/MD/TXT.
- [x] Tests/build
  - [x] Backend parse tests for TXT and `.doc` hint.
  - [x] Backend/admin tests or static frontend assertions for document_parse config.
  - [x] `npm run build`, sync `package/static`.
  - [x] Targeted pytest.

## Validation Commands

```bash
package/venv/bin/python -m pytest package/backend/tests/test_optimization_billing.py -q -k 'txt or doc_document or parse_pdf or parse_docx or mineru'
package/venv/bin/python -m pytest package/backend/tests/test_frontend_redeem_entry.py -q
cd package/frontend && npm run build
```

## Risk Points

- Do not leak `MINERU_API_TOKEN` to frontend; return only set/last4.
- Do not clear existing MinerU token when the admin saves other settings.
- Keep PDF parse fallback behavior unchanged.
- Sync hashed static assets after frontend build.
