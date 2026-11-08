# Document Loading (BL-001)

## Purpose
Loads a job ad and a CV into the application as context for later generation and revision features.

## Supported inputs
- **Formats:** PDF (`.pdf`), HTML (`.html`, `.htm`), plain text (`.txt`, `.text`, `.md` and other text content).
- **Sources:** Local file upload or web URL (`http`/`https`).

## Behavior
- The web UI provides separate sections for the **Job ad** and **CV**.
- For each document, the user can provide either a URL or a local file (not both in the same submission).
- URL loading fetches the resource and extracts readable text.
  - PDF URLs/files are parsed with `pypdf`.
  - HTML is parsed with BeautifulSoup and non-content tags (`script`, `style`, `noscript`, `svg`, `canvas`) are removed.
  - Other content is treated as text (UTF-8 with replacement for decoding errors).
- Extracted text is cleaned (normalized line endings, excessive blank lines collapsed).
- The UI displays the source, detected type, and extracted text for confirmation.
- Loaded job/CV content is kept in an in-memory session (cookie-based) for the local app so both documents remain visible while loading the other.

## Constraints
- Original files are never modified by the program.
- Maximum fetch/upload size is 10 MB per document (current scaffold limit).
- URL fetch follows redirects and uses a 30-second timeout. Pages that require login, block bots, or render content only via client-side JavaScript may not extract useful text.

## Implementation
- `app/main.py`: FastAPI routes and session-backed UI rendering.
- `app/loaders.py`: document source handling and text extraction.
- `app/templates/index.html`, `app/static/style.css`: basic web UI.
