# Document Loading (BL-001, BL-002)

## Purpose
Loads a job ad, a CV, and writing samples into the application as context for generation and revision features (see `docs/generation.md` for BL-003 and `docs/chat.md` for BL-004).

**Local-only design:** Semiapply runs locally on the user's machine and uses the local `opencode` installation for AI features where necessary. The app prefers local filesystem references (paths/folder selection) over uploading file contents.

## Supported inputs
- **Formats:** PDF (`.pdf`), HTML (`.html`, `.htm`), plain text (`.txt`, `.text`, `.md` and other text content).
- **Sources:** Local file, web URL (`http`/`https`), or a local folder (for writing samples).

## Behavior

### Job ad and CV
- The web UI provides separate sections for the **Job ad** and **CV**, each represented by a single button with integrated status text.
- **No document loaded:** the button shows:
  - 1st line: document type/title (`CV` or `Job ad`)
  - 2nd line: status message (e.g. `No document loaded.`)
  - Clicking the button opens a modal with:
    - a **Web URL** input and a **Load** button next to it, and
    - a **Local file** picker below.
  - The URL **Load** button is disabled until a valid `http(s)` URL is entered. Clicking it loads/extracts text from the URL.
  - Selecting a local file loads/extracts text from that file immediately.
  - On successful load, the load modal closes and a **preview/confirm** modal opens showing the extracted text in a read-only text area with **Back** and **Confirm** actions.
    - **Confirm** stores the document as loaded context and closes the modal.
    - **Back** discards the preview and returns to the load modal.
- **Document loaded:** the button uses a highlighted color and shows:
  - 1st line: document type/title (`CV` or `Job ad`)
  - 2nd line: document filename/source (truncated if long)
  - 3rd line: status message (e.g. `Loaded. Click to manage.`)
  - Clicking the button opens a modal to **remove** the loaded document. Confirming removal clears the loaded document (and persisted context) and returns the button to its unloaded state.

### Writing samples (BL-002)
- The web UI provides a single **Writing samples** button (matching the CV/Job ad document buttons).
  - **No samples loaded:** the button shows the title and a status message. Clicking opens a modal to load samples.
  - **Samples loaded:** the button uses the loaded (green) highlight and shows a brief summary (e.g. number of samples loaded). Clicking opens the same modal to manage samples.
- In the modal, the user can load/adjust writing samples by:
  - Selecting a local folder via the system folder picker, which loads supported files from that folder immediately (replacing any currently loaded writing samples), or
  - Providing different web URL(s) (separated by newlines, commas, or whitespace) and clicking **Load URL(s)** to load from those URLs (replacing any currently loaded writing samples).
  Supported formats are the same (PDF, HTML, or plain text).
- The modal also allows removing all loaded writing samples, returning the button to its unloaded state.

### Extraction and persistence
- URL loading fetches the resource and extracts readable text.
  - PDF URLs/files are parsed with `pypdf`.
  - HTML is parsed with BeautifulSoup and non-content tags (`script`, `style`, `noscript`, `svg`, `canvas`) are removed.
  - Other content is treated as text (UTF-8 with replacement for decoding errors).
- Extracted text is cleaned (normalized line endings, excessive blank lines collapsed).
- Loaded job/CV/writing samples are kept in an in-memory session (cookie-based) for the local app so documents remain visible while loading others.
- Loaded context is also persisted to the local cache (`.semiapply_cache/context/` as canonical text files like `job_ad.txt`, `cv.txt`, `writing_sample_XX.txt`, plus `context_manifest.json` and `.semiapply_cache/state.json`) so it can be reused after restarting the app and read on demand by the model as an isolated workspace for generation. The cache state also stores remembered generation settings (selected model and output folder) between sessions.
- Job/CV preview loads are kept temporarily in session until confirmed or cancelled.

## Constraints
- Original files are never modified by the program.
- Maximum fetch/upload/size limit is 10 MB per document (current scaffold limit).
- URL fetch follows redirects and uses a 30-second timeout. Pages that require login, block bots, or render content only via client-side JavaScript may not extract useful text.

## Implementation
- `app/main.py`: FastAPI routes and session-backed UI rendering/state (job, CV, writing samples), including preview/confirm/cancel/remove endpoints for job/CV modal flow.
- `app/loaders.py`: document source handling and text extraction (files, URLs, folders, multiple URLs).
- `app/templates/index.html`, `app/static/style.css`: web UI, modal interactions, and client-side loading/management flows for job/CV and writing samples.
