import io
import re
from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pypandoc
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from ocr_engine import process_image_with_gemini
from blur_detector import calculate_blur_score

app = FastAPI(title="SnapTex API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExportRequest(BaseModel):
    latex: str


@app.get("/")
def read_root():
    return {"message": "SnapTex API is online and healthy!"}


@app.post("/process-document")
async def process_document(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        blur_score = calculate_blur_score(contents)
        ocr_result = process_image_with_gemini(contents)

        return {
            "status": "success",
            "blur_score": blur_score,
            "latex": ocr_result.get("latex", ""),
            "text": ocr_result.get("text", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


def clean_markdown_and_latex(text: str) -> str:
    """Strips Markdown bold syntax, converts basic LaTeX symbols to Unicode, and removes inline math delimiters ($)."""
    if not text:
        return ""

    # Remove \text{...} wrappers
    cleaned = re.sub(r'\\text\{([^}]*)\}', r'\1', text)

    # Basic symbol mappings
    replacements = {
        r'\forall': '∀',
        r'\exists': '∃',
        r'\in': '∈',
        r'\notin': '∉',
        r'\mathbb{Z}': 'ℤ',
        r'\mathbb{N}': 'ℕ',
        r'\mathbb{R}': 'ℝ',
        r'\Longrightarrow': '⟹',
        r'\Longrightarrow': '⟹',
        r'\implies': '⟹',
        r'\wedge': '∧',
        r'\vee': '∨',
        r'\geq': '≥',
        r'\geq ': '≥ ',
        r'\leq': '≤',
        r'\dots': '…',
    }

    for pattern, replacement in replacements.items():
        cleaned = cleaned.replace(pattern, replacement)

    # Strip bold markdown (**), math delimiters ($), and excess braces
    cleaned = cleaned.replace('**', '').replace('$', '')
    cleaned = re.sub(r'\\([{}])', r'\1', cleaned)

    return cleaned.strip()


@app.post("/export-docx")
async def export_docx(payload: ExportRequest):
    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # Attempt 1: Pandoc (If installed)
    try:
        output_bytes = pypandoc.convert_text(
            payload.latex,
            to='docx',
            format='markdown+tex_math_dollars',
            outputfile=None
        )
        return Response(content=output_bytes, media_type=DOCX_MIME)
    except Exception:
        pass

    # Attempt 2: Clean python-docx formatter (Guaranteed readable Word export)
    try:
        doc = Document()

        # Document Header
        title = doc.add_heading('SnapTex - Transcribed Notes', level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        p_sub = doc.add_paragraph()
        p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_sub = p_sub.add_run('Generated automatically via SnapTex OCR Engine')
        run_sub.font.italic = True
        run_sub.font.size = Pt(9)
        run_sub.font.color.rgb = RGBColor(128, 128, 128)

        doc.add_paragraph()

        lines = payload.latex.split('\n')
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped == '---':
                continue

            # Headings
            if stripped.startswith('##') or stripped.startswith('**Théorème') or stripped.startswith(
                    '**Définition') or stripped.startswith('**Proposition') or stripped.startswith(
                    '**Exercice') or stripped.startswith('**Corollaire'):
                clean_text = clean_markdown_and_latex(stripped)
                p = doc.add_paragraph()
                run = p.add_run(clean_text)
                run.bold = True
                run.font.name = 'Calibri'
                run.font.size = Pt(12)
                run.font.color.rgb = RGBColor(0, 51, 102)

            # Display Equations ($$ ... $$)
            elif stripped.startswith('$$') or stripped.endswith('$$'):
                clean_eq = clean_markdown_and_latex(stripped)
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(clean_eq)
                run.font.name = 'Cambria Math'
                run.font.size = Pt(12)
                run.font.bold = True

            # Standard Paragraphs
            else:
                clean_text = clean_markdown_and_latex(stripped)
                p = doc.add_paragraph(clean_text)
                p.style.font.name = 'Calibri'
                p.style.font.size = Pt(11)

        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return Response(content=file_stream.getvalue(), media_type=DOCX_MIME)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX export failed: {str(e)}")