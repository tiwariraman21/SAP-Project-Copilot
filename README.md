# SAP Project Copilot MVP

Competition-ready vertical slice for turning a Business Requirements Document (BRD) into a reviewable requirement baseline and a template-driven SAP Functional Specification Document (FSD).

## What works

1. Upload a PDF, DOCX, TXT, or Markdown BRD.
2. Extract page/paragraph-aware source chunks; DOCX tables are retained as source evidence.
3. When `OPENAI_API_KEY` is configured, analyze the **complete BRD once** into a persistent structured `BRDKnowledgeBase` containing process, scope, stakeholders, data, screens, integrations, rules, messages, NFRs, risks, acceptance criteria, and tests.
4. Generate atomic, source-linked requirements and send them through human approval/rejection.
5. Build the FSD from **three explicit inputs**: the versioned FSD template contract, persisted BRD knowledge, and the approved requirement baseline.
6. Validate grounding, completeness, traceability, BRD-context coverage, and template limits before rendering.
7. Export DOCX/PDF FSD output plus delivery backlog, technical design, test pack, traceability, and AI Companion artifacts.

## FSD generation architecture

```text
Uploaded BRD
    |
    +--> Local source extraction (page/chunk evidence)
    |
    +--> OpenAI full-document BRD understanding
             |
             v
       BRDKnowledgeBase (persisted)
             |
             +--> Requirement Intelligence --> Human Review --> Approved Baseline
             |
             +----------------------------------------------+
                                                            |
Versioned FSD Template Contract ----------------------------+
                                                            v
                                                   FSD Design Agent
                                                            |
                                                   Deterministic expansion
                                                            |
                                                     Release validation
                                                            |
                                                      DOCX / PDF
```

The FSD agent does **not** rely on conversation memory. The template contract is version-controlled locally, BRD knowledge is persisted in the database, and the approved requirements are stored as the human-reviewed baseline. This makes generation reproducible and cache-safe.

## Architecture

- `apps/web`: Next.js App Router frontend.
- `apps/api`: FastAPI + SQLAlchemy backend.
- SQLite is the zero-setup default; set `DATABASE_URL` to PostgreSQL for production.
- `app/brd_schemas.py`: structured full-BRD knowledge contract.
- `app/services/brd_intelligence.py`: OpenAI full-document BRD extraction with local-chunk fallback.
- `app/services/requirement_intelligence.py`: atomic source-linked requirement extraction with coverage guards.
- `app/services/functional_design.py`: template + BRD knowledge + approved-requirement FSD synthesis.
- `templates/fsd/v3/template-contract.json`: machine-readable 17-section FSD contract and section-to-BRD source map.
- `app/services/fsd_validation.py`: grounding/traceability/release gate.
- `app/services/fsd_export.py`: deterministic DOCX/PDF renderer.

## Run locally

Backend (PowerShell):

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

Backend (macOS/Linux):

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd apps/web
npm install
cp .env.local.example .env.local   # Windows: Copy-Item .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`.

Without an API key, the local demonstration path remains available for development. With `OPENAI_API_KEY`, the application performs full BRD knowledge extraction, requirement intelligence, and model-backed FSD design. Responses use `store=False`; model/token usage is recorded locally.

## Important OpenAI settings

See `apps/api/.env.example`.

- `OPENAI_BRD_MODEL`: deep full-document BRD understanding.
- `OPENAI_REQUIREMENTS_MODEL`: repetitive atomic requirement extraction.
- `OPENAI_FSD_MODEL`: FSD synthesis from template + BRD knowledge + approved requirements.
- `OPENAI_BRD_USE_FILE_INPUT=true`: prefer direct file input so PDF page visuals/tables/mockups are available to the BRD extractor.
- `OPENAI_MAX_SOURCE_CHARACTERS` and `OPENAI_REQUIREMENTS_MAX_BATCHES`: **coverage guards**. The application now fails explicitly instead of silently dropping later BRD content.

## API

- `POST /api/projects` - upload and analyze a BRD synchronously.
- `POST /api/projects/start` - upload and start background BRD/requirement analysis.
- `GET /api/projects/{id}` - fetch the review workspace.
- `GET /api/projects/{id}/brd-knowledge` - inspect the persisted structured BRD context used by downstream generation.
- `PATCH /api/requirements/{id}` - edit/review a requirement.
- `POST /api/projects/{id}/approve` - approve the reviewed baseline.
- `POST /api/projects/{id}/artifacts/{kind}` - generate a downstream artifact (`fsd`, `backlog`, `technical_design`, `test_cases`, `traceability`, or `companion`).
- `GET /api/projects/{id}/usage` - inspect recorded model/token usage.
- `GET /api/usage` - inspect all recorded local model/token usage.
- `GET /health` - health check and configured pipeline/model summary.

## Security / packaging

Do not commit `.env`, user uploads, generated artifacts, local databases, virtual environments, `node_modules`, or `.next`. The distribution ZIP produced for this revision intentionally excludes those runtime/secrets directories while keeping the complete source tree, lockfiles, templates, tests, and `.env.example` files.

For the detailed design rationale and modification map, see [`docs/brd-context-pipeline.md`](docs/brd-context-pipeline.md).
