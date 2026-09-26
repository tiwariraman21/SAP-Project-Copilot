# Changelog

## BRD Context Enhanced FSD Pipeline - 2026-08-26

- Added complete `BRDKnowledgeBase` schema and persistent BRD knowledge store.
- Added original-file OpenAI BRD analysis with all-chunk fallback.
- Added source-hash/model/version reuse so unchanged BRDs do not incur repeated full-document extraction calls.
- FSD generation now receives template semantics + BRD knowledge + approved requirements.
- Added BRD knowledge inspection API endpoint.
- Prevented silent BRD truncation and silent requirement-batch dropping.
- Added DOCX table extraction.
- Added semantic near-duplicate requirement filtering.
- Expanded FSD screen capacity from 4 to 10 and removed the renderer's four-screen cap.
- Added first-class data mapping, status definition, message catalogue, and NFR collections.
- Updated template contract, generation prompt, validation and 17-section DOCX/PDF rendering.
- Added/updated tests for context injection, coverage guards, and DOCX table extraction.
- Updated environment configuration and documentation.
