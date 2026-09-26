# SAP Project Copilot MVP - Test Guide

## 1. Start the services

Backend terminal (from `apps/api`):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Frontend terminal (from the project root):

```powershell
cd apps/web
npm run dev
```

Open http://localhost:3000.

## 2. Upload the sample BRD

1. Enter project name: `S/4HANA Order-to-Cash Improvement`.
2. Select `sample-sap-order-to-cash-brd.txt` from this output folder.
3. Click **Analyze BRD**.

The no-key demo extractor should identify multiple source-linked requirements. Results can vary when OpenAI extraction is enabled.

## 3. Review requirements

For every requirement, confirm that:

- It has a `REQ-###` identifier.
- The requirement statement is meaningful.
- A source paragraph and quote are displayed.
- Acceptance criteria are present.
- Confidence and priority are displayed.

Click **Approve** for valid requirements and **Reject** for anything unsuitable.

## 4. Approve the baseline

The **Approve baseline** button remains disabled until every requirement has been reviewed and at least one is approved.

After reviewing all requirements, click **Approve baseline**. The project should change to `Baseline approved` and display six downstream capabilities:

- Functional Specification
- Backlog & Sprint Plan
- Technical Design
- Test Cases
- Traceability Matrix
- AI Companion

Click each card or use its sidebar item to generate the corresponding artifact from the approved baseline.

## 5. Test all delivery capabilities

After baseline approval, open each enabled sidebar item and click its Generate button:

1. **Functional Design** - scope, approved functional requirements, acceptance criteria, controls, and open questions.
2. **Project Planning** - user stories, priorities, story points, sprint allocation, and sprint goals.
3. **Technical Design** - architecture, requirement-level component designs, security controls, and technical decisions.
4. **Quality & Testing** - requirement-linked test cases, preconditions, steps, expected results, and quality gates.
5. **Traceability** - BRD requirement to FSD section, backlog story, and test case coverage.
6. **AI Companion** - grounded project summary, suggested questions, requirement citations, and knowledge-base guardrails.

Use **Regenerate** on any generated artifact to rebuild it from the approved baseline. Confirm that rejected requirements do not appear in downstream outputs.

## 6. Optional API checks

- Health: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

The health response uses `demo` mode when no OpenAI key is configured and `openai` mode when a key is available.

## Troubleshooting

- Backend root `/` returning 404 is expected; use `/health` or `/docs`.
- If the frontend cannot reach the backend, confirm both terminals are still running.
- If port 3000 is occupied, use the alternative URL printed by the frontend terminal.
- If the document produces no requirements, use the supplied sample TXT file first to verify the complete workflow.
