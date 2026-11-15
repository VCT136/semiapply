# Chat UI for Revisions (BL-004)

## Purpose
Provides a chat UI for requesting revisions to generated application documents and improving them with additional information (e.g., skills, career details, tone preferences).

## Requirements and constraints
- Requires generated content to revise (customized CV and/or motivation letter from BL-003).
- Uses the locally installed `opencode` CLI for revisions (same local-only model as generation).
- Revision requests are grounded in loaded context files (job ad, CV, writing samples) and any additional factual information explicitly provided by the user in chat.
- The app instructs the model not to invent or fabricate skills, dates, employers, titles, education, or achievements. Information provided by the user in chat may be incorporated as stated, without embellishment.
- Each revision produces a new complete document text and is saved as a new timestamped `.txt` file in the selected output folder (e.g. `customized-cv-revised-YYYYMMDD-HHMMSS.txt`).
- Existing/original files and previous generated/revised outputs are never modified.

## Behavior
- The "Revise generated content" section includes:
  - a document selector (Customized CV or Motivation letter),
  - a reading area showing the current selected document text,
  - chat history (user requests and assistant confirmations),
  - an input field to request revisions or provide additional information.
- The active document text is initialized from the latest generated results in the session and updated after each successful revision.
- Revisions use the remembered model/output folder settings (configurable in the "Generate application documents" section). The model may read cached context files from the local workspace on demand; the final response must be only the complete revised document text.
- Chat history and current revised document texts are kept in the in-memory session (local single-user app). Revised files are written to the chosen output folder.

## Limitations / notes
- Revision quality and adherence to instructions depend on the selected model/agent behavior.
- If the app/session is restarted, in-memory chat history and unsynced revised working text may be lost; saved revision files remain in the output folder and previously loaded source context remains available via the local cache.
- Output is plain text.

## Implementation
- `app/generator.py`: `build_revision_prompt(...)` and `revise_document(...)` (runs `opencode run` in the cached context workspace and saves a new revision file).
- `app/main.py`: chat session state, `/chat/send` route, and synchronization of chat working documents from generation results.
- `app/templates/index.html`, `app/static/style.css`: chat/revision UI (reading area, chat history, input, document selection).
