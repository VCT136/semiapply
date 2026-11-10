# DONE

## Completed
- [x] **DEV-001 / BL-001:** Scaffolded Python + FastAPI web app and implemented loading of job ad and CV for context.
  - Project structure/dependencies (`pyproject.toml`), app package, Windows `run.bat`.
  - Basic web UI for URL/local file input (separate Job ad and CV sections).
  - Supports PDF, HTML, and plain text from local file or web URL (fetch & extract text).
  - Displays loaded source/type and extracted text for confirmation (readonly text areas).
  - Session-backed in-memory context keeps both documents visible; originals never modified.
  - Docs: `README.md`, `docs/document-loading.md`.

- [x] **DEV-002 / BL-002:** Implemented loading of writing samples for style reference.
  - Extended loaders to support loading all supported files from a local folder and loading from multiple web URLs.
  - Added session-backed storage for writing samples (accumulated in-memory).
  - Added UI section for writing samples with folder path or URL(s) input; displays loaded samples with source/type and extracted text.
  - Updated docs (`docs/document-loading.md`, `README.md`) and backlog tracking.

- [x] **DEV-003 / BL-003:** Implemented generation of customized CV and optional motivation letter.
  - Added `app/generator.py` to list models via `opencode models`, build a grounded prompt from loaded job/CV/samples, run `opencode run --model ...`, parse delimited output, and save new timestamped `.txt` files to a user-selected output folder (no overwrites; originals unchanged).
  - Added `/generate` route, session-backed generation result/error handling, and UI for model selection, output folder picker, document selection, and result display.
  - Added `docs/generation.md` and updated `README.md`, `docs/document-loading.md`, and backlog tracking.
