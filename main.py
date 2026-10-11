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

        # Extract LaTeX text using Gemini (uses multi-key rotation engine)
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
    """Replaces LaTeX symbols, operators, and formatting tags with clean Unicode text."""
    if not text:
        return ""

    # 1. Strip \text{...}, \mathrm{...}, and \mathbf{...} wrappers
    cleaned = re.sub(r'\\(?:text|mathrm|mathbf)\{([^}]*)\}', r'\1', text)

    # 2. Comprehensive symbol mapping (handles both lowercase and capitalized variants)
    replacements = {
        # Implication & Arrows
        r'\Longrightarrow': '⟹',
        r'\Longleftrightarrow': '⟺',
        r'\implies': '⟹',
        r'\Implies': '⟹',
        r'\iff': '⇔',
        r'\longrightarrow': '⟶',
        r'\rightarrow': '→',
        r'\to': '→',

        # Quantifiers & Set Theory
        r'\forall': '∀',
        r'\exists': '∃',
        r'\in': '∈',
        r'\notin': '∉',
        r'\subset': '⊂',
        r'\subseteq': '⊆',
        r'\cap': '∩',
        r'\cup': '∪',

        # Operations & Relations
        r'\le': '≤',
        r'\leq': '≤',
        r'\ge': '≥',
        r'\geq': '≥',
        r'\neq': '≠',
        r'\approx': '≈',
        r'\wedge': '∧',
        r'\vee': '∨',
        r'\times': '×',
        r'\div': '÷',
        r'\pm': '±',

        # Dots & Spacing
        r'\dots': '…',
        r'\ldots': '…',
        r'\cdots': '⋯',
        r'\quad': ' ',
        r'\qquad': ' ',
        r'\hfill': ' ',

        # Product, Sum & Calculus Operators
        r'\prod': '∏',
        r'\sum': '∑',
        r'\int': '∫',

        # Blackboard Bold Sets
        r'\mathbb{R}^+': 'ℝ⁺',
        r'\mathbb{R}': 'ℝ',
        r'\mathbb{N}': 'ℕ',
        r'\mathbb{Z}': 'ℤ',
        r'\mathbb{Q}': 'ℚ',
        r'\mathbb{C}': 'ℂ',

        # Common Functions
        r'\max': 'max',
        r'\min': 'min',
        r'\lim': 'lim',
        r'\log': 'log',
        r'\ln': 'ln',

        # Greek Letters
        r'\alpha': 'α',
        r'\beta': 'β',
        r'\gamma': 'γ',
        r'\delta': 'δ',
        r'\epsilon': 'ε',
        r'\theta': 'θ',
        r'\lambda': 'λ',
        r'\pi': 'π',
        r'\sigma': 'σ',
        r'\omega': 'ω',
        r'\Delta': 'Δ',
    }

    # Apply symbol replacements
    for latex_pattern, unicode_char in replacements.items():
        cleaned = cleaned.replace(latex_pattern, unicode_char)

    # 3. Clean up LaTeX formatting syntax (braces, powers, subscripts)
    cleaned = re.sub(r'_\{([^}]*)\}', r'_\1', cleaned)
    cleaned = re.sub(r'\^\{([^}]*)\}', r'^\1', cleaned)

    # Convert common digit/letter subscripts
    subscripts = {'0':'₀', '1':'₁', '2':'₂', '3':'₃', '4':'₄', '5':'₅', '6':'₆', '7':'₇', '8':'₈', '9':'₉', 'i':'ᵢ', 'j':'ⱼ', 'n':'ₙ', 'k':'ₖ'}
    for digit, sub in subscripts.items():
        cleaned = cleaned.replace(f'_{digit}', sub)

    # Convert common superscripts
    superscripts = {'0':'⁰', '1':'¹', '2':'²', '3':'³', '4':'⁴', '5':'⁵', '6':'⁶', '7':'⁷', '8':'⁸', '9':'⁹', 'n':'ⁿ', '+':'⁺', '-':'⁻'}
    for char, sup in superscripts.items():
        cleaned = cleaned.replace(f'^{char}', sup)

    # Clean up remaining LaTeX slash artifacts and math delimiters
    cleaned = re.sub(r'\\([{}_\^\#\&])', r'\1', cleaned)
    cleaned = cleaned.replace('$$', '').replace('$', '').replace('**', '').replace('\\', '')

    return cleaned.strip()


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