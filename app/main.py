from __future__ import annotations

import asyncio
import secrets
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.cache import load_persisted_context, save_persisted_settings, save_session_context
from app.generator import generate_documents, list_models, revise_document
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
    persisted = PERSISTED_CONTEXT or {"job": None, "cv": None, "samples": [], "settings": {}}
    settings = persisted.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    return {
        "job": persisted.get("job"),
        "cv": persisted.get("cv"),
        "job_preview": None,
        "cv_preview": None,
        "samples": list(persisted.get("samples") or []),
        "generation": None,
        "generation_job": {
            "status": "idle",  # idle|running|completed|error
            "message": "",
            "steps": [],
            "error": None,
            "transcript": "",
        },
        "chat": {
            "messages": [],
            "active_doc": "cv",
            "cv_text": None,
            "letter_text": None,
            "cv_path": None,
            "letter_path": None,
            "last_model": "",
            "error": None,
        },
        "settings": {
            "model": str(settings.get("model") or ""),
            "output_dir": str(settings.get("output_dir") or ""),
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
    if not isinstance(session.get("chat"), dict):
        session["chat"] = base["chat"].copy()
    else:
        chat_base = base["chat"]
        for k, v in chat_base.items():
            if k not in session["chat"]:
                session["chat"][k] = v
        if not isinstance(session["chat"].get("messages"), list):
            session["chat"]["messages"] = []
    return session


def _sync_chat_from_generation(session: dict[str, Any]) -> None:
    gen = session.get("generation") or {}
    chat = session.setdefault("chat", _default_session()["chat"].copy())
    if not isinstance(chat, dict):
        chat = _default_session()["chat"].copy()
        session["chat"] = chat
    cv_text = gen.get("cv_text")
    letter_text = gen.get("letter_text")
    if cv_text and not chat.get("cv_text"):
        chat["cv_text"] = cv_text
        chat["cv_path"] = gen.get("cv_path")
    elif cv_text:
        # keep latest generation texts available if chat hasn't diverged via revision? update when generation reruns
        if gen.get("cv_path") and gen.get("cv_path") != chat.get("cv_path"):
            chat["cv_text"] = cv_text
            chat["cv_path"] = gen.get("cv_path")
    if letter_text and not chat.get("letter_text"):
        chat["letter_text"] = letter_text
        chat["letter_path"] = gen.get("letter_path")
    elif letter_text:
        if gen.get("letter_path") and gen.get("letter_path") != chat.get("letter_path"):
            chat["letter_text"] = letter_text
            chat["letter_path"] = gen.get("letter_path")
    if chat.get("active_doc") not in {"cv", "letter"}:
        chat["active_doc"] = "cv"
    if not chat.get("cv_text") and chat.get("letter_text"):
        chat["active_doc"] = "letter"
    if gen.get("model"):
        chat["last_model"] = gen.get("model") or chat.get("last_model") or ""


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
    chat_error: str | None = None,
    models: list[str] | None = None,
):
    session = _ensure_session(sid)
    _sync_chat_from_generation(session)
    settings = session.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    chat = session.get("chat") or {}
    active_doc = chat.get("active_doc") if chat.get("active_doc") in {"cv", "letter"} else "cv"
    active_text = chat.get("cv_text") if active_doc == "cv" else chat.get("letter_text")
    active_path = chat.get("cv_path") if active_doc == "cv" else chat.get("letter_path")
    context = {
        "request": request,
        "job": _doc_context(session.get("job")),
        "cv": _doc_context(session.get("cv")),
        "job_display": _doc_display_name(session.get("job")),
        "cv_display": _doc_display_name(session.get("cv")),
        "samples": _docs_context(session.get("samples") or []),
        "job_error": job_error,
        "cv_error": cv_error,
        "samples_error": samples_error,
        "generate_error": generate_error or (session.get("generation_job") or {}).get("error"),
        "chat_error": chat_error or chat.get("error"),
        "generation": session.get("generation"),
        "generation_job": session.get("generation_job"),
        "chat": {
            "messages": chat.get("messages") or [],
            "active_doc": active_doc,
            "active_text": active_text or "",
            "active_path": active_path,
            "cv_text": chat.get("cv_text") or "",
            "letter_text": chat.get("letter_text") or "",
            "cv_path": chat.get("cv_path"),
            "letter_path": chat.get("letter_path"),
        },
        "models": models if models is not None else list_models(),
        "settings": {
            "model": str(settings.get("model") or ""),
            "output_dir": str(settings.get("output_dir") or ""),
        },
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


def _doc_display_name(doc: Any) -> str:
    if not doc:
        return ""
    filename = getattr(doc, "filename", None) or (doc.get("filename") if isinstance(doc, dict) else None)
    source = getattr(doc, "source", "") or (doc.get("source") if isinstance(doc, dict) else "")
    name = filename or source or ""
    if name.startswith("local file: "):
        name = name[len("local file: ") :]
    name = str(name)
    return name if len(name) <= 40 else name[:37] + "..."


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/pick/folder")
async def pick_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "path": None,
                "error": (
                    "Folder picker unavailable: tkinter is not installed or not configured "
                    f"({exc}). Enter the path manually."
                ),
            },
            status_code=501,
        )

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
    # Remember chosen generation settings between sessions.
    session["settings"] = {
        "model": model.strip(),
        "output_dir": output_dir.strip(),
    }
    save_persisted_settings(model=model, output_dir=output_dir)
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
    if job.get("status") == "completed":
        _sync_chat_from_generation(session)
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
    return _render_index(
        request,
        sid=sid,
        set_cookie=set_cookie,
        generate_error="Generation is started from the UI with progress tracking. Please use the generation buttons.",
    )


@app.get("/generate")
async def generate_get():
    return RedirectResponse(url="/", status_code=303)


@app.post("/chat/send", response_class=HTMLResponse)
async def chat_send(
    request: Request,
    message: str = Form(default=""),
    active_doc: str = Form(default="cv"),
    model: str = Form(default=""),
    output_dir: str = Form(default=""),
):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    _sync_chat_from_generation(session)
    chat = session.get("chat") or {}
    chat["error"] = None
    doc = "letter" if (active_doc or "").strip().lower() == "letter" else "cv"
    chat["active_doc"] = doc
    settings = session.get("settings") or {}
    model_sel = (model or settings.get("model") or chat.get("last_model") or "").strip()
    out_dir_sel = (output_dir or settings.get("output_dir") or "").strip()
    msg = (message or "").strip()
    try:
        if not msg:
            raise ValueError("Enter a message to request a revision.")
        current_text = chat.get("cv_text") if doc == "cv" else chat.get("letter_text")
        if not (current_text or "").strip():
            raise ValueError("Generate the selected document first before requesting revisions.")
        # Persist remembered settings if provided.
        if model_sel or out_dir_sel:
            session["settings"] = {
                "model": model_sel or str(settings.get("model") or ""),
                "output_dir": out_dir_sel or str(settings.get("output_dir") or ""),
            }
            save_persisted_settings(model=session["settings"]["model"], output_dir=session["settings"]["output_dir"])
        history = list(chat.get("messages") or [])
        result = await revise_document(
            model=model_sel,
            output_dir=out_dir_sel,
            kind=doc,
            current_text=str(current_text),
            user_request=msg,
            chat_history=history,
        )
        history.append({"role": "user", "content": msg})
        doc_label = "Customized CV" if doc == "cv" else "Motivation letter"
        history.append({"role": "assistant", "content": f"Revised {doc_label} saved to: {result.path}"})
        chat["messages"] = history[-40:]
        if doc == "cv":
            chat["cv_text"] = result.text
            chat["cv_path"] = result.path
        else:
            chat["letter_text"] = result.text
            chat["letter_path"] = result.path
        chat["last_model"] = result.model
        chat["error"] = None
    except Exception as exc:  # noqa: BLE001
        chat["error"] = str(exc)
    return _render_index(request, sid=sid, set_cookie=set_cookie)


@app.get("/chat/send")
async def chat_send_get():
    return RedirectResponse(url="/", status_code=303)


@app.get("/load/job")
async def load_job_get():
    return RedirectResponse(url="/", status_code=303)


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


@app.post("/load/job/preview")
async def load_job_preview(
    request: Request,
    job_url: str = Form(default=""),
    job_file: UploadFile | None = File(default=None),
):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    try:
        doc = await load_document(url=job_url, upload=job_file, label="Job ad")
        session["job_preview"] = doc
        payload = {"ok": True, "doc": asdict(doc), "display_name": _doc_display_name(doc)}
        resp = JSONResponse(payload)
    except Exception as exc:  # noqa: BLE001
        resp = JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.post("/load/job/confirm")
