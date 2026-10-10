import io
from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pypandoc
from docx import Document

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

    # Attempt 1: Pandoc Conversion
    try:
        output_bytes = pypandoc.convert_text(
            payload.latex,
            to='docx',
            format='markdown',
            outputfile=None
        )
        return Response(content=output_bytes, media_type=DOCX_MIME)
    except Exception:
        pass  # If pandoc fails or binary missing, proceed to pure Python fallback

    # Attempt 2: Pure python-docx document builder (Guaranteed Success)
    try:
        doc = Document()
        doc.add_heading('SnapTex - Extracted LaTeX & Notes', level=1)

        # Write lines to docx
        for line in payload.latex.split('\n'):
            if line.strip():
                doc.add_paragraph(line)

        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return Response(content=file_stream.getvalue(), media_type=DOCX_MIME)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")