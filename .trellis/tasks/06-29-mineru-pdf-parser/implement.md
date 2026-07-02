# Implementation Plan: MinerU PDF Parser Integration

## Ordered Checklist

1. Read relevant backend/frontend specs and current parser/frontend code.
2. Add MinerU config keys to `package/backend/app/config.py`.
3. Add `package/backend/app/services/mineru_service.py`:
   - request upload URLs
   - upload bytes
   - poll result
   - download zip
   - extract `*_content_list.json`
   - return typed result metadata
4. Extend `document_structure_service.py`:
   - `SEMANTIC_SOURCE_MINERU`
   - PDF parser accepts filename
   - MinerU success -> `ParsedDocument`
   - MinerU failure -> MarkItDown fallback with trace/warning
   - content-list item mapping helpers
5. Update parse route to pass filename into parser.
6. Add/adjust tests:
   - MinerU success mapping
   - MinerU fallback
   - no Docling dependency regression if cheap
   - existing Zhuque integration unchanged
7. Update frontend upload notice in `WorkspacePage.jsx`.
8. Build frontend and sync static bundle if build succeeds.
9. Run validation commands.
10. Final scan for `docling`, `torch==`, and stale parser config names.

## Validation Commands

```bash
python3 -m py_compile \
  package/backend/app/services/mineru_service.py \
  package/backend/app/services/document_structure_service.py \
  package/backend/app/routes/optimization.py \
  package/backend/tests/test_optimization_billing.py

package/venv/bin/python -m pytest -q \
  package/backend/tests/test_optimization_billing.py \
  package/backend/tests/test_zhuque_integration.py

cd package/frontend && npm run build
rm -rf package/static && cp -r package/frontend/dist package/static
rg -n "docling|Docling|torch==|torchvision==|PDF_STRUCTURE_ENGINE=docling" -g '!package/venv' -g '!package/frontend/node_modules' .
```

## Risky Files / Rollback Points

- `package/backend/app/services/document_structure_service.py`: parser contract and semantic mapping. Rollback by setting `PDF_STRUCTURE_ENGINE=markitdown` or reverting MinerU branch.
- `package/backend/app/services/mineru_service.py`: external API protocol. Keep tests mocked.
- `package/frontend/src/pages/WorkspacePage.jsx`: UI state only; avoid changing start payload semantics.
- `package/static`: generated bundle may need forced git add.

## Review Gates

- No token or uploaded text content in trace/logs.
- `parse_trace` remains compact JSON string at API boundary.
- No speculative multi-field fallbacks beyond documented MinerU content item fields.
- No Docling/Torch dependency reintroduced.
