import io
import os
import re
import tempfile
from typing import List
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
from database import (
    save_transcription,
    fetch_recent_transcriptions,
    get_supabase_client,
    update_transcription_filename,
    update_transcription_content
)

app = FastAPI(title="SnapTex API", version="1.5")

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


class UpdateTranscriptionRequest(BaseModel):
    markdown_content: str
    filename: str | None = None


class ExportDocxRequest(BaseModel):
    title: str = "SnapTex_Document"
    markdown_content: str


class AIAssistRequest(BaseModel):
    full_markdown: str
    active_page_content: str | None = None
    active_page_number: int | None = 1
    user_prompt: str
    mode: str = "explain"  # "fix_ocr", "explain", "exercise", "solution"


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
        bitmap = page.render(scale=2.5)
        pil_image = bitmap.to_pil()
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        page_images.append(buf.getvalue())
        page.close()

    pdf.close()
    return page_images


@app.get("/")
def read_root():
    return {"message": "SnapTex API (Batch OCR + Native DOCX Export + Surgical AI Copilot) is online and healthy!"}


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

        stitched_latex_parts: List[str] = []
        stitched_text_parts: List[str] = []
        blur_scores: List[float] = []

        for idx, img_bytes in enumerate(page_buffers, start=1):
            score = calculate_blur_score(img_bytes)
            blur_scores.append(score)

            ocr_result = process_image_with_gemini(img_bytes, aggressive_whitening=is_whitening_enabled)
            page_latex = (ocr_result.get("latex") or "").strip()
            page_text = (ocr_result.get("text") or "").strip()

            if len(page_buffers) > 1:
                stitched_latex_parts.append(f"## Page {idx}\n\n{page_latex}")
                stitched_text_parts.append(f"--- Page {idx} ---\n{page_text}")
            else:
                stitched_latex_parts.append(page_latex)
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
            "page_count": len(page_buffers),
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
    """Surgical AI Copilot endpoint with page context, solution file generation, and structured JSON output."""
    verify_token(authorization)

    try:
        from google import genai

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        system_instruction = (
            "You are SnapTex Copilot, an expert university-level STEM assistant. "
            "You help students audit math/physics proofs, fix OCR LaTeX errors, generate practice exercises, "
            "and produce complete step-by-step solution documents. "
            "You must return a valid JSON response with keys: "
            "'explanation' (concise summary or explanation in Markdown with KaTeX math), "
            "'suggested_patch' (corrected markdown snippet when editing a tagged line, or null), "
            "'solution_title' (if mode is 'solution', a clean title like 'Solution - <Topic>', else null), and "
            "'solution_markdown' (if mode is 'solution', the complete, rigorous step-by-step worked solution "
            "formatted in Markdown with $...$ and $$...$$ KaTeX math and '---' between pages/sections, else null)."
        )

        context_prompt = (
            f"Mode: {payload.mode}\n"
            f"Active Page Number: {payload.active_page_number}\n"
            f"Active Page Content:\n{payload.active_page_content or payload.full_markdown}\n\n"
            f"Full Document Context:\n{payload.full_markdown}\n\n"
            f"User Request: {payload.user_prompt}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=context_prompt,
            config={
                "system_instruction": system_instruction,
                "response_mime_type": "application/json",
            },
        )

        return {"status": "success", "result": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Copilot failed: {str(e)}")


@app.post("/export-docx")
def export_docx(
    payload: ExportDocxRequest,
    authorization: str = Header(...)
):
    """Converts Markdown + LaTeX into a real Microsoft Word (.docx) file with native math equations."""
    verify_token(authorization)

    safe_title = re.sub(r'[\\/*?:"<>|]', "_", payload.title.strip() or "SnapTex_Document")
    md_content = f"# {payload.title.strip()}\n\n{payload.markdown_content}"

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

        with open(tmp_docx_path, "rb") as f:
            docx_bytes = f.read()

    except Exception as pandoc_err:
        print(f"Pandoc DOCX conversion fallback triggered: {pandoc_err}")
        doc = Document()
        doc.add_heading(payload.title.strip() or "SnapTex Document", level=1)
        for line in payload.markdown_content.splitlines():
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

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.docx"'
        }
    )


@app.get("/history")
def get_history(authorization: str = Header(...)):
    """Returns the 10 most recent transcriptions for the authenticated user."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]
    return {"history": fetch_recent_transcriptions(access_token=token, limit=10)}


@app.put("/history/{transcription_id}")
def update_history_item(
    transcription_id: str,
    payload: UpdateTranscriptionRequest,
    authorization: str = Header(...)
):
    """Persists edited markdown content and title to Supabase."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]

    try:
        updated_record = update_transcription_content(
            transcription_id=transcription_id,
            markdown_content=payload.markdown_content,
            filename=payload.filename,
            access_token=token
        )
        if not updated_record:
            raise HTTPException(status_code=404, detail="Record not found or update failed.")
        return {"status": "success", "data": updated_record}
    except HTTPException:
        raise
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