import asyncio
import gc
import io
import json
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import create_client
import pypdfium2 as pdfium
import pypandoc
from docx import Document

from ocr_engine import process_image_with_gemini
from blur_detector import calculate_blur_score
from key_manager import provider_manager
from exporter import apply_table_borders
from table_export import html_tables_to_grid_markdown, normalize_html_tables
from database import (
    save_transcription,
    fetch_recent_transcriptions,
    get_supabase_client,
    count_recent_uploads,
    update_transcription_filename,
    update_transcription_content
)

app = FastAPI(title="SnapTex API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

MAX_PAGES = 5
MAX_CONCURRENT_PAGES = 2
DAILY_UPLOAD_LIMIT = 5  # successful transcriptions per rolling 24 h, per user


class UpdateTranscriptionRequest(BaseModel):
    markdown_content: str
    filename: str | None = None


class CreateTranscriptionRequest(BaseModel):
    markdown_content: str
    filename: str = "SnapTex_Document"


class ExportDocumentRequest(BaseModel):
    title: str = "SnapTex_Document"
    markdown_content: str
    format: str = "docx"  # "docx", "pdf", "tex"


class AIAssistRequest(BaseModel):
    full_markdown: str
    active_page_content: str | None = None
    active_page_number: int | None = 1
    user_prompt: str
    mode: str = "explain"  # "fix_ocr", "explain", "exercise", "solution"
    language: str = "en"   # "en" or "fr"


def verify_token(authorization: str = Header(...)):
    """Extracts and verifies the user JWT token from the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    token = authorization.split("Bearer ")[1]

    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token or user session expired.")
        return {"token": token, "user_id": user_response.user.id}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")


def pdf_bytes_to_png_pages(pdf_bytes: bytes, max_pages: int = MAX_PAGES) -> List[bytes]:
    """Renders up to `max_pages` of a PDF into high-res PNG byte buffers."""
    pdf = pdfium.PdfDocument(pdf_bytes)
    total_pages = len(pdf)
    if total_pages > max_pages:
        pdf.close()
        raise HTTPException(
            status_code=400,
            detail=f"PDF has {total_pages} pages. Maximum allowed is {max_pages} pages per upload."
        )

    page_images: List[bytes] = []
    for i in range(total_pages):
        page = pdf[i]
        bitmap = page.render(scale=2.0)
        pil_image = bitmap.to_pil()
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        page_images.append(buf.getvalue())
        pil_image.close()
        page.close()

    pdf.close()
    gc.collect()
    return page_images


def _process_single_page_sync(
    idx: int,
    img_bytes: bytes,
    is_whitening_enabled: bool
) -> Tuple[int, float, str, str]:
    """Runs blur detection + OCR for a single page inside a worker thread and frees memory."""
    try:
        score = calculate_blur_score(img_bytes)
        ocr_result = process_image_with_gemini(img_bytes, aggressive_whitening=is_whitening_enabled)
        page_latex = (ocr_result.get("latex") or "").strip()
        page_text = (ocr_result.get("text") or "").strip()
        return idx, score, page_latex, page_text
    finally:
        gc.collect()


def _universal_latex_markdown_sanitizer(text: str | None) -> str | None:
    """Universally repairs LaTeX control chars, delimiters, un-delimited math lines, and Markdown tables."""
    if not text or not isinstance(text, str):
        return text

    # 0. T9 regression: drop empty table cells and flatten nested list bullets
    #    before any line-level math/table handling sees them.
    text = normalize_html_tables(text)

    # 1. Recover LaTeX commands corrupted by ASCII control chars (\b, \f, \t, \r)
    text = text.replace("\x08", "\\b")
    text = text.replace("\x0c", "\\f")
    text = re.sub(r"\x09(?=[a-zA-Z])", r"\\t", text)
    text = re.sub(r"\x0d(?=[a-zA-Z])", r"\\r", text)

    # 2. Convert \[ ... \] -> $$ ... $$ and \( ... \) -> $ ... $
    text = re.sub(r"\\\[\s*([\s\S]*?)\s*\\\]", r"\n$$\n\1\n$$\n", text)
    text = re.sub(r"\\\(\s*(.*?)\s*\\\)", r"$\1$", text)

    # 3. Repair accidental \left$ / \right$
    text = re.sub(r"\\left\s*\$", r"\\left(", text)
    text = re.sub(r"\\right\s*\$", r"\\right)", text)

    # 4. Ensure horizontal rules and Markdown headings always start on clean lines
    text = re.sub(r"([^\n])\s*---\s*(#{1,4}\s+)", r"\1\n\n---\n\n\2", text)
    text = re.sub(r"([^\n])\s+(#{1,4}\s+)", r"\1\n\n\2", text)

    # 5. Repair collapsed single-line Markdown tables
    text = re.sub(r"\|\s+\|(?=\s*:?-+:?\s*\|)", "|\n|", text)
    text = re.sub(r"(:?-+:?\s*\|)\s+\|", r"\1\n|", text)
    text = re.sub(r"\|\s+\|(?=\s*[^|\n]+\|)", "|\n|", text)

    # 6. Auto-wrap standalone un-delimited LaTeX lines in $$ ... $$ and pad tables with blank lines
    latex_cmd_pattern = re.compile(
        r"\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|lim|begin|end|boxed|iff|implies|equiv|le|ge|neq|approx|in|notin|cup|cap|land|lor|sim|forall|exists|left|right|bigl|bigr|biggl|biggr|ln|log|sin|cos|tan|exp)\b"
    )

    lines = text.splitlines()
    out_lines: List[str] = []
    in_display_math = False
    in_table = False
    in_html_table = False

    for raw_line in lines:
        stripped = raw_line.strip()
        lower = stripped.lower()

        # HTML tables are structural: never rewrite their lines as LaTeX or Markdown.
        if in_html_table:
            out_lines.append(raw_line)
            if "</table>" in lower:
                in_html_table = False
            continue
        if "<table" in lower:
            out_lines.append(raw_line)
            if "</table>" not in lower:
                in_html_table = True
            continue

        if stripped == "$$":
            in_display_math = not in_display_math
            out_lines.append(raw_line)
            continue

        if in_display_math:
            out_lines.append(raw_line)
            continue

        is_table_row = bool(re.match(r"^\s*\|.+\|\s*$", raw_line))
        if is_table_row and not in_table:
            if out_lines and out_lines[-1].strip() != "":
                out_lines.append("")
            in_table = True
        elif not is_table_row and in_table:
            if stripped != "":
                out_lines.append("")
            in_table = False

        if (
            stripped
            and not is_table_row
            and "$" not in stripped
            and not stripped.startswith(("#", "-", "*", ">", "|"))
            and not re.match(r"^\d+[\.\)]\s", stripped)
            and latex_cmd_pattern.search(stripped)
        ):
            prose_words = re.findall(r"\b[a-zA-Z]{4,}\b", re.sub(r"\\[a-zA-Z]+", "", stripped))
            if len(prose_words) <= 3:
                out_lines.extend(["", "$$", stripped, "$$", ""])
                continue

        out_lines.append(raw_line)

    return "\n".join(out_lines)


def _parse_tagged_copilot_output(raw_text: str) -> dict:
    """Parses ===SECTION=== blocks from raw LLM text without JSON backslash escaping bugs."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:markdown|md|text)?\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)

    def _get_section(name: str) -> str | None:
        pattern = rf"==={name}===\s*([\s\S]*?)(?=\n===[A-Z_]+===|\Z)"
        m = re.search(pattern, text)
        if not m:
            return None
        val = m.group(1).strip()
        if not val or val.upper() == "NONE" or val.lower() == "null":
            return None
        return _universal_latex_markdown_sanitizer(val)

    explanation = _get_section("EXPLANATION")
    suggested_patch = _get_section("PATCH")
    solution_title_raw = _get_section("SOLUTION_TITLE")
    solution_markdown = _get_section("SOLUTION_MARKDOWN")

    if not explanation and not suggested_patch and not solution_markdown:
        explanation = _universal_latex_markdown_sanitizer(text)

    solution_title = None
    if solution_title_raw:
        solution_title = solution_title_raw.splitlines()[0].strip().strip("#").strip()

    return {
        "explanation": explanation or "",
        "suggested_patch": suggested_patch,
        "solution_title": solution_title,
        "solution_markdown": solution_markdown,
    }


def run_copilot_with_fallback(system_instruction: str, context_prompt: str) -> str:
    """Uses provider_manager key pools: Gemini -> Groq -> OpenRouter with raw text output."""
    provider_manager.reload_all()
    errors = []

    for _ in range(len(provider_manager.google_pool.keys)):
        g_key = provider_manager.google_pool.get_key()
        if not g_key:
            break
        try:
            from google import genai
            from google.genai.errors import APIError
            client = genai.Client(api_key=g_key, http_options={"timeout": 60000})
            for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-2.5-pro"]:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=context_prompt,
                        config={
                            "system_instruction": system_instruction,
                        },
                    )
                    if response.text:
                        return response.text
                except APIError as e:
                    errors.append(f"Google({model_name}): {e.code}")
                    if e.code == 429 or "quota" in str(e).lower():
                        provider_manager.google_pool.mark_rate_limited(g_key, cooldown_seconds=60)
                        break
        except Exception as e:
            errors.append(f"GoogleClient: {str(e)}")

    for _ in range(len(provider_manager.groq_pool.keys)):
        groq_key = provider_manager.groq_pool.get_key()
        if not groq_key:
            break
        try:
            req_body = json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": context_prompt},
                ],
                "temperature": 0.2,
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=req_body,
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "SnapTex-Backend/2.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            if "429" in str(e):
                provider_manager.groq_pool.mark_rate_limited(groq_key, cooldown_seconds=60)
            errors.append(f"Groq: {str(e)}")

    for _ in range(len(provider_manager.openrouter_pool.keys)):
        or_key = provider_manager.openrouter_pool.get_key()
        if not or_key:
            break
        try:
            req_body = json.dumps({
                "model": "openrouter/free",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": context_prompt},
                ],
                "temperature": 0.2,
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=req_body,
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "SnapTex-Backend/2.0",
                    "HTTP-Referer": "https://snaptex-omega.vercel.app",
                    "X-Title": "SnapTex AI Copilot",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            if "429" in str(e):
                provider_manager.openrouter_pool.mark_rate_limited(or_key, cooldown_seconds=60)
            errors.append(f"OpenRouter: {str(e)}")

    raise RuntimeError(" | ".join(errors) if errors else "No AI provider API keys configured.")


@app.get("/")
def read_root():
    return {"message": "SnapTex API (Batch OCR + Bilingual EN/FR + Multi-Format Export + Pooled AI Copilot) is online!"}


@app.post("/process-document")
async def process_document(
    files: List[UploadFile] = File(...),
    aggressive_whitening: str = Form("false"),
    authorization: str = Header(...)
):
    try:
        auth_data = verify_token(authorization)
        token = auth_data["token"]
        user_id = auth_data["user_id"]

        # T7: fail-open daily cap. Count saved transcriptions from the last 24 h;
        # None from the DB helper means "could not check" -> allow the upload.
        since_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        used = count_recent_uploads(token, user_id, since_iso)
        if used is not None and used >= DAILY_UPLOAD_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Daily upload limit reached ({DAILY_UPLOAD_LIMIT} per 24 hours). "
                    "Please try again tomorrow."
                ),
            )

        if not files:
            raise HTTPException(status_code=400, detail="No files uploaded.")

        is_whitening_enabled = aggressive_whitening.lower() in ["true", "1", "yes"]

        page_buffers: List[bytes] = []
        for upload in files:
            raw_bytes = await upload.read()
            content_type = (upload.content_type or "").lower()
            filename_lower = (upload.filename or "").lower()

            if content_type == "application/pdf" or filename_lower.endswith(".pdf"):
                if len(files) > 1:
                    raise HTTPException(
                        status_code=400,
                        detail="Please upload either 1 PDF (up to 5 pages) or up to 5 images at once."
                    )
                page_buffers.extend(pdf_bytes_to_png_pages(raw_bytes, max_pages=MAX_PAGES))
            else:
                page_buffers.append(raw_bytes)

        if len(page_buffers) > MAX_PAGES:
            raise HTTPException(
                status_code=400,
                detail=f"You uploaded {len(page_buffers)} pages. Maximum allowed is {MAX_PAGES} pages per batch."
            )

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

        async def _bounded_page_task(idx: int, img_bytes: bytes):
            async with semaphore:
                return await asyncio.to_thread(
                    _process_single_page_sync, idx, img_bytes, is_whitening_enabled
                )

        tasks = [
            _bounded_page_task(idx, img_bytes)
            for idx, img_bytes in enumerate(page_buffers, start=1)
        ]
        page_results = await asyncio.gather(*tasks)
        page_results.sort(key=lambda item: item[0])

        page_buffers.clear()
        gc.collect()

        stitched_latex_parts: List[str] = []
        stitched_text_parts: List[str] = []
        blur_scores: List[float] = []

        for idx, score, page_latex, page_text in page_results:
            blur_scores.append(score)
            clean_page_latex = _universal_latex_markdown_sanitizer(page_latex) or ""
            if len(page_results) > 1:
                stitched_latex_parts.append(f"## Page {idx}\n\n{clean_page_latex}")
                stitched_text_parts.append(f"--- Page {idx} ---\n{page_text}")
            else:
                stitched_latex_parts.append(clean_page_latex)
                stitched_text_parts.append(page_text)

        final_latex = "\n\n---\n\n".join(stitched_latex_parts)
        final_text = "\n\n".join(stitched_text_parts)
        avg_blur = round(sum(blur_scores) / len(blur_scores), 2) if blur_scores else 0.0

        primary_name = files[0].filename or "Batch_Document"
        if len(files) > 1:
            base_stem = os.path.splitext(primary_name)[0]
            primary_name = f"{base_stem} (+{len(files) - 1} pages)"

        saved_record = save_transcription(
            filename=primary_name,
            markdown_content=final_latex,
            blur_score=avg_blur,
            whitening_enabled=is_whitening_enabled,
            user_id=user_id,
            access_token=token
        )

        return {
            "status": "success",
            "id": saved_record.get("id"),
            "page_count": len(page_results),
            "blur_score": avg_blur,
            "latex": final_latex,
            "text": final_text
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.post("/ai-assist")
async def ai_assist(
    payload: AIAssistRequest,
    authorization: str = Header(...)
):
    """Surgical AI Copilot endpoint backed by pooled Gemini -> Groq -> OpenRouter."""
    verify_token(authorization)

    try:
        lang_label = "French (Français)" if payload.language.lower().startswith("fr") else "English"
        title_example = "Corrigé - <Sujet>" if lang_label.startswith("French") else "Solution - <Topic>"

        system_instruction = (
            "You are SnapTex Copilot, an expert university-level STEM assistant. "
            "You help students audit math/physics proofs, fix OCR LaTeX errors, generate practice exercises, "
            "and produce complete step-by-step solution documents. "
            f"IMPORTANT: Write ALL natural-language explanations, headings, solution titles, and worked solutions strictly in {lang_label}.\n"
            "CRITICAL KATEX & MARKDOWN RULES:\n"
            "1. Wrap EVERY inline math expression in single dollar signs ($...$) and EVERY standalone display equation on its own lines with $$ on the line before and $$ on the line after.\n"
            "2. NEVER leave raw LaTeX commands (\\frac, \\ln, \\bigl, \\begin{cases}, \\boxed, \\iff, \\infty, etc.) outside $...$ or $$...$$.\n"
            "3. Keep ALL natural-language prose strictly OUTSIDE $...$ delimiters so words are never italicized or merged together.\n"
            "4. Format Markdown tables with a blank line before and after, and put every row on its own newline.\n"
            "5. Output your response using EXACTLY these four section markers (do NOT wrap in JSON):\n\n"
            "===EXPLANATION===\n"
            "<concise summary or explanation in Markdown with $...$ and $$...$$ KaTeX math>\n\n"
            "===PATCH===\n"
            "<corrected markdown snippet when fixing a tagged line, or NONE>\n\n"
            "===SOLUTION_TITLE===\n"
            f"<if mode is 'solution', a clean title like '{title_example}', else NONE>\n\n"
            "===SOLUTION_MARKDOWN===\n"
            "<if mode is 'solution', the complete step-by-step worked solution in Markdown with $...$ and $$...$$ KaTeX math, multi-line Markdown tables, and '\\n\\n---\\n\\n' between sections, else NONE>"
        )

        context_prompt = (
            f"Preferred Response Language: {lang_label}\n"
            f"Mode: {payload.mode}\n"
            f"Active Page Number: {payload.active_page_number}\n"
            f"Active Page Content:\n{payload.active_page_content or payload.full_markdown}\n\n"
            f"Full Document Context:\n{payload.full_markdown}\n\n"
            f"User Request: {payload.user_prompt}"
        )

        raw_output = run_copilot_with_fallback(system_instruction, context_prompt)
        parsed = _parse_tagged_copilot_output(raw_output)

        return {"status": "success", "result": json.dumps(parsed, ensure_ascii=False)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Copilot failed: {str(e)}")


def _build_export_bytes(title: str, markdown_content: str, fmt: str) -> tuple[bytes, str, str]:
    """Converts Markdown + LaTeX into .docx, .tex, or .pdf bytes."""
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title.strip() or "SnapTex_Document")
    md_content = f"# {title.strip()}\n\n{markdown_content}"

    # Pandoc's Markdown reader drops raw HTML, so an HTML table would vanish from
    # the export. Rewrite each one as a grid table so it survives as a real table.
    md_content = html_tables_to_grid_markdown(md_content)

    fmt = fmt.lower().strip()

    if fmt == "tex":
        try:
            tex_body = pypandoc.convert_text(
                md_content,
                "latex",
                format="markdown+tex_math_dollars",
            )
        except Exception:
            tex_body = md_content

        standalone_tex = (
            "\\documentclass[12pt,a4paper]{article}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage[T1]{fontenc}\n"
            "\\usepackage{amsmath,amssymb,amsthm,geometry}\n"
            "\\geometry{margin=1in}\n"
            f"\\title{{{title.strip()}}}\n"
            "\\date{}\n"
            "\\begin{document}\n"
            "\\maketitle\n\n"
            f"{tex_body}\n\n"
            "\\end{document}\n"
        )
        return standalone_tex.encode("utf-8"), "application/x-tex", f"{safe_title}.tex"

    if fmt == "pdf":
        tmp_pdf_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                tmp_pdf_path = tmp_file.name
            pypandoc.convert_text(
                md_content,
                "pdf",
                format="markdown+tex_math_dollars",
                outputfile=tmp_pdf_path,
                extra_args=["--pdf-engine=weasyprint"],
            )
            with open(tmp_pdf_path, "rb") as f:
                return f.read(), "application/pdf", f"{safe_title}.pdf"
        except Exception as pdf_err:
            raise HTTPException(
                status_code=500,
                detail=f"Server PDF engine unavailable ({pdf_err}). Use Print -> Save as PDF or export .docx/.tex."
            )
        finally:
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)

    # Default: .docx
    tmp_docx_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_file:
            tmp_docx_path = tmp_file.name

        pypandoc.convert_text(
            md_content,
            "docx",
            format="markdown+tex_math_dollars",
            outputfile=tmp_docx_path
        )

        # Pandoc emits tables without visible borders; force them in the XML.
        apply_table_borders(tmp_docx_path)

        with open(tmp_docx_path, "rb") as f:
            docx_bytes = f.read()
    except Exception as pandoc_err:
        print(f"Pandoc DOCX conversion fallback triggered: {pandoc_err}")
        doc = Document()
        doc.add_heading(title.strip() or "SnapTex Document", level=1)
        for line in markdown_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                doc.add_heading(stripped[4:], level=3)
            elif stripped.startswith("## "):
                doc.add_heading(stripped[3:], level=2)
            elif stripped.startswith("# "):
                doc.add_heading(stripped[2:], level=1)
            elif stripped:
                doc.add_paragraph(stripped)

        fallback_buf = io.BytesIO()
        doc.save(fallback_buf)
        docx_bytes = fallback_buf.getvalue()
    finally:
        if tmp_docx_path and os.path.exists(tmp_docx_path):
            os.remove(tmp_docx_path)

    return (
        docx_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        f"{safe_title}.docx",
    )


