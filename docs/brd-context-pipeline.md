# BRD Context → Template-Driven FSD Pipeline

## Why this revision exists

The previous FSD generation call received only the approved requirement catalogue. That preserved the human-review baseline, but it could omit valuable BRD context such as stakeholder tables, process diagrams, screen mockups, data ownership, status definitions, integration requirements, business messages, NFRs, risks, and detailed test scenarios.

This revision introduces a durable structured BRD context layer and makes it an explicit input to FSD generation.

## 1. Full BRD knowledge extraction

`app/services/brd_intelligence.py` analyzes the original uploaded document and parses it into `BRDKnowledgeBase` from `app/brd_schemas.py`.

Preferred mode:

```text
Original PDF/DOCX/TXT/MD
  -> OpenAI file input
  -> BRDKnowledgeBase structured output
```

Fallback mode:

```text
All locally extracted chunks in source order
  -> one complete structured extraction request
  -> BRDKnowledgeBase
```

The result is persisted in the `brd_knowledge` table with extraction version, model, input mode, source SHA-256, coverage percentage, and JSON payload.

## 2. Requirement Intelligence remains human-controlled

Requirement extraction still produces atomic, source-linked review candidates. The approved/rejected state is not inferred from the BRD knowledge object; it remains a human decision.

Two coverage safeguards were added:

- If locally extracted source exceeds `OPENAI_MAX_SOURCE_CHARACTERS`, extraction fails explicitly instead of truncating the end of the BRD.
- If the document requires more than `OPENAI_REQUIREMENTS_MAX_BATCHES`, extraction fails explicitly instead of dropping later batches.

## 3. FSD input contract

The FSD design request now contains:

```json
{
  "project": {
    "name": "...",
    "source_document": "...",
    "brd_knowledge_version": "brd-knowledge-v1",
    "brd_knowledge_coverage_percent": 100.0
  },
  "brd_knowledge": { "...": "complete structured BRD facts" },
  "approved_requirements": [ "...human-approved implementation baseline..." ]
}
```

The static `instructions` come from the versioned FSD template contract and generation prompt. This separates:

- **template semantics** — stable, reusable, version controlled;
- **BRD facts** — project-specific source knowledge;
- **approved requirements** — project-specific human-reviewed implementation baseline.

## 4. Machine-readable FSD template

`templates/fsd/v3/template-contract.json` now maps each of the 17 FSD sections to the BRD knowledge domains that should inform it. The generation prompt tells the model how to use this map and prohibits invention of SAP objects not stated in the source.

Screen limits were increased from four to ten and screen field/action caps were raised. The renderer no longer hard-codes a four-screen navigation diagram.

## 5. First-class FSD design collections

`FSDDocument` / `FSDDesignDraft` now include:

- `data_mappings`
- `status_definitions`
- `message_catalog`
- `non_functional_requirements`

These collections allow rich BRDs such as Supplier 360 to carry source-system data ownership, business status semantics, error/message behavior, and performance/security/usability targets into the FSD instead of burying them in prose.

## 6. Deterministic release gate

The model creates compact design decisions. Local code then restores/guarantees:

- all approved requirements;
- test coverage;
- traceability rows;
- source evidence;
- grounded requirement IDs;
- collection size bounds;
- reproducible generation metadata.

Generated design records with no approved requirement grounding are removed and recorded as an open issue.

## 7. DOCX/PDF rendering

The renderer now follows the 17-section master layout and includes dedicated subsections for data mapping, status definitions, business messages, NFRs, integrations, roles/authorizations, tests, traceability, RICEFW, risks, open points, localization, and appendices.

## 8. Recommended next production upgrades

1. Add a real migration tool (Alembic) before deploying database schema changes beyond local SQLite.
2. Add project-level model evaluation fixtures using several representative SAP BRDs.
3. Introduce retrieval/vector search when one project routinely includes multiple very large source documents rather than one BRD.
4. Add organization-specific SAP authorization and technical-design enrichment only after those facts are supplied or approved by a functional/technical lead.
5. Add resumable BRD extraction if a model/network failure occurs after upload.