async def load_job_confirm(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    preview = session.get("job_preview")
    if preview is None:
        resp = JSONResponse({"ok": False, "error": "No preview to confirm."}, status_code=400)
    else:
        session["job"] = preview
        session["job_preview"] = None
        save_session_context(session)
        resp = JSONResponse({"ok": True, "doc": _doc_context(session["job"]), "display_name": _doc_display_name(session["job"])})
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.post("/load/job/cancel")
async def load_job_cancel(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    session["job_preview"] = None
    resp = JSONResponse({"ok": True})
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.post("/load/job/remove")
async def load_job_remove(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    session["job"] = None
    session["job_preview"] = None
    save_session_context(session)
    resp = JSONResponse({"ok": True})
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.get("/load/cv")
async def load_cv_get():
    return RedirectResponse(url="/", status_code=303)


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


@app.post("/load/cv/preview")
async def load_cv_preview(
    request: Request,
    cv_url: str = Form(default=""),
    cv_file: UploadFile | None = File(default=None),
):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    try:
        doc = await load_document(url=cv_url, upload=cv_file, label="CV")
        session["cv_preview"] = doc
        payload = {"ok": True, "doc": asdict(doc), "display_name": _doc_display_name(doc)}
        resp = JSONResponse(payload)
    except Exception as exc:  # noqa: BLE001
        resp = JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.post("/load/cv/confirm")
async def load_cv_confirm(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    preview = session.get("cv_preview")
    if preview is None:
        resp = JSONResponse({"ok": False, "error": "No preview to confirm."}, status_code=400)
    else:
        session["cv"] = preview
        session["cv_preview"] = None
        save_session_context(session)
        resp = JSONResponse({"ok": True, "doc": _doc_context(session["cv"]), "display_name": _doc_display_name(session["cv"])})
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.post("/load/cv/cancel")
async def load_cv_cancel(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    session["cv_preview"] = None
    resp = JSONResponse({"ok": True})
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.post("/load/cv/remove")
async def load_cv_remove(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    session["cv"] = None
    session["cv_preview"] = None
    save_session_context(session)
    resp = JSONResponse({"ok": True})
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp


@app.get("/load/samples")
async def load_samples_get():
    return RedirectResponse(url="/", status_code=303)


@app.post("/load/samples")
async def load_samples(
    request: Request,
    samples_urls: str = Form(default=""),
    samples_folder: str = Form(default=""),
):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    samples_urls_clean = (samples_urls or "").strip()
    samples_folder_clean = (samples_folder or "").strip()

    wants_json = "application/json" in (request.headers.get("accept") or "") or request.headers.get("x-requested-with") == "fetch"

    def _resp(payload: dict[str, Any], status_code: int = 200):
        if wants_json:
            resp = JSONResponse(payload, status_code=status_code)
        else:
            # Fallback for legacy/non-JS form posts
            if status_code >= 400:
                resp = _render_index(request, sid=sid, set_cookie=set_cookie, samples_error=payload.get("error"))
            else:
                resp = _render_index(request, sid=sid, set_cookie=set_cookie)
        if set_cookie:
            resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
        return resp

    try:
        if samples_folder_clean and samples_urls_clean:
            raise ValueError("Provide either a local folder or URL(s), not both.")
        if not samples_folder_clean and not samples_urls_clean:
            raise ValueError("Provide a local folder (use the button) or one or more web URL(s) for writing samples.")

        loaded: list[LoadedDocument] = []
        if samples_folder_clean:
            loaded = await load_documents_from_folder(samples_folder_clean, label_prefix="Writing sample")
        elif samples_urls_clean:
            # Support comma, newline, or whitespace separated URLs
            import re

            urls = re.split(r"[\n,\s]+", samples_urls_clean)
            loaded = await load_documents_from_urls(urls, label_prefix="Writing sample")

        # Replace existing samples when (re)loading via the modal to support adjustment.
        session["samples"] = loaded
        save_session_context(session)
        return _resp({
            "ok": True,
            "count": len(loaded),
            "samples": _docs_context(loaded),
        })
    except Exception as exc:  # noqa: BLE001 - show user-facing load errors
        return _resp({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/load/samples/remove")
async def load_samples_remove(request: Request):
    sid, set_cookie = _get_session_id(request)
    session = _ensure_session(sid)
    session["samples"] = []
    save_session_context(session)
    resp = JSONResponse({"ok": True})
    if set_cookie:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return resp



