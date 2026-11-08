from __future__ import annotations

import secrets
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.loaders import LoadedDocument, load_document

app = FastAPI(title="Semiapply")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

SESSION_COOKIE = "semiapply_session"
# In-memory session store for local single-user development.
# Stores loaded document context so both job ad and CV remain visible.
SESSIONS: dict[str, dict[str, LoadedDocument | None]] = {}


def _get_session_id(request: Request) -> tuple[str, bool]:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid and sid in SESSIONS:
        return sid, False
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = {"job": None, "cv": None}
    return sid, True


def _doc_context(doc: LoadedDocument | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return asdict(doc)


def _render_index(
    request: Request,
    *,
    sid: str,
    set_cookie: bool,
    job_error: str | None = None,
    cv_error: str | None = None,
):
    session = SESSIONS.setdefault(sid, {"job": None, "cv": None})
    context = {
        "request": request,
        "job": _doc_context(session.get("job")),
        "cv": _doc_context(session.get("cv")),
        "job_error": job_error,
        "cv_error": cv_error,
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
    session = SESSIONS.setdefault(sid, {"job": None, "cv": None})
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
    session = SESSIONS.setdefault(sid, {"job": None, "cv": None})
    try:
        session["cv"] = await load_document(url=cv_url, upload=cv_file, label="CV")
        return _render_index(request, sid=sid, set_cookie=set_cookie)
    except Exception as exc:  # noqa: BLE001 - show user-facing load errors
        return _render_index(request, sid=sid, set_cookie=set_cookie, cv_error=str(exc))
