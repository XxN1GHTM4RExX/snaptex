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

# Enable CORS for Streamlit frontend requests
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

        # Calculate image blur score
        blur_score = calculate_blur_score(contents)

        # Extract LaTeX text using Gemini
        ocr_result = process_image_with_gemini(contents)

        return {
            "status": "success",
            "blur_score": blur_score,
            "latex": ocr_result.get("latex", ""),
            "text": ocr_result.get("text", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


def latex_to_unicode_math(text: str) -> str:
    """Replaces common LaTeX mathematical symbols with clean Unicode representation and strips raw LaTeX tags."""
    # Strip \text{...} wrappers while preserving the inner plain text
    cleaned = re.sub(r'\\text\{([^}]*)\}', r'\1', text)

    replacements = {
        r'\forall': '∀',
        r'\exists': '∃',
        r'\in': '∈',
        r'\notin': '∉',
        r'\subset': '⊂',
        r'\subseteq': '⊆',
        r'\le': '≤',
        r'\ge': '≥',
        r'\neq': '≠',
        r'\iff': '⇔',
        r'\implies': '⇒',
        r'\rightarrow': '→',
        r'\longrightarrow': '⟶',
        r'\times': '×',
        r'\mathbb{R}^+': 'ℝ⁺',
        r'\mathbb{R}': 'ℝ',
        r'\mathbb{N}': 'ℕ',
        r'\mathbb{Z}': 'ℤ',
        r'\quad': '    ',
        r'\qquad': '        ',
        r'\max': 'max',
    }
    for latex_pattern, unicode_char in replacements.items():
        cleaned = cleaned.replace(latex_pattern, unicode_char)

    # Strip remaining math delimiters and raw inline markdown tags
    cleaned = cleaned.replace('$$', '').replace('$', '').replace('**', '')
    return cleaned


@app.post("/export-docx")
async def export_docx(payload: ExportRequest):
    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # Attempt 1: Pandoc conversion
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

    # Attempt 2: Clean python-docx document builder
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

        doc.add_paragraph()  # Blank spacing line

        # Parse text line by line
        lines = payload.latex.split('\n')
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped == '---':
                continue

            # Strip Markdown Heading tags dynamically
            if stripped.startswith('#### '):
                heading_text = latex_to_unicode_math(stripped.replace('#### ', ''))
                h = doc.add_heading(heading_text, level=3)
                h.style.font.name = 'Calibri'
            elif stripped.startswith('### '):
                heading_text = latex_to_unicode_math(stripped.replace('### ', ''))
                h = doc.add_heading(heading_text, level=2)
                h.style.font.name = 'Calibri'
            elif stripped.startswith('## '):
                heading_text = latex_to_unicode_math(stripped.replace('## ', ''))
                h = doc.add_heading(heading_text, level=1)
                h.style.font.name = 'Calibri'

            # Center-aligned display math equations ($$ ... $$)
            elif stripped.startswith('$$') or stripped.endswith('$$'):
                math_line = latex_to_unicode_math(stripped)
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(math_line)
                run.font.name = 'Cambria Math'
                run.font.size = Pt(12)
                run.font.bold = True
                run.font.color.rgb = RGBColor(0, 51, 102)

            # Standard body paragraphs
            else:
                clean_text = latex_to_unicode_math(stripped)
                p = doc.add_paragraph(clean_text)
                p.style.font.name = 'Calibri'
                p.style.font.size = Pt(11)

        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return Response(content=file_stream.getvalue(), media_type=DOCX_MIME)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX export failed: {str(e)}")