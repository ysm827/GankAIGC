# PDF/DOCX structure-aware Zhuque filtering

## Goal

Improve Zhuque AI-detect-reduce accuracy by adding a structure-aware document parsing and segment classification layer. Zhuque should continue detecting the complete paper text, but LLM rewriting must only run on actual body segments. Headings, abstracts, keywords, table-of-contents entries, acknowledgements, references, tables, captions, formulas, metadata, headers/footers, and very short fragments must be protected from rewriting.

## User Value

- Prevent accidental rewriting of thesis front/back matter such as abstract, TOC, acknowledgements, and references.
- Make PDF handling more accurate by defaulting to Docling layout/reading-order/table-aware parsing, while preserving reliability through MarkItDown fallback.
- Make DOCX handling more accurate by using Word paragraph styles before text heuristics.
- Preserve the user-facing Zhuque full-text score semantics: final checks still use the complete paper, not a正文-only subset.
- Provide auditable trace output so users can see which Zhuque-hit segments were rewritten and which were protected.

## Confirmed Facts From Current Code

- Current upload parsing uses MarkItDown for DOCX and PDF (`test_parse_docx_document_upload_uses_markitdown`, `test_parse_pdf_document_upload_uses_markitdown`).
- Current Zhuque flow detects full text, maps `segment_labels[].position` back to local segments, then filters with `_classify_zhuque_fallback_segments()`.
- Current fallback text classifier already protects common headings, abstract heading/body, keywords, TOC, acknowledgement heading/body, references, formulas, metadata, captions, and short text.
- Existing dependencies include `python-docx` and `markitdown[docx,pdf]`; Docling is not currently declared.
- Existing tests for Zhuque integration pass after the recent front-matter protection changes: `99 passed` in `package/backend/tests/test_zhuque_integration.py`.

## Requirements

### R1. Preserve Zhuque full-text detection semantics

- Initial and recheck Zhuque detection must send the complete document text/layout representation available to the session.
- Protected sections must not be removed before Zhuque detection.
- The UI/report wording should distinguish full-text Zhuque rate from actual body rewrite selection when surfaced.

### R2. Add unified semantic segment metadata

Each segment should have a normalized semantic decision, either persisted or computed and stored during session creation:

- `semantic_type`
- `semantic_source`
- `semantic_confidence`
- `reduce_allowed`
- `semantic_reason`
- character span fields such as `char_start` / `char_end`
- optional PDF metadata such as `page_number` and `bbox_json`

If persistence is deferred for MVP, equivalent metadata must be available in the Zhuque trace and service-layer decisions.

### R3. DOCX parser must prefer native Word structure

- DOCX segments should be classified using `python-docx` paragraph styles first.
- Recognize at minimum:
  - `Heading 1` through `Heading 4` -> `SECTION_HEADING`
  - `Title` -> `TITLE`
  - `TOC 1` through `TOC 4` -> `TOC_ITEM`
  - document headers/footers where available -> `HEADER_FOOTER`
- If style information is missing or inconclusive, fall back to the existing text-rule classifier.

### R4. PDF parser must default to Docling with MarkItDown fallback

- PDF structure engine default should be Docling for product builds.
- If Docling is not installed, times out, returns empty text, or raises, automatically fall back to MarkItDown.
- MarkItDown fallback must still run the text-rule classifier.
- Docling should be configurable, including OCR and table-structure settings.
- Recommended defaults:
  - `PDF_STRUCTURE_ENGINE=docling`
  - `PDF_DO_OCR=false`
  - `PDF_DO_TABLE_STRUCTURE=true`
  - `PDF_STRUCTURE_TIMEOUT_SECONDS=120`
  - `PDF_STRUCTURE_FALLBACK_ENGINE=markitdown`

### R5. Allowed/protected semantic types

Allowed to rewrite:

- `BODY`
- `MIXED_HEADING_BODY` (heading plus body in the same paragraph should be treated as body)

Protected from rewrite:

- `TITLE`
- `SECTION_HEADING`
- `ABSTRACT_HEADING`
- `ABSTRACT_BODY`
- `KEYWORDS`
- `TOC_HEADING`
- `TOC_ITEM`
- `ACK_HEADING`
- `ACK_BODY`
- `REFERENCE_HEADING`
- `REFERENCE_ITEM`
- `TABLE`
- `CAPTION`
- `FORMULA`
- `META`
- `HEADER_FOOTER`
- `SHORT_TEXT`
- `UNKNOWN_PROTECTED`

### R6. Zhuque segment filtering must use semantic metadata

- Zhuque `segment_labels` are still the first gate.
- Local semantic classification is the second gate.
- A segment is rewritten only if Zhuque marks it high/suspicious AI and semantic metadata says `reduce_allowed=true`.
- If all Zhuque-hit segments are protected, do not fallback to rewriting the full document.

### R7. Trace audit must explain filtering decisions

Zhuque trace should include compact metadata only, never full paper text:

- hit segment count
- filtered/protected count
- selected count
- selected segment indices
- filtered summary by semantic type
- optional sample protected segment indices and reasons
- parser engine and fallback status

### R8. Backward compatibility

- Existing sessions without semantic fields must continue to work using text-rule classification.
- Existing retry/export behavior must remain compatible.
- MarkItDown fallback must remain available for deployment environments where Docling is too heavy or unavailable.

## Acceptance Criteria

- [ ] PDF upload path defaults to Docling structure parsing when available.
- [ ] PDF parsing automatically falls back to MarkItDown on missing dependency, timeout, exception, or empty output.
- [ ] DOCX upload path classifies Word paragraph styles before text rules.
- [ ] Semantic classification protects abstract, keywords, TOC, acknowledgements, references, headings, formulas, metadata, tables/captions, headers/footers, and short fragments.
- [ ] Mixed heading+body paragraphs are classified as rewrite-eligible body.
- [ ] Zhuque still detects the complete document text.
- [ ] Zhuque rewrite selection only includes `reduce_allowed=true` body segments.
- [ ] If Zhuque only hits protected segments, the task stops or reports no reducible body instead of fallback-all rewriting.
- [ ] Trace includes parser engine, fallback reason if any, selected segment indices, filtered counts, and filtered semantic summary.
- [ ] Existing Zhuque integration tests still pass.
- [ ] New tests cover DOCX style classification, PDF Docling success, PDF MarkItDown fallback, protected front/back matter, mixed heading+body, and audit trace.

## Out of Scope For First Implementation

- Replacing Zhuque with another detector.
- Removing MarkItDown.
- Detecting only正文 while reporting it as full-text Zhuque rate.
- Heavy UI redesign beyond exposing compact audit information.
- Perfect OCR for all scanned PDFs; OCR should be configurable and can remain disabled by default.

## Decisions

- First implementation must add the real Docling dependency and make it the default PDF structure engine.
- Docling still needs lazy import / timeout / fallback safeguards so runtime can recover to MarkItDown if parsing fails.