@app.post("/export-document")
def export_document(
    payload: ExportDocumentRequest,
    authorization: str = Header(...)
):
    """Exports document as .docx, .tex, or .pdf."""
    verify_token(authorization)
    file_bytes, media_type, filename = _build_export_bytes(
        payload.title, payload.markdown_content, payload.format
    )
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/export-docx")
def export_docx(
    payload: ExportDocumentRequest,
    authorization: str = Header(...)
):
    """Backward-compatible alias for .docx export."""
    verify_token(authorization)
    file_bytes, media_type, filename = _build_export_bytes(
        payload.title, payload.markdown_content, "docx"
    )
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/history")
def get_history(authorization: str = Header(...)):
    """Returns the 10 most recent transcriptions for the authenticated user."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]
    return {"history": fetch_recent_transcriptions(access_token=token, limit=10)}


@app.post("/history")
def create_history_item(
    payload: CreateTranscriptionRequest,
    authorization: str = Header(...)
):
    """Saves a newly generated document (such as an AI Solution File) to Supabase history."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]
    user_id = auth_data["user_id"]

    try:
        saved_record = save_transcription(
            filename=payload.filename,
            markdown_content=payload.markdown_content,
            blur_score=100.0,
            whitening_enabled=False,
            user_id=user_id,
            access_token=token
        )
        return {"status": "success", "data": saved_record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create history item failed: {str(e)}")


@app.put("/history/{transcription_id}")
def update_history_item(
    transcription_id: str,
    payload: UpdateTranscriptionRequest,
    authorization: str = Header(...)
):
    """Persists edited markdown content and title to Supabase (inserts if record ID is new/missing)."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]
    user_id = auth_data["user_id"]

    try:
        updated_record = None
        if transcription_id and transcription_id not in ("new", "null", "undefined"):
            try:
                updated_record = update_transcription_content(
                    transcription_id=transcription_id,
                    markdown_content=payload.markdown_content,
                    filename=payload.filename,
                    access_token=token
                )
            except Exception:
                updated_record = None

        if not updated_record:
            updated_record = save_transcription(
                filename=payload.filename or "SnapTex_Document",
                markdown_content=payload.markdown_content,
                blur_score=100.0,
                whitening_enabled=False,
                user_id=user_id,
                access_token=token
            )

        return {"status": "success", "data": updated_record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@app.delete("/history/{transcription_id}")
def delete_history_item(transcription_id: str, authorization: str = Header(...)):
    """Deletes a specific transcription row belonging to the authenticated user."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]

    try:
        supabase = get_supabase_client(access_token=token)
        supabase.table("transcriptions").delete().eq("id", transcription_id).execute()
        return {"status": "success", "message": "Record deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deletion failed: {str(e)}")


@app.patch("/history/{transcription_id}")
def rename_history_item(
    transcription_id: str,
    new_filename: str = Query(...),
    authorization: str = Header(...)
):
    """Renames a specific transcription record belonging to the authenticated user."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]

    try:
        updated_record = update_transcription_filename(
            transcription_id=transcription_id,
            new_filename=new_filename,
            access_token=token
        )
        if not updated_record:
            raise HTTPException(status_code=400, detail="Could not update record.")
        return {"status": "success", "data": updated_record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename failed: {str(e)}")