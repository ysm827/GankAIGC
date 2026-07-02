# PRD: 接入 MinerU PDF 高精度解析

## Goal

Use MinerU precise parsing API as the default PDF structure parser so uploaded PDFs produce paragraph-level, structure-aware segments from `*_content_list.json`, while retaining MarkItDown as an explicit fallback. This improves Zhuque AI reduce selection by protecting headings, references, tables, formulas, and other non-body content before LLM rewriting.

## User Value

- Avoid Docling local runtime cost and previous timeout/hang failures.
- Improve PDF segment structure beyond MarkItDown-only text extraction.
- Keep Zhuque full-text detection rate semantics unchanged.
- Reduce only Zhuque-hit body segments, not titles, TOC, references, acknowledgements, tables, formulas, or short metadata fragments.
- Make fallback visible so users know structure quality is lower.

## Confirmed Facts

- Current PDF parser after Docling removal is MarkItDown only in `package/backend/app/services/document_structure_service.py`.
- Existing parser contract returns `ParsedDocument` / `ParsedSegment` with `parse_engine`, `parse_fallback_used`, `parse_trace`, `semantic_type`, `reduce_allowed`, `page_number`, and `bbox_json`.
- Existing Zhuque pipeline already gates rewrite by Zhuque labels plus local `reduce_allowed` metadata.
- API parse response serializes `parse_trace` as JSON string.
- MinerU official precise API v4 flow is: request upload URL -> PUT file -> poll extract results -> download `full_zip_url` -> read `*_content_list.json`.
- MinerU `content_list.json` has reading-order items with fields such as `type`, `text`, `text_level`, `page_idx`, and `bbox`.
- Real MinerU v4 `content_list.json` can emit references as top-level `{"type": "ref_text", "text": ...}` items, while the downloaded `full.md` contains the same reference section.

## Requirements

1. PDF upload parsing must default to MinerU when configured.
2. MinerU service must use official v4 endpoints and authorization token from backend config only.
3. MinerU success must map `content_list.json` into existing `ParsedDocument` / `ParsedSegment` contract.
4. MinerU headings must be protected using `text_level > 0`, but text-rule classifier must still override generic headings into more specific protected types like abstract, references, TOC, acknowledgements, formulas, captions, and mixed heading/body.
5. MinerU tables, formulas/equations, images/figures/charts/captions must become protected segment types where meaningful text exists.
6. `page_idx` must map to `page_number = page_idx + 1`; `bbox` and MinerU metadata must be stored compactly in `bbox_json`.
7. MinerU failure, timeout, missing token, missing zip URL, invalid zip, missing content_list, or empty extracted text must fall back to MarkItDown with `parse_fallback_used=true` and warning text mentioning MinerU.
8. Frontend upload UI must visibly show MinerU success and fallback states.
9. Manual textarea edits must continue to clear stale `documentParse`.
10. Tests must mock MinerU network calls; real token-based validation is optional/manual after implementation.

## Acceptance Criteria

- PDF parse success via mocked MinerU returns:
  - `parser="mineru"`
  - `parse_engine="mineru"`
  - `parse_fallback_used=false`
  - `parse_trace` includes engine/api/batch/item count metadata
  - heading/table/formula/reference items are protected
  - normal body text is rewrite-eligible when long enough
- MinerU failure via mocked service returns:
  - `parser="markitdown"`
  - `parse_engine="markitdown"`
  - `parse_fallback_used=true`
  - warning contains `MinerU`
  - `parse_trace` includes fallback reason/message
- Zhuque regression tests still pass: selected reduce segments are only body/mixed body and no full-document fallback rewrite is introduced.
- Frontend build succeeds and UI contains explicit MinerU success/fallback copy.
- No Docling/Torch dependency is reintroduced.

## Out of Scope

- Async background parse job UI/progress bar for MinerU polling.
- DOCX parsing through MinerU; DOCX remains python-docx first.
- Real MinerU token provisioning or billing management UI.
- Using experimental `content_list_v2.json`.
- Reintroducing local Docling/Torch parser chain.

## Open Questions

None blocking first implementation. If real MinerU responses differ from the official documented sample shape, update the parser based on captured real response evidence rather than speculative multi-field fallback.
