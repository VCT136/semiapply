from __future__ import annotations

import asyncio
import secrets
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.cache import load_persisted_context, save_session_context
from app.generator import generate_documents, list_models
from app.loaders import LoadedDocument, load_document, load_documents_from_folder, load_documents_from_urls

app = FastAPI(title="Semiapply")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

SESSION_COOKIE = "semiapply_session"
# In-memory session store for local single-user development.
# Stores loaded document context so job ad, CV, and writing samples remain visible.
SESSIONS: dict[str, dict[str, Any]] = {}
PERSISTED_CONTEXT: dict[str, Any] = load_persisted_context()


def _default_session() -> dict[str, Any]:
    # Start from persisted context (survives restarts via local cache).
    persisted = PERSISTED_CONTEXT or {"job": None, "cv": None, "samples": []}
    return {
        "job": persisted.get("job"),
        "cv": persisted.get("cv"),
        "samples": list(persisted.get("samples") or []),
        "generation": None,
        "generation_job": {
            "status": "idle",  # idle|running|completed|error
            "message": "",
            "steps": [],
            "error": None,
            "transcript": "",
        },
    }


def _ensure_session(sid: str) -> dict[str, Any]:
    session = SESSIONS.setdefault(sid, _default_session())
    # Backfill keys for older sessions.
    base = _default_session()
    for k, v in base.items():
        if k not in session:
            session[k] = v
    if not isinstance(session.get("generation_job"), dict):
        session["generation_job"] = base["generation_job"].copy()
    return session


def _get_session_id(request: Request) -> tuple[str, bool]:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid and sid in SESSIONS:
        _ensure_session(sid)
        return sid, False
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = _default_session()
    return sid, True


def _doc_context(doc: LoadedDocument | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return asdict(doc)


def _docs_context(docs: list[LoadedDocument] | None) -> list[dict[str, Any]]:
    if not docs:
        return []
    return [asdict(doc) for doc in docs]


def _render_index(
    request: Request,
    *,
    sid: str,
    set_cookie: bool,
    job_error: str | None = None,
    cv_error: str | None = None,
    samples_error: str | None = None,
    generate_error: str | None = None,
    models: list[str] | None = None,
):
    session = _ensure_session(sid)
    context = {
        "request": request,
        "job": _doc_context(session.get("job")),
        "cv": _doc_context(session.get("cv")),
        "samples": _docs_context(session.get("samples") or []),
        "job_error": job_error,
        "cv_error": cv_error,
        "samples_error": samples_error,
        "generate_error": generate_error or (session.get("generation_job") or {}).get("error"),
        "generation": session.get("generation"),
        "generation_job": session.get("generation_job"),
        "models": models if models is not None else list_models(),
    }
    response = templates.TemplateResponse(request=request, name="index.html", context=context)
    if set_cookie:
        response.set_cookie(
            SESSION_COOKIE,
            sid,
            httponly=True,
            samesite="lax",
        )
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/pick/folder")
async def pick_folder():
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder_path = filedialog.askdirectory(master=root)
        root.destroy()
        if not folder_path:
            return JSONResponse({"path": None})
        return JSONResponse({"path": folder_path})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"path": None, "error": str(exc)}, status_code=500)



@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    sid, set_cookie = _get_session_id(request)
    return _render_index(request, sid=sid, set_cookie=set_cookie)


def _start_generation_job(
    sid: str,
    *,
    model: str,
    output_dir: str,
    generate_cv_flag: bool,
    generate_letter_flag: bool,
) -> None:
    session = _ensure_session(sid)
    job = session.get("job")
    cv = session.get("cv")
    samples = session.get("samples") or []

    # Basic synchronous validation before starting background work for clearer immediate errors.
    if not generate_cv_flag and not generate_letter_flag:
        raise ValueError("Select at least one document to generate (CV and/or motivation letter).")
    if not (model or "").strip():
        raise ValueError("Select a model.")
    if not (output_dir or "").strip():
        raise ValueError("Select an output folder.")
    out_dir = Path(output_dir)
    if not out_dir.exists() or not out_dir.is_dir():
        raise ValueError(f"Output folder does not exist or is not a directory: {out_dir}")
    if not job or not getattr(job, "text", "").strip():
        raise ValueError("Load a job ad before generating.")
    if not cv or not getattr(cv, "text", "").strip():
        raise ValueError("Load a CV before generating.")

    session["generation_job"] = {
        "status": "running",
        "message": "Starting generation...",
        "steps": ["Starting generation..."],
        "error": None,
        "transcript": "",
    }
    session["generation"] = None
    # Ensure loaded context is persisted to the local cache workspace used for generation.
    save_session_context(session)

    job_text = job.text
    cv_text = cv.text
    samples_texts = [s.text for s in samples if getattr(s, "text", None)]

    def worker() -> None:
        def progress(msg: str, data: dict | None = None) -> None:
            s = SESSIONS.get(sid)
            if not s:
                return
            gj = s.setdefault(
                "generation_job",
                {"status": "running", "message": "", "steps": [], "error": None, "transcript": ""},
            )
            gj["status"] = "running"
            gj["message"] = msg
            steps = gj.setdefault("steps", [])
            if not steps or steps[-1] != msg:
                steps.append(msg)
            if data and isinstance(data, dict):
                entry = data.get("transcript")
                if entry:
                    existing = gj.get("transcript") or ""
                    gj["transcript"] = (existing + ("\n\n" if existing else "") + str(entry)).strip()

        try:
            result = asyncio.run(
                generate_documents(
                    model=model,
                    output_dir=output_dir,
                    job_text=job_text,
                    cv_text=cv_text,
                    samples_texts=samples_texts,
                    generate_cv=generate_cv_flag,
                    generate_letter=generate_letter_flag,
                    progress_callback=progress,
                )
            )
            s = SESSIONS.get(sid)
            if not s:
                return
            s["generation"] = asdict(result)
            prev = s.get("generation_job") or {}
            s["generation_job"] = {
                "status": "completed",
                "message": "Generation complete.",
                "steps": prev.get("steps") or ["Generation complete."],
                "error": None,
                "transcript": (result.transcript or prev.get("transcript") or "").strip(),
            }
        except Exception as exc:  # noqa: BLE001
            s = SESSIONS.get(sid)
            if not s:
                return
            err = str(exc)
            gj = s.get("generation_job") or {"steps": [], "transcript": ""}
            steps = gj.get("steps") or []
            if not steps or steps[-1] != f"Error: {err}":
                steps.append(f"Error: {err}")
            s["generation_job"] = {
                "status": "error",
                "message": err,
                "steps": steps,
                "error": err,
                "transcript": gj.get("transcript") or "",
            }

    threading.Thread(target=worker, daemon=True).start()


@app.post("/generate/start")
async def generate_start(
    request: Request,
    model: str = Form(default=""),
    output_dir: str = Form(default=""),
    generate_cv: str | None = Form(default=None),
    generate_letter: str | None = Form(default=None),
):
    sid, set_cookie = _get_session_id(request)
    try:
        _start_generation_job(
            sid,
            model=model,
            output_dir=output_dir,
            generate_cv_flag=bool(generate_cv),
            generate_letter_flag=bool(generate_letter),
        )
        resp = JSONResponse({"status": "started"})
    except Exception as exc:  # noqa: BLE001
        session = _ensure_session(sid)
        session["generation_job"] = {
            "status": "error",
            "message": str(exc),
            "steps": [f"Error: {exc}"],
            "error": str(exc),
            "transcript": "",
        }
        resp = JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.get("/generate/status")
async def generate_status(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    job = session.get("generation_job") or {"status": "idle", "message": "", "steps": [], "error": None, "transcript": ""}
    payload = {
        "status": job.get("status", "idle"),
        "message": job.get("message", ""),
        "steps": job.get("steps", []),
        "error": job.get("error"),
        "has_result": bool(session.get("generation")),
        "transcript": job.get("transcript", ""),
    }
    resp = JSONResponse(payload)
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.post("/generate", response_class=HTMLResponse)
async def generate(request: Request):
    # Fallback for non-JS form posts: redirect-like behavior by starting job is complex;
    # keep endpoint simple by instructing use of UI. Show current state.
    sid, set_cookie = _get_session_id(request)
    return _render_index(request, sid=sid, set_cookie=set_cookie, generate_error="Generation is started from the UI with progress tracking. Please use the Generate button.")


@app.post("/load/job", response_class=HTMLResponse)
async def load_job(
    request: Request,
    job_url: str = Form(default=""),
    job_file: UploadFile | None = File(default=None),
):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    try:
        session["job"] = await load_document(url=job_url, upload=job_file, label="Job ad")
        save_session_context(session)
        return _render_index(request, sid=sid, set_cookie=set_cookie)
    except Exception as exc:  # noqa: BLE001 - show user-facing load errors
        return _render_index(request, sid=sid, set_cookie=set_cookie, job_error=str(exc))


@app.post("/load/cv", response_class=HTMLResponse)
async def load_cv(
    request: Request,
    cv_url: str = Form(default=""),
    cv_file: UploadFile | None = File(default=None),
):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    try:
        session["cv"] = await load_document(url=cv_url, upload=cv_file, label="CV")
        save_session_context(session)
        return _render_index(request, sid=sid, set_cookie=set_cookie)
    except Exception as exc:  # noqa: BLE001 - show user-facing load errors
        return _render_index(request, sid=sid, set_cookie=set_cookie, cv_error=str(exc))


@app.post("/load/samples", response_class=HTMLResponse)
async def load_samples(
    request: Request,
    samples_urls: str = Form(default=""),
    samples_folder: str = Form(default=""),
):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    samples_urls_clean = (samples_urls or "").strip()
    samples_folder_clean = (samples_folder or "").strip()

    try:
        if samples_folder_clean and samples_urls_clean:
            raise ValueError("Provide either a local folder or URL(s), not both.")
        if not samples_folder_clean and not samples_urls_clean:
            raise ValueError("Provide a local folder (use the button or enter path) or one or more web URL(s) for writing samples.")

        loaded: list[LoadedDocument] = []
        if samples_folder_clean:
            loaded = await load_documents_from_folder(samples_folder_clean, label_prefix="Writing sample")
        elif samples_urls_clean:
            # Support comma, newline, or whitespace separated URLs
            import re

            urls = re.split(r"[\n,\s]+", samples_urls_clean)
            loaded = await load_documents_from_urls(urls, label_prefix="Writing sample")

        if not isinstance(session.get("samples"), list):
            session["samples"] = []
        session["samples"].extend(loaded)
        save_session_context(session)
        return _render_index(request, sid=sid, set_cookie=set_cookie)
    except Exception as exc:  # noqa: BLE001 - show user-facing load errors
        return _render_index(request, sid=sid, set_cookie=set_cookie, samples_error=str(exc))



