# Generation (BL-003)

## Purpose
Generates a customized CV and/or motivation letter tailored to a loaded job ad, using the applicant's loaded CV as the source of truth and optional writing samples as style reference.

## Requirements and constraints
- Uses the locally installed `opencode` CLI for generation (no hosted backend API keys managed by Semiapply).
- Model selection is provided in the app UI (models are listed via `opencode models` when available; a manual model ID can be entered if not).
- Generated content must be accurate and grounded in the provided materials.
- The app instructs the model not to invent, fabricate, or assume experience, skills, dates, employers, titles, education, or achievements.
- Irrelevant content may be omitted to better match the job ad.
- Outputs are saved as new plain text files in a user-selected local output folder.
- Existing/original files are never modified by the program. If a target filename already exists, a numeric suffix is added.

## Inputs used
- **Required:** loaded job ad and loaded CV (from BL-001).
- **Optional:** loaded writing samples for style/tone reference (from BL-002).

## Behavior
- In the "Generate tailored documents" section, the user selects:
  - a model (`provider/model`, optionally `#variant` as supported by `opencode run --model`),
  - an output folder (path or via the system folder picker),
  - which document(s) to generate (customized CV and/or motivation letter).
- **Local cache/workspace:** loaded documents are persisted to `.semiapply_cache/` so context can be reused between app restarts and accessed as files during generation. The cache context directory (used as the `opencode` working directory) contains canonical files such as `job_ad.txt`, `cv.txt`, `writing_sample_XX.txt`, and `context_manifest.json` (plus `state.json` at the cache root).
- **Remembered between sessions:** the chosen model and output folder are persisted in the local cache state (`.semiapply_cache/state.json` under `settings`) and pre-filled in the UI on subsequent sessions.
- **On-demand file reading (tool use allowed):** prompts do **not** embed the full job/CV/writing sample texts. Instead, each generation prompt lists the available cached context files and instructs the model to read/check them from the working directory on demand (tool use and intermediate steps are allowed).
- **Separate generation:** each requested document is generated independently with its own prompt and a separate `opencode run --model <selected-model> <prompt>` call (including when both CV and motivation letter are requested).
- **Final output requirements:** although intermediate steps/tool use may occur, the model is instructed that its **final response must be only the complete final document text**, ready to be saved and used directly (no preamble/commentary/notes, no tool-call JSON, no wrapping markdown fences). The app applies light cleanup for accidental wrappers and rejects outputs that are clearly tool-call/intermediate JSON instead of a final document (details visible in the transcript).
- Generated files are written as timestamped `.txt` files in the chosen output folder (e.g. `customized-cv-YYYYMMDD-HHMMSS.txt`, `motivation-letter-YYYYMMDD-HHMMSS.txt`).
- **Progress visualization and CLI transparency:** generation runs as a background job; the UI polls `/generate/status` and displays step-by-step progress messages (e.g. starting, preparing cache, generating CV, generating motivation letter, complete/error). For each `opencode run` invocation, the UI exposes the full command-line interaction (command, working directory, prompt/input sent, stdout, stderr, and exit code) in a transcript shown during generation and retained with the completed result. On completion the page reloads to show saved file paths, a generated output preview, and the transcript.

## Limitations / notes
- Generation quality and adherence to instructions depend on the selected model/agent behavior.
- `opencode` must be installed and available on `PATH`.
- Each document is a separate model call, so generating both takes longer than a single document but keeps outputs isolated and directly usable.
- Output is plain text (formatting/layout tailored to specific file formats like PDF/DOCX is out of scope for this item).
- Progress is session-scoped and in-memory (local single-user app), while loaded context is persisted in `.semiapply_cache/` for reuse across restarts. The cache is a local workspace aid and may contain extracted text from loaded documents.

## Implementation
- `app/generator.py`: model listing, per-document prompt construction, `opencode run` invocation, output cleanup, and safe file saving (with progress callbacks).
- `app/main.py`: `/generate/start` and `/generate/status` endpoints, background job/progress tracking, and session-backed generation result/error handling.
- `app/templates/index.html`, `app/static/style.css`: generation UI and progress visualization (polling).