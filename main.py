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


def clean_fallback_text(text: str) -> str:
    """Strips Markdown asterisks, carets, and converts basic LaTeX to clean text for fallback export."""
    if not text:
        return ""

    # Remove \text{...} wrappers
    cleaned = re.sub(r'\\text\{([^}]*)\}', r'\1', text)

    # Basic LaTeX symbol replacements
    replacements = {
        r'\forall': '∀', r'\exists': '∃', r'\in': '∈', r'\notin': '∉',
        r'\mathbb{Z}': 'ℤ', r'\mathbb{N}': 'ℕ', r'\mathbb{R}': 'ℝ',
        r'\Longrightarrow': '⟹', r'\implies': '⟹', r'\wedge': '∧',
        r'\vee': '∨', r'\geq': '≥', r'\leq': '≤', r'\dots': '…',
        r'\prod': '∏', r'\sum': '∑', r'\times': '×',
        r'\alpha': 'α', r'\beta': 'β', r'\delta': 'δ', r'\gamma': 'γ'
    }

    for pattern, replacement in replacements.items():
        cleaned = cleaned.replace(pattern, replacement)

    # Convert subscript patterns (_1 -> ₁, _i -> ᵢ)
    subscripts = {'0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
                  'i': 'ᵢ', 'j': 'ⱼ', 'n': 'ₙ', 'k': 'ₖ'}
    for digit, sub in subscripts.items():
        cleaned = cleaned.replace(f'_{digit}', sub)

    # Convert superscript patterns (^1 -> ¹, ^2 -> ²)
    superscripts = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
                    'n': 'ⁿ'}
    for char, sup in superscripts.items():
        cleaned = cleaned.replace(f'^{char}', sup)

    # Strip markdown artifacts (*, **, $, caret parentheses)
    cleaned = cleaned.replace('**', '').replace('*', '').replace('$', '')
    cleaned = re.sub(r'\^\(([^)]+)\)', r'⁽\1⁾', cleaned)
    cleaned = re.sub(r'\\([{}])', r'\1', cleaned)

    return cleaned.strip()


@app.post("/export-docx")
async def export_docx(payload: ExportRequest):
    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # Attempt 1: Pandoc conversion (Generates native Word equations)
    try:
        output_bytes = pypandoc.convert_text(
            payload.latex,
            to='docx',
            format='markdown+tex_math_dollars',
            outputfile=None
        )
        return Response(content=output_bytes, media_type=DOCX_MIME)
    except Exception as e:
        print(f"Pandoc fallback notice: {str(e)}")

    # Attempt 2: Clean python-docx fallback (Strips all markdown/caret noise)
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
            if stripped.startswith('##') or stripped.startswith('Théorème') or stripped.startswith(
                    'Définition') or stripped.startswith('Proposition') or stripped.startswith(
                    'Exercice') or stripped.startswith('Corollaire'):
                clean_text = clean_fallback_text(stripped)
                p = doc.add_paragraph()
                run = p.add_run(clean_text)
                run.bold = True
                run.font.name = 'Calibri'
                run.font.size = Pt(12)
                run.font.color.rgb = RGBColor(0, 51, 102)

            # Display Equations ($$ ... $$)
            elif stripped.startswith('$$') or stripped.endswith('$$'):
                clean_eq = clean_fallback_text(stripped)
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(clean_eq)
                run.font.name = 'Cambria Math'
                run.font.size = Pt(12)
                run.font.bold = True

            # Standard Paragraphs
            else:
                clean_text = clean_fallback_text(stripped)
                p = doc.add_paragraph(clean_text)
                p.style.font.name = 'Calibri'
                p.style.font.size = Pt(11)

        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return Response(content=file_stream.getvalue(), media_type=DOCX_MIME)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX export failed: {str(e)}")