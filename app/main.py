from __future__ import annotations

import secrets
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.loaders import LoadedDocument, load_document, load_documents_from_folder, load_documents_from_urls, load_documents_from_uploads

app = FastAPI(title="Semiapply")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

SESSION_COOKIE = "semiapply_session"
# In-memory session store for local single-user development.
# Stores loaded document context so job ad, CV, and writing samples remain visible.
SESSIONS: dict[str, dict[str, Any]] = {}


def _get_session_id(request: Request) -> tuple[str, bool]:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid and sid in SESSIONS:
        return sid, False
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = {"job": None, "cv": None, "samples": []}
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
):
    session = SESSIONS.setdefault(sid, {"job": None, "cv": None, "samples": []})
    context = {
        "request": request,
        "job": _doc_context(session.get("job")),
        "cv": _doc_context(session.get("cv")),
        "samples": _docs_context(session.get("samples") or []),
        "job_error": job_error,
        "cv_error": cv_error,
        "samples_error": samples_error,
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


@app.post("/load/job", response_class=HTMLResponse)
async def load_job(
    request: Request,
    job_url: str = Form(default=""),
    job_file: UploadFile | None = File(default=None),
):
    sid, set_cookie = _get_session_id(request)
    session = SESSIONS.setdefault(sid, {"job": None, "cv": None, "samples": []})
    try:
        session["job"] = await load_document(url=job_url, upload=job_file, label="Job ad")
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
    session = SESSIONS.setdefault(sid, {"job": None, "cv": None, "samples": []})
    try:
        session["cv"] = await load_document(url=cv_url, upload=cv_file, label="CV")
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
    session = SESSIONS.setdefault(sid, {"job": None, "cv": None, "samples": []})
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
        return _render_index(request, sid=sid, set_cookie=set_cookie)
    except Exception as exc:  # noqa: BLE001 - show user-facing load errors
        return _render_index(request, sid=sid, set_cookie=set_cookie, samples_error=str(exc))



