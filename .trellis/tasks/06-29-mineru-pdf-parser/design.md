# Design: MinerU PDF Parser Integration

## Architecture

```
POST /api/optimization/documents/parse
  -> DocumentStructureService._parse_pdf(content, filename)
     -> MinerUService.parse_pdf(filename, content)
        -> POST /api/v4/file-urls/batch
        -> PUT upload URL
        -> GET /api/v4/extract-results/batch/{batch_id} until done/failed/timeout
        -> GET full_zip_url
        -> read *_content_list.json
        -> map content items to raw segments
     -> build_parsed_document_from_raw_segments(...)
  -> fallback parse_document_with_markitdown on MinerU failure
```

## Boundaries

- `mineru_service.py` owns HTTP protocol, polling, zip download, and content-list extraction.
- `document_structure_service.py` owns mapping MinerU content items into project semantic segment decisions and fallback behavior.
- `optimization.py` owns request file validation and response serialization.
- Frontend owns display of parser/fallback status only; it does not parse MinerU trace.

## Config Contract

Add settings:

- `PDF_STRUCTURE_ENGINE: str = "mineru"`
- `PDF_STRUCTURE_FALLBACK_ENGINE: str = "markitdown"`
- `MINERU_BASE_URL: str = "https://mineru.net"`
- `MINERU_API_TOKEN: Optional[str] = None`
- `MINERU_MODEL_VERSION: str = "vlm"`
- `MINERU_ENABLE_FORMULA: bool = True`
- `MINERU_ENABLE_TABLE: bool = True`
- `MINERU_IS_OCR: bool = False`
- `MINERU_LANGUAGE: str = "ch"`
- `MINERU_TIMEOUT_SECONDS: int = 300`
- `MINERU_POLL_INTERVAL_SECONDS: float = 2.0`
- `MINERU_NO_CACHE: bool = False`
- `MINERU_CACHE_TOLERANCE: int = 900`

`extra="ignore"` already means old env values will not break startup.

## MinerU API Contract

Official v4 local upload precise parse:

1. `POST {base}/api/v4/file-urls/batch`
   - headers: `Content-Type: application/json`, `Authorization: Bearer <token>`
   - request includes file names and parse options.
2. Response must contain `code=0`, `data.batch_id`, `data.file_urls`.
3. `PUT <file_url>` uploads raw bytes.
4. `GET {base}/api/v4/extract-results/batch/{batch_id}` polls.
5. Successful file result must expose `full_zip_url`.
6. Zip must contain one stable `*_content_list.json`; do not use experimental v2 first.

If official result shape differs in real tests, implementation must be adjusted from captured response, not guessed.

## Segment Mapping

Raw segment tuple shape remains:

```python
(text, explicit_decision, page_number, bbox_json)
```

Mapping:

- `type == "text"` and `text_level > 0` -> `SECTION_HEADING`, source `mineru`, protected.
- `type == "text"` and no heading level -> no explicit decision; text rule decides body/protected semantics.
- `type == "table"` -> `TABLE`, protected.
- `type in {"equation", "formula"}` -> `FORMULA`, protected.
- `type in {"image", "figure", "chart", "caption"}` -> `CAPTION`, protected when caption/text exists.
- `type == "list"` with `sub_type == "ref_text"` -> `REFERENCE_ITEM`, protected.
- Real API evidence from `IJOSSER-7-9-28-33.pdf` also shows top-level `type == "ref_text"` with `text` -> `REFERENCE_ITEM`, protected.
- Other list items -> convert item text into raw text segments and let text rules classify.
- Unknown meaningful text -> no explicit decision; text rules classify.

Text extraction must use only documented/observed fields. Avoid speculative `a or b or c` chains for unknown contracts. Multi-field extraction is allowed only for fields documented in MinerU output examples such as `text`, `table_body`, `table_caption`, `table_footnote`, `img_caption`, `img_footnote`, `latex`, and `list_items` when handled explicitly by type.

## Fallback Semantics

MinerU exceptions are caught only at the PDF parser boundary. Fallback returns MarkItDown parsed document with:

- `parse_fallback_used=true`
- `warnings += ["MinerU 解析失败，已回退 MarkItDown：..."]`
- `parse_trace` compactly records `fallback_from`, `fallback_reason`, `fallback_message`, and `batch_id` if available.

No fallback may hide errors in trace; no full-document rewrite fallback is introduced.

## Frontend UX

After upload parse:

- `parse_engine === "mineru" && !parse_fallback_used` -> success notice.
- `parse_fallback_used === true` -> warning notice.
- fallback copy must explicitly say MarkItDown structure precision is lower.

## Compatibility

- Existing MarkItDown-only mode remains available with `PDF_STRUCTURE_ENGINE=markitdown`.
- Missing MinerU token triggers fallback, not request failure, for first product rollout.
- Existing DOCX/Markdown/manual text flows unchanged.
- Existing Zhuque semantic gate contract unchanged.

## Rollback

Set `PDF_STRUCTURE_ENGINE=markitdown` to bypass MinerU without code rollback.
