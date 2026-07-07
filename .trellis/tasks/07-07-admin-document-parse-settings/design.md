# Design: 后台文档解析设置与 TXT 上传支持

## Boundaries

- Backend config API owns persistence and runtime reload of document-parse settings.
- Document parser service owns format routing and TXT decoding.
- Workspace frontend owns upload accept/help copy.
- Admin ConfigManager owns document-parse settings UI.

## Data Flow

```text
Admin ConfigManager form
  -> POST /api/admin/config {PDF_STRUCTURE_ENGINE, MINERU_*}
  -> _persist_runtime_env_updates writes active env file
  -> reload_settings hot-updates settings
  -> document_structure_service reads settings on next parse
```

```text
Workspace upload .txt
  -> POST /api/optimization/documents/parse
  -> allowed extension/MIME validation
  -> DocumentStructureService.parse_uploaded_document(..., extension='.txt')
  -> decode bytes as utf-8-sig / utf-8 / gb18030
  -> build_parsed_document_from_text(parser='plain_text', document_format='txt', parse_engine='plain_text')
  -> frontend stores documentParse and sends it to optimization start
```

## API Contract

`GET /api/admin/config` adds:

```json
"document_parse": {
  "pdf_structure_engine": "mineru",
  "mineru_base_url": "https://mineru.net",
  "mineru_api_token_set": true,
  "mineru_api_token_last4": "abcd",
  "mineru_model_version": "vlm",
  "mineru_enable_formula": true,
  "mineru_enable_table": true,
  "mineru_is_ocr": false,
  "mineru_language": "ch",
  "mineru_timeout_seconds": 300,
  "mineru_poll_interval_seconds": 2.0
}
```

`POST /api/admin/config` accepts Settings field names. `MINERU_API_TOKEN` follows model API key behavior: empty string is ignored and does not clear stored token.

## Validation Rules

- `PDF_STRUCTURE_ENGINE` must be `mineru` or `markitdown`.
- Numeric fields must be sane positive values through existing Pydantic settings reload; invalid values return a 400 and rollback env writes.
- No newline in values, enforced by existing `_persist_runtime_env_updates`.
- `.doc` upload remains rejected with a specific conversion hint.

## Compatibility

- Existing `.env.docker` keys stay the source of truth in Docker deployments.
- Runtime update appends missing keys to the active env file just like existing model config fields.
- No DB migration required.
- Existing PDF/DOCX/Markdown parser response contract is unchanged.

## Rollback

- Set `PDF_STRUCTURE_ENGINE=markitdown` to bypass MinerU without code rollback.
- Revert frontend/static bundle if admin UI causes visual issues.
- TXT upload support is isolated to extension whitelist and service branch.
