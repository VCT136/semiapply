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
