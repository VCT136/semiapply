# DONE

## Completed
- [x] **DEV-001 / BL-001:** Scaffolded Python + FastAPI web app and implemented loading of job ad and CV for context.
  - Project structure/dependencies (`pyproject.toml`), app package, Windows `run.bat`.
  - Basic web UI for URL/local file input (separate Job ad and CV sections).
  - Supports PDF, HTML, and plain text from local file or web URL (fetch & extract text).
  - Displays loaded source/type and extracted text for confirmation (readonly text areas).
  - Session-backed in-memory context keeps both documents visible; originals never modified.
  - Docs: `README.md`, `docs/document-loading.md`.
