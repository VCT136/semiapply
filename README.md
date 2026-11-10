# Semiapply

A web tool to help find a job and facilitate job applications.

## Deployment / Usage model
- **Local-only:** Semiapply is intended to run locally on the user's machine (see run instructions below). It is not designed as a hosted multi-user service.
- **Local OpenCode integration:** Where AI features are needed (e.g., generation and revisions), Semiapply is planned to use the locally installed `opencode` CLI with model selection in the app. No external API keys need to be managed by a hosted backend.
- **Local filesystem access:** Because it runs locally, the app can reference local files and folders by path (and use local system dialogs) without requiring file uploads where not necessary.

## Current status
Early development. See `BACKLOG.md`, `TODO.md`, and `DONE.md`.

## Features (in progress / planned)
- **BL-001 (Done):** Load a job ad and CV for context from a local file or web URL (PDF, HTML, or text).
- **BL-002 (Done):** Load writing samples (e.g., motivation/cover letters) for style reference from a local folder or web URL(s) (PDF, HTML, or text).
- **BL-003:** Generate a customized CV and optional motivation letter tailored to a job ad (accurate; no fabrication; may omit irrelevant content). Generated files are saved as new text files; originals remain unchanged.
- **BL-004:** Chat UI for requesting revisions and improving generated content.

## Tech stack
- Python 3.10+
- FastAPI + Jinja2 web UI
- OpenCode CLI integration for generation/revisions (planned): uses installed `opencode`, with model selection in the app.

## Run (Windows)
```bat
run.bat
```
This creates `.venv` if needed, installs dependencies (`pip install -e .`), and starts the app.

## Manual setup/run
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python -m uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000/



## Development notes
- Document loading supports local files and URL fetch/extraction for PDF, HTML, and plain text.
- Original user files are never modified by the program.
- Generated outputs (future) will be saved to a user-chosen folder as new text files.
