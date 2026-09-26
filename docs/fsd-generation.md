# Consistent FSD generation

The FSD pipeline separates semantic generation from presentation:

1. A compact approved-requirement design brief is passed to the FSD Content Agent.
2. OpenAI Structured Outputs returns `FSDDesignDraft` with grouped process decisions, flows and screens; the model never repeats the full baseline or controls DOCX/PDF layout.
3. Deterministic enrichment expands every approved requirement, test, traceability row, fixed metadata and exact source evidence locally.
4. The FSD release gate checks schema validity, approved-requirement coverage, reference integrity, source evidence, traceability and minimum screen coverage.
5. Only validated content reaches the fixed DOCX/PDF renderer.
6. The artifact stores template, schema, prompt and renderer versions, model, generation time and a SHA-256 fingerprint of the approved baseline.
7. A validated document is cached by baseline hash. Unchanged retries and regenerations skip OpenAI; rendering failures reuse the saved document.

The active `fsd-v2` contract combines the stable FSD and FS03 section patterns into 14 fixed sections. The compact response uses low reasoning and verbosity; the application expands complete requirement, test and traceability rows locally. Design records without approved requirement IDs are discarded, unresolved facts remain `TBD`, and the release gate rejects missing evidence, coverage, or out-of-limit collections. Progress logs and the UI timing panel report each measured FSD function separately.

## Versioning

The active contract is in `apps/api/templates/fsd/v1`. Do not edit a released version for an incompatible layout or schema change. Copy it to `v2`, update the active version in `app/fsd_template.py`, update the Pydantic schema and add regression fixtures.

## Consistency guarantees

- Section order, headings, branding, tables, diagrams and download formats are deterministic.
- Every approved requirement must appear in both functional detail and traceability.
- Generated records may reference only approved requirement IDs.
- Approved source quotes are restored from the database instead of trusting generated text.
- Missing SAP facts remain `TBD` and require human review.

Natural-language wording can vary between model calls. For stronger semantic stability, configure a dated model snapshot after confirming its availability for the account and run the consistency tests before changing model, prompt, schema or template versions.
