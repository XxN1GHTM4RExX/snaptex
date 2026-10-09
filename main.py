from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from blur_detector import is_image_blurry
from ocr_engine import transcribe_document
from exporter import create_docx_from_transcription

app = FastAPI(
    title="SnapTex Backend Engine",
    description="Quality-gated document OCR service using OpenCV and Gemini AI.",
    version="1.0.0"
)


@app.get("/")
def read_root():
    return {"message": "SnapTex API is online."}


@app.post("/process-document")
async def process_document(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    contents = await file.read()

    # Step 1: Quality Gate - Blur Check
    blurry, score = is_image_blurry(contents, threshold=150.0)

    if blurry:
        return {
            "filename": file.filename,
            "blur_score": score,
            "is_blurry": True,
            "status": "rejected",
            "message": "Image is too blurry for accurate OCR. Please upload a clearer photo.",
            "transcription": None
        }

    # Step 2: OCR Pipeline - Gemini
    try:
        transcription = transcribe_document(contents, mime_type=file.content_type)
        return {
            "filename": file.filename,
            "blur_score": score,
            "is_blurry": False,
            "status": "accepted",
            "message": "Document processed successfully.",
            "transcription": transcription
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")


@app.post("/export-docx")
async def export_docx(transcription: str = Form(...), filename: str = Form("SnapTex_Doc")):
    """
    Endpoint that takes transcription text and returns a downloadable .docx file.
    """
    try:
        doc_stream = create_docx_from_transcription(transcription, filename=filename)

        headers = {
            'Content-Disposition': f'attachment; filename="{filename}.docx"'
        }

        return StreamingResponse(
            doc_stream,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate DOCX: {str(e)}")