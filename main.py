import io
from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pypandoc
from docx import Document
from fastapi import Response, HTTPException
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

        # Calculate image blur score safely
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



@app.post("/export-docx")
async def export_docx(payload: ExportRequest):
    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # 1. Primary Attempt: Use Pandoc with markdown+tex_math_dollars extension
    # This instructs Pandoc to convert $...$ and $$...$$ directly into Word native math (OMML)
    try:
        output_bytes = pypandoc.convert_text(
            payload.latex,
            to='docx',
            format='markdown+tex_math_dollars+raw_tex',
            outputfile=None
        )
        return Response(content=output_bytes, media_type=DOCX_MIME)
    except Exception:
        pass  # Fall back if pandoc fails on specific raw tex blocks

    # 2. Secondary Attempt: Pure LaTeX input format for Pandoc
    try:
        # Wrap in a minimal LaTeX document body for Pandoc parser
        full_tex = f"\\documentclass{{article}}\n\\begin{{document}}\n{payload.latex}\n\\end{{document}}"
        output_bytes = pypandoc.convert_text(
            full_tex,
            to='docx',
            format='latex',
            outputfile=None
        )
        return Response(content=output_bytes, media_type=DOCX_MIME)
    except Exception:
        pass

    # 3. Final Fallback: Styled python-docx document
    try:
        doc = Document()
        doc.add_heading('SnapTex - Transcribed Notes', level=1)

        for line in payload.latex.split('\n'):
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith('$$') or line_str.startswith('\\['):
                # Add math block as centered callout paragraph
                p = doc.add_paragraph()
                p.alignment = 1  # Center alignment
                run = p.add_run(line_str)
                run.font.name = 'Cambria Math'
            else:
                doc.add_paragraph(line_str)

        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return Response(content=file_stream.getvalue(), media_type=DOCX_MIME)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")