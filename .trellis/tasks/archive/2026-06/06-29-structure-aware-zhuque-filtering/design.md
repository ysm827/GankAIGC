# Design: Structure-aware Zhuque filtering

## Architecture

Add a document structure layer between upload parsing and session/segment creation.

```text
Frontend upload / pasted text
  -> parse-document API
  -> DocumentStructureService
      -> DOCXStyleParser for .docx
      -> PDFDoclingParser for .pdf when enabled/available
      -> MarkItDownParser fallback
      -> TextRuleClassifier fallback/enrichment
  -> ParsedDocument + ParsedSegment[]
  -> OptimizationSession + OptimizationSegment semantic metadata
  -> Zhuque full-text detect
  -> Zhuque segment-label mapping
  -> Semantic reduce gate
  -> LLM rewrite body only
  -> Zhuque full-text recheck
```

## Core types

Use a central enum-like set of constants, preferably in a new backend service module:

- `SemanticType`
- `SemanticSource`
- `ParsedDocument`
- `ParsedSegment`
- `SegmentSemanticDecision`

Recommended semantic sources:

- `docx_style`
- `docling`
- `markitdown_text_rule`
- `manual_text_rule`
- `legacy_text_rule`

## Parser behavior

### DOCX

Use existing `python-docx` dependency.

- Read paragraph text and style names.
- Use style names to classify known structural paragraphs.
- Use text-rule classifier when style is `Normal`, missing, custom, or inconclusive.
- Preserve paragraph order as reading order.
- Build full text from parsed segments with the same separator convention used by session segments.

### PDF

Use Docling as configured engine.

- Import lazily so deployments without Docling still boot.
- Enforce timeout around conversion.
- Treat missing dependency, conversion exception, timeout, and empty output as fallback triggers.
- Convert Docling items into `ParsedSegment` records with page/bbox metadata where available.
- Use Docling labels for tables/captions/headings when available; enrich/fallback with text rules.

Fallback path:

- MarkItDown extracts text.
- Split into segments using current behavior.
- Apply text-rule classifier.

## Persistence

Preferred migration:

`optimization_segments`:

- `semantic_type` string nullable
- `semantic_source` string nullable
- `semantic_confidence` float nullable
- `reduce_allowed` boolean nullable
- `semantic_reason` string nullable
- `char_start` integer nullable
- `char_end` integer nullable
- `page_number` integer nullable
- `bbox_json` text nullable

`optimization_sessions`:

- `document_format` string nullable
- `parse_engine` string nullable
- `parse_fallback_used` boolean nullable
- `parse_trace` text/json nullable

Compatibility:

- If semantic fields are null, compute legacy text-rule classification at runtime.
- Do not require migrating historical segment text.

## Zhuque filtering change

Replace scattered direct classifier checks in the selection path with a semantic decision provider:

```python
classification = semantic_service.classify_or_load(seg)
if classification.reduce_allowed:
    selected.append(seg)
else:
    filtered.append({index, semantic_type, reason})
```

Retain position/overlap requirements:

- label must normalize to 0 or 2
- confidence must be above the existing threshold
- position must map to local segment spans
- overlap threshold stays unchanged unless separately tuned

## Trace

Add `segment_filter_audit` event after selection:

```json
{
  "type": "segment_filter_audit",
  "parser_engine": "docling",
  "parse_fallback_used": false,
  "zhuque_hit_count": 97,
  "filtered_count": 78,
  "selected_count": 19,
  "filtered_summary": {"TOC_ITEM": 60, "ACK_BODY": 5},
  "selected_segment_indices": [110, 111],
  "protected_samples": [
    {"segment_index": 28, "semantic_type": "ABSTRACT_BODY", "reason": "abstract_body"}
  ]
}
```

Do not store full text in trace.

## Config

Add backend settings:

- `PDF_STRUCTURE_ENGINE: str = "docling"`
- `PDF_STRUCTURE_FALLBACK_ENGINE: str = "markitdown"`
- `PDF_DO_OCR: bool = False`
- `PDF_DO_TABLE_STRUCTURE: bool = True`
- `PDF_STRUCTURE_TIMEOUT_SECONDS: int = 120`
- `DOCX_STRUCTURE_ENGINE: str = "python_docx"`

## Trade-offs

- Docling will be added as a real first-version dependency and default PDF engine; lazy import + timeout + fallback still prevent hard failures.
- Persisting semantic metadata improves auditability and retry consistency but requires migration.
- Runtime-only metadata is lower risk for MVP but weaker for debugging historical sessions.

## Rollback plan

- Keep MarkItDown path intact behind config.
- If Docling causes operational issues, set `PDF_STRUCTURE_ENGINE=markitdown`.
- If semantic metadata migration causes issues, runtime classifier fallback should still allow sessions to process.
