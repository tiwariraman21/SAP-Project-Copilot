# Packaging Notes

This archive contains the complete application **source distribution** after the BRD-context/FSD pipeline changes.

Included:

- backend application source;
- frontend application source;
- `package.json` / lockfiles;
- Python requirements;
- FSD templates and prompts;
- tests;
- documentation;
- sample/output reference documents that were part of the source tree;
- `.env.example` / `.env.local.example` files.

Intentionally excluded from the source distribution:

- `.env` and `.env.local` containing runtime secrets;
- `.venv`;
- `node_modules`;
- `.next` build cache/output;
- `__pycache__`, `.pytest_cache`, and TypeScript build caches;
- local SQLite/database files;
- user `uploads/`;
- generated artifact/runtime folders;
- temporary/QA-render directories.

Those directories are regenerated locally by `pip install`, `npm install`, application startup, tests, or artifact generation. Excluding them keeps the archive safe, portable, and dramatically smaller without removing project source code.
