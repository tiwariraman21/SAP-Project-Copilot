# Combined SAP FSD / FS03 template v1

This directory is the single source of truth for FSD generation.

- `template-contract.json` fixes section order, branding and minimum content.
- `generation-prompt.txt` defines the content agent's stable instructions.
- `validation-rules.json` defines the release gate.
- `app/fsd_schemas.py` is the executable Structured Outputs JSON schema.
- `app/services/fsd_export.py` is the deterministic DOCX/PDF renderer.

Create a new version directory for incompatible changes. Existing generated
artifacts retain their recorded template, schema, prompt and renderer versions.
