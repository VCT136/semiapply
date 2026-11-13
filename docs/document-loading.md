# Document Loading (BL-001, BL-002)

## Purpose
Loads a job ad, a CV, and writing samples into the application as context for generation and revision features (see `docs/generation.md` for BL-003).

**Local-only design:** Semiapply runs locally on the user's machine and uses the local `opencode` installation for AI features where necessary. The app prefers local filesystem references (paths/folder selection) over uploading file contents.

## Supported inputs
- **Formats:** PDF (`.pdf`), HTML (`.html`, `.htm`), plain text (`.txt`, `.text`, `.md` and other text content).
- **Sources:** Local file upload, web URL (`http`/`https`), or a local folder (for writing samples).

## Behavior
- The web UI provides separate sections for the **Job ad** and **CV**.
- For each document (job ad/CV), the user can provide either a URL or a local file (not both in the same submission).
- **Writing samples (BL-002):** The user can load writing samples as a reference for writing style via either (1) the folder selection button (opens the system folder picker; the app loads all supported files from the selected folder) or (2) a local folder path (advanced), or (3) one or more web URLs (separated by newlines, commas, or whitespace). Supported formats are the same (PDF, HTML, or plain text).
- URL loading fetches the resource and extracts readable text.
  - PDF URLs/files are parsed with `pypdf`.
  - HTML is parsed with BeautifulSoup and non-content tags (`script`, `style`, `noscript`, `svg`, `canvas`) are removed.
  - Other content is treated as text (UTF-8 with replacement for decoding errors).
- Extracted text is cleaned (normalized line endings, excessive blank lines collapsed).
- The UI displays the source, detected type, and extracted text for confirmation.
- Loaded job/CV/writing samples are kept in an in-memory session (cookie-based) for the local app so documents remain visible while loading others.
- Loaded context is also persisted to the local cache (`.semiapply_cache/context/` as canonical text files like `job_ad.txt`, `cv.txt`, `writing_sample_XX.txt`, plus `context_manifest.json` and `.semiapply_cache/state.json`) so it can be reused after restarting the app and read on demand by the model as an isolated workspace for generation. The cache state also stores remembered generation settings (selected model and output folder) between sessions.

## Constraints
- Original files are never modified by the program.
- Maximum fetch/upload/size limit is 10 MB per document (current scaffold limit).
- URL fetch follows redirects and uses a 30-second timeout. Pages that require login, block bots, or render content only via client-side JavaScript may not extract useful text.

## Implementation
- `app/main.py`: FastAPI routes and session-backed UI rendering (job, CV, writing samples).
- `app/loaders.py`: document source handling and text extraction (files, URLs, folders, multiple URLs).
- `app/templates/index.html`, `app/static/style.css`: basic web UI.
