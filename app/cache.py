from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.loaders import LoadedDocument

CACHE_DIR = Path(".semiapply_cache")
CONTEXT_DIR = CACHE_DIR / "context"
STATE_FILE = CACHE_DIR / "state.json"
SETTINGS_FILE = CACHE_DIR / "settings.json"


def ensure_cache_dirs() -> None:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _doc_file_content(doc: LoadedDocument) -> str:
    header = f"Label: {doc.label}\nSource: {doc.source}\nType: {doc.kind}\n\n"
    return header + (doc.text or "")


def _clear_generated_context_files() -> None:
    # Remove previous canonical context files to avoid stale files being read.
    if not CONTEXT_DIR.exists():
        return
    for p in CONTEXT_DIR.iterdir():
        if not p.is_file():
            continue
        name = p.name.lower()
        if name == "job_ad.txt" or name == "cv.txt" or name.startswith("writing_sample_") or name == "context_manifest.json":
            try:
                p.unlink()
            except Exception:
                pass


def save_session_context(session: dict[str, Any]) -> dict[str, Any]:
    """Persist loaded job/CV/samples to local cache so they survive restarts and can be used as workspace files.

    Writes canonical filenames in the cache context directory for reliable model/tool access:
      - job_ad.txt
      - cv.txt
      - writing_sample_XX.txt
      - context_manifest.json
    """
    ensure_cache_dirs()
    _clear_generated_context_files()

    # Preserve persisted generation settings when rewriting state.
    existing_settings = load_persisted_settings()
    state: dict[str, Any] = {"job": None, "cv": None, "samples": [], "settings": existing_settings}
    manifest: dict[str, Any] = {"job_ad": None, "cv": None, "writing_samples": []}

    job = session.get("job")
    if isinstance(job, LoadedDocument):
        cache_path = _write_text(CONTEXT_DIR / "job_ad.txt", _doc_file_content(job))
        state["job"] = {**asdict(job), "cache_path": cache_path}
        manifest["job_ad"] = {
            "file": "job_ad.txt",
            "label": job.label,
            "source": job.source,
            "kind": job.kind,
            "filename": job.filename,
        }

    cv = session.get("cv")
    if isinstance(cv, LoadedDocument):
        cache_path = _write_text(CONTEXT_DIR / "cv.txt", _doc_file_content(cv))
        state["cv"] = {**asdict(cv), "cache_path": cache_path}
        manifest["cv"] = {
            "file": "cv.txt",
            "label": cv.label,
            "source": cv.source,
            "kind": cv.kind,
            "filename": cv.filename,
        }

    samples = session.get("samples") or []
    saved_samples = []
    for i, sample in enumerate(samples, start=1):
        if isinstance(sample, LoadedDocument):
            fname = f"writing_sample_{i:02d}.txt"
            cache_path = _write_text(CONTEXT_DIR / fname, _doc_file_content(sample))
            saved_samples.append({**asdict(sample), "cache_path": cache_path})
            manifest["writing_samples"].append(
                {
                    "file": fname,
                    "label": sample.label,
                    "source": sample.source,
                    "kind": sample.kind,
                    "filename": sample.filename,
                }
            )
    state["samples"] = saved_samples
    manifest["workspace_dir"] = str(CONTEXT_DIR)

    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_text(CONTEXT_DIR / "context_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def get_context_manifest() -> dict[str, Any]:
    """Return manifest describing canonical context files in the cache workspace."""
    path = CONTEXT_DIR / "context_manifest.json"
    if not path.exists():
        return {"job_ad": None, "cv": None, "writing_samples": [], "workspace_dir": str(CONTEXT_DIR)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"job_ad": None, "cv": None, "writing_samples": [], "workspace_dir": str(CONTEXT_DIR)}


def _doc_from_state(data: dict[str, Any] | None) -> LoadedDocument | None:
    if not data:
        return None
    try:
        return LoadedDocument(
            label=str(data.get("label", "")),
            source=str(data.get("source", "")),
            kind=str(data.get("kind", "text")),
            filename=data.get("filename"),
            text=str(data.get("text", "")),
        )
    except Exception:
        return None


def load_persisted_settings() -> dict[str, str]:
    """Load persisted generation settings (model, output folder) from cache state."""
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            settings = state.get("settings") or {}
            if isinstance(settings, dict):
                return {
                    "model": str(settings.get("model") or ""),
                    "output_dir": str(settings.get("output_dir") or ""),
                }
        except Exception:
            pass
    # Backward/alternative location
    if SETTINGS_FILE.exists():
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(settings, dict):
                return {
                    "model": str(settings.get("model") or ""),
                    "output_dir": str(settings.get("output_dir") or ""),
                }
        except Exception:
            pass
    return {"model": "", "output_dir": ""}


def save_persisted_settings(model: str = "", output_dir: str = "") -> None:
    """Persist chosen generation model and output folder between sessions."""
    ensure_cache_dirs()
    settings = {
        "model": (model or "").strip(),
        "output_dir": (output_dir or "").strip(),
    }
    state: dict[str, Any] = {"job": None, "cv": None, "samples": [], "settings": settings}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {"job": None, "cv": None, "samples": []}
        except Exception:
            state = {"job": None, "cv": None, "samples": []}
    state["settings"] = settings
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_persisted_context() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"job": None, "cv": None, "samples": [], "settings": load_persisted_settings()}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"job": None, "cv": None, "samples": [], "settings": {"model": "", "output_dir": ""}}
    job = _doc_from_state(state.get("job"))
    cv = _doc_from_state(state.get("cv"))
    samples = []
    for item in state.get("samples") or []:
        doc = _doc_from_state(item)
        if doc:
            samples.append(doc)
    settings = load_persisted_settings() if isinstance(state, dict) else {"model": "", "output_dir": ""}
    if isinstance(state, dict):
        s = state.get("settings") or {}
        if isinstance(s, dict):
            settings = {
                "model": str(s.get("model") or ""),
                "output_dir": str(s.get("output_dir") or ""),
            }
    return {"job": job, "cv": cv, "samples": samples, "settings": settings}


def get_workspace_dir() -> Path:
    ensure_cache_dirs()
    return CONTEXT_DIR
