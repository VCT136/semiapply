from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.cache import get_context_manifest, get_workspace_dir, save_session_context


@dataclass
class GenerationResult:
    cv_path: str | None
    letter_path: str | None
    raw_output: str
    model: str
    transcript: str


ProgressCallback = Callable[[str, dict | None], None]


def _run_cmd(args: list[str], timeout: int = 600, cwd: str | Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(cwd) if cwd is not None else None,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def list_models() -> list[str]:
    opencode = shutil.which("opencode")
    if not opencode:
        return []
    try:
        code, out, _err = _run_cmd([opencode, "models"], timeout=30)
    except Exception:
        return []
    if code != 0:
        return []
    models: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith(("DESCRIPTION", "USAGE", "GLOBAL", "FLAGS", "SUBCOMMANDS")):
            continue
        if "/" in line:
            token = line.split()[0]
            if re.match(r"^[\w.\-]+/[\w.\-:#]+$", token):
                models.append(token)
            elif " " not in line:
                models.append(line)
    seen: set[str] = set()
    uniq: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def _unique_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        i = 1
        while target.exists():
            target = target.with_name(f"{stem}_{i}{suffix}")
            i += 1
    return target


def _safe_write(path: Path, content: str) -> Path:
    target = _unique_path(path)
    target.write_text(content, encoding="utf-8")
    return target


def _looks_like_tool_call(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Common case reported: model emits a tool/read request JSON instead of final document text.
    if re.search(r'"(execute|tool|tool_call|toolName|function_call|action)"\s*:', t) and re.search(r'"(path|read_file|file)"\s*:', t):
        return True
    if t.startswith("{") and t.endswith("}") and '"path"' in t and ('"execute"' in t or '"read_file"' in t):
        return True
    return False


def _clean_generated_output(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return ""
    # Strip common accidental wrappers so the file is directly usable as document text.
    fence = re.match(r"^```(?:[\w.-]+)?\n([\s\S]*?)\n```$", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    # Remove legacy delimiter tags if a model includes them anyway.
    for tag in ("CV", "MOTIVATION_LETTER"):
        m = re.match(rf"^<{tag}>\s*([\s\S]*?)\s*</{tag}>$", cleaned, re.IGNORECASE)
        if m:
            cleaned = m.group(1).strip()
    # Remove a single leading/trailing horizontal rule some models add.
    cleaned = re.sub(r"^\s*---+\s*\n", "", cleaned)
    cleaned = re.sub(r"\n\s*---+\s*$", "", cleaned)
    cleaned = cleaned.strip()
    if _looks_like_tool_call(cleaned):
        raise ValueError(
            "Model returned a tool-call/intermediate step instead of final document text. "
            "The run may not have completed to a final answer. Check the CLI transcript for intermediate steps and try again or use a different model/agent configuration."
        )
    return cleaned


def _format_context_manifest(manifest: dict) -> str:
    lines: list[str] = []
    job = manifest.get("job_ad")
    cv = manifest.get("cv")
    samples = manifest.get("writing_samples") or []
    if job and job.get("file"):
        lines.append(f"- Job ad: {job['file']} (label: {job.get('label','')}, source: {job.get('source','')})")
    if cv and cv.get("file"):
        lines.append(f"- CV: {cv['file']} (label: {cv.get('label','')}, source: {cv.get('source','')})")
    if samples:
        for s in samples:
            if s.get("file"):
                lines.append(f"- Writing sample: {s['file']} (label: {s.get('label','')}, source: {s.get('source','')})")
    else:
        lines.append("- Writing samples: (none provided)")
    lines.append("- Manifest: context_manifest.json")
    return "\n".join(lines)


def build_prompt(kind: str, manifest: dict) -> str:
    if kind not in {"cv", "letter"}:
        raise ValueError(f"Unknown generation kind: {kind}")

    parts: list[str] = []
    parts.append(
        "You are assisting a job applicant by creating optimized application materials. "
        "Use only information present in the provided CV and job ad. To better match the applicant's writing style, writing samples may be provided as references. "
        "Do not invent or fabricate skills, dates, employers, titles, education, or achievements. "
        "You may omit irrelevant content, but everything included must be accurate and grounded in the provided materials."
    )
    parts.append("\n## Context files (read from working directory)\n")
    parts.append(
        "The source materials are available as files in the current working directory (local cache workspace). "
        "Read/check them on demand as needed instead of relying on embedded copies.\n"
    )
    parts.append(_format_context_manifest(manifest or {}))

    if kind == "cv":
        parts.append(
            "\n## Task\n"
            "Read the job ad and CV files (and any relevant writing samples if helpful for phrasing/tone). "
            "Generate a customized CV tailored to the job ad, reflecting the applicant's actual experience. "
            "Prioritize and phrase relevant experience to match the role while remaining truthful."
        )
    else:
        parts.append(
            "\n## Task\n"
            "Read the job ad, CV, and writing sample files as needed. "
            "Generate a motivation/cover letter tailored to the job ad. "
            "Match the applicant's writing style and tone where writing samples are provided, while keeping all facts grounded in the CV/job ad."
        )

    parts.append(
        "\n\n## Execution and output requirements\n"
        "- You may use available tools and read files from the working directory to inspect the context files. Intermediate steps are allowed.\n"
        "- However, your FINAL response must be ONLY the complete final document text, ready to be saved and used directly.\n"
        "- Do not include preamble, explanation, commentary, analysis, notes, tool-call JSON, or progress messages in the final response.\n"
        "- Do not wrap the entire final output in markdown code fences.\n"
        "- Use plain text formatting suitable for a .txt document.\n"
    )
    if kind == "cv":
        parts.append("After reading/checking the necessary files, return the complete customized CV as the final answer.")
    else:
        parts.append("After reading/checking the necessary files, return the complete motivation/cover letter as the final answer.")
    return "\n".join(parts)


def _validate_inputs(
    *,
    model: str,
    output_dir: str,
    job_text: str,
    cv_text: str,
    generate_cv: bool,
    generate_letter: bool,
) -> Path:
    if not generate_cv and not generate_letter:
        raise ValueError("Select at least one document to generate (CV and/or motivation letter).")
    if not (model or "").strip():
        raise ValueError("Select a model.")
    if not (output_dir or "").strip():
        raise ValueError("Select an output folder.")
    if not (job_text or "").strip():
        raise ValueError("Load a job ad before generating.")
    if not (cv_text or "").strip():
        raise ValueError("Load a CV before generating.")

    out_dir = Path(output_dir)
    if not out_dir.exists() or not out_dir.is_dir():
        raise ValueError(f"Output folder does not exist or is not a directory: {out_dir}")

    opencode = shutil.which("opencode")
    if not opencode:
        raise ValueError("The 'opencode' CLI was not found. Install OpenCode and ensure it is on PATH.")
    return out_dir


def _format_transcript_entry(
    *,
    kind_label: str,
    model: str,
    prompt: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    cwd: str | Path | None = None,
) -> str:
    cmd = f'opencode run --model "{model}" <prompt>'
    parts = [
        f"=== {kind_label}: command ===",
        cmd,
    ]
    if cwd is not None:
        parts.extend(["", f"=== {kind_label}: working directory ===", str(cwd)])
    parts.extend([
        "",
        f"=== {kind_label}: prompt/input ===",
        prompt,
        "",
        f"=== {kind_label}: stdout ===",
        stdout if stdout.strip() else "(empty)",
        "",
        f"=== {kind_label}: stderr ===",
        stderr if stderr.strip() else "(empty)",
        "",
        f"=== {kind_label}: exit code ===",
        str(exit_code),
    ])
    return "\n".join(parts).rstrip()


async def _run_one(
    *,
    opencode: str,
    model: str,
    prompt: str,
    kind_label: str,
    progress: Callable[[str, dict | None], None],
    cwd: str | Path | None = None,
) -> tuple[str, str]:
    progress(f"{kind_label}: running opencode...", {"kind": kind_label, "stage": "running"})

    def _run() -> tuple[int, str, str]:
        return _run_cmd([opencode, "run", "--model", model.strip(), prompt], timeout=600, cwd=cwd)

    code, stdout, stderr = await asyncio.to_thread(_run)
    transcript = _format_transcript_entry(
        kind_label=kind_label,
        model=model.strip(),
        prompt=prompt,
        stdout=stdout or "",
        stderr=stderr or "",
        exit_code=code,
        cwd=cwd,
    )
    progress(
        f"{kind_label}: command finished (exit {code}).",
        {"kind": kind_label, "stage": "finished", "exit_code": code, "transcript": transcript},
    )
    raw = (stdout or "").strip()
    if code != 0:
        msg = (stderr or stdout or "Unknown error").strip()
        raise ValueError(f"{kind_label} generation failed (opencode exit {code}): {msg[:2000]}")
    cleaned = _clean_generated_output(raw)
    if not cleaned:
        raise ValueError(f"{kind_label} generation produced no usable output.")
    return cleaned, transcript


async def generate_documents(
    *,
    model: str,
    output_dir: str,
    job_text: str,
    cv_text: str,
    samples_texts: list[str],
    generate_cv: bool,
    generate_letter: bool,
    progress_callback: ProgressCallback | None = None,
) -> GenerationResult:
    out_dir = _validate_inputs(
        model=model,
        output_dir=output_dir,
        job_text=job_text,
        cv_text=cv_text,
        generate_cv=generate_cv,
        generate_letter=generate_letter,
    )
    opencode = shutil.which("opencode")
    assert opencode  # validated above

    def progress(msg: str, data: dict | None = None) -> None:
        if progress_callback:
            try:
                progress_callback(msg, data)
            except Exception:
                pass

    workspace_dir = get_workspace_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    cv_path_out: str | None = None
    letter_path_out: str | None = None
    outputs: list[str] = []
    transcripts: list[str] = []

    # Context files/manifest are persisted in the cache workspace (saved by the app before generation).
    progress("Preparing cached context files for generation...")
    manifest = get_context_manifest()
    if generate_cv or generate_letter:
        missing = []
        if not (manifest.get("job_ad") and manifest.get("job_ad", {}).get("file")):
            missing.append("job ad")
        if not (manifest.get("cv") and manifest.get("cv", {}).get("file")):
            missing.append("CV")
        if missing:
            raise ValueError(f"Missing cached context file(s) for: {', '.join(missing)}. Please reload the document(s) and try again.")

    if generate_cv:
        progress("Generating customized CV...")
        prompt = build_prompt("cv", manifest)
        cv_text_out, transcript = await _run_one(
            opencode=opencode, model=model, prompt=prompt, kind_label="Customized CV", progress=progress, cwd=workspace_dir
        )
        transcripts.append(transcript)
        written = _safe_write(out_dir / f"customized-cv-{ts}.txt", cv_text_out)
        cv_path_out = str(written)
        outputs.append(f"=== Customized CV (saved text) ===\n{cv_text_out}")
        progress("Customized CV generated and saved.")

    if generate_letter:
        progress("Generating motivation letter...")
        prompt = build_prompt("letter", manifest)
        letter_text_out, transcript = await _run_one(
            opencode=opencode, model=model, prompt=prompt, kind_label="Motivation letter", progress=progress, cwd=workspace_dir
        )
        transcripts.append(transcript)
        written = _safe_write(out_dir / f"motivation-letter-{ts}.txt", letter_text_out)
        letter_path_out = str(written)
        outputs.append(f"=== Motivation letter (saved text) ===\n{letter_text_out}")
        progress("Motivation letter generated and saved.")

    progress("Generation complete.")
    return GenerationResult(
        cv_path=cv_path_out,
        letter_path=letter_path_out,
        raw_output="\n\n".join(outputs).strip(),
        model=model.strip(),
        transcript="\n\n".join(transcripts).strip(),
    )