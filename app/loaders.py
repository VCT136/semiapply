from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import UploadFile
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".pdf", ".html", ".htm", ".txt", ".text", ".md"}
MAX_FETCH_BYTES = 10 * 1024 * 1024
USER_AGENT = "semiapply/0.1 (+document fetch for local job application assistance)"


@dataclass
class LoadedDocument:
    label: str
    source: str
    kind: str
    filename: str | None
    text: str


def _clean_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # Collapse excessive blank lines while preserving paragraph breaks.
    cleaned: list[str] = []
    blank = 0
    for line in lines:
        if line.strip():
            blank = 0
            cleaned.append(line)
        else:
            blank += 1
            if blank <= 2:
                cleaned.append("")
    return "\n".join(cleaned).strip()


def _kind_from_name(name: str | None, content_type: str | None = None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "application/pdf":
        return "pdf"
    if ct in {"text/html", "application/xhtml+xml"}:
        return "html"
    if ct.startswith("text/"):
        return "text"
    if name:
        ext = Path(name).suffix.lower()
        if ext == ".pdf":
            return "pdf"
        if ext in {".html", ".htm"}:
            return "html"
        if ext in {".txt", ".text", ".md"}:
            return "text"
    return "text"


def _extract_text(data: bytes, *, kind: str, source: str) -> str:
    if kind == "pdf":
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n\n".join(parts)
    elif kind == "html":
        soup = BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "canvas"]):
            tag.decompose()
        text = soup.get_text("\n")
    else:
        text = data.decode("utf-8", errors="replace")

    text = _clean_text(text)
    if not text:
        raise ValueError(f"No readable text could be extracted from {source}.")
    return text


async def _load_from_url(url: str, label: str) -> LoadedDocument:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http(s) URLs are supported.")

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.content

    if len(content) > MAX_FETCH_BYTES:
        raise ValueError(f"Fetched content exceeds {MAX_FETCH_BYTES // (1024 * 1024)} MB limit.")

    filename = Path(parsed.path).name or None
    kind = _kind_from_name(filename, response.headers.get("content-type"))
    text = _extract_text(content, kind=kind, source=url)
    return LoadedDocument(label=label, source=url, kind=kind, filename=filename, text=text)


async def _load_from_upload(upload: UploadFile, label: str) -> LoadedDocument:
    filename = upload.filename or "uploaded-file"
    ext = Path(filename).suffix.lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: PDF, HTML, or plain text."
        )

    data = await upload.read()
    if not data:
        raise ValueError("Uploaded file is empty.")
    if len(data) > MAX_FETCH_BYTES:
        raise ValueError(f"Uploaded file exceeds {MAX_FETCH_BYTES // (1024 * 1024)} MB limit.")

    kind = _kind_from_name(filename, upload.content_type)
    text = _extract_text(data, kind=kind, source=filename)
    return LoadedDocument(
        label=label,
        source=f"local file: {filename}",
        kind=kind,
        filename=filename,
        text=text,
    )


async def load_document(
    *, url: str = "", upload: UploadFile | None = None, label: str
) -> LoadedDocument:
    url = (url or "").strip()
    has_upload = upload is not None and bool(upload.filename)

    if url and has_upload:
        raise ValueError("Provide either a URL or a local file, not both.")
    if not url and not has_upload:
        raise ValueError(f"Provide a URL or a local file for {label}.")

    if url:
        return await _load_from_url(url, label)
    assert upload is not None
    return await _load_from_upload(upload, label)


async def load_document_from_path(path: str | Path, label: str) -> LoadedDocument:
    p = Path(path)
    if not p.exists():
        raise ValueError(f"Path does not exist: {p}")
    if not p.is_file():
        raise ValueError(f"Path is not a file: {p}")

    ext = p.suffix.lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: PDF, HTML, or plain text."
        )

    data = p.read_bytes()
    if not data:
        raise ValueError("File is empty.")
    if len(data) > MAX_FETCH_BYTES:
        raise ValueError(f"File exceeds {MAX_FETCH_BYTES // (1024 * 1024)} MB limit.")

    kind = _kind_from_name(p.name)
    text = _extract_text(data, kind=kind, source=str(p))
    return LoadedDocument(
        label=label,
        source=f"local file: {p}",
        filename=p.name,
        kind=kind,
        text=text,
    )


async def load_documents_from_folder(folder_path: str | Path, label_prefix: str = "Writing sample") -> list[LoadedDocument]:
    p = Path(folder_path)
    if not p.exists():
        raise ValueError(f"Folder does not exist: {p}")
    if not p.is_dir():
        raise ValueError(f"Path is not a folder: {p}")

    docs: list[LoadedDocument] = []
    # Load all supported files in the folder (non-recursive as a simple default)
    for entry in sorted(p.iterdir()):
        if entry.is_file():
            ext = entry.suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                try:
                    doc = await load_document_from_path(entry, label=f"{label_prefix}: {entry.name}")
                    docs.append(doc)
                except Exception:
                    # Skip files that fail to load/extract; continue with others
                    continue
    if not docs:
        raise ValueError("No supported readable files found in the folder.")
    return docs

async def load_documents_from_uploads(uploads: list[UploadFile], label_prefix: str = "Writing sample") -> list[LoadedDocument]:
    docs: list[LoadedDocument] = []
    for idx, upload in enumerate(uploads, start=1):
        if not upload or not upload.filename:
            continue
        try:
            doc = await _load_from_upload(upload, label=f"{label_prefix}: {Path(upload.filename).name}")
            docs.append(doc)
        except Exception:
            continue
    if not docs:
        raise ValueError("No supported readable files could be loaded from the selected folder/files.")
    return docs

async def load_documents_from_urls(urls: list[str], label_prefix: str = "Writing sample") -> list[LoadedDocument]:
    docs: list[LoadedDocument] = []
    for idx, url in enumerate(urls, start=1):
        url_clean = (url or "").strip()
        if not url_clean:
            continue
        try:
            doc = await _load_from_url(url_clean, label=f"{label_prefix} {idx}")
            docs.append(doc)
        except Exception:
            continue
    if not docs:
        raise ValueError("No valid writing samples could be loaded from the provided URL(s).")
    return docs

