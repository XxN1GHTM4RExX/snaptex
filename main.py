import io
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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

@app.get("/")
def read_root():
    return {"message": "SnapTex API is online and healthy!"}

@app.post("/process-document")
async def process_document(
    file: UploadFile = File(...),
    aggressive_whitening: str = Form("false")
):
    try:
        contents = await file.read()
        blur_score = calculate_blur_score(contents)

        # Parse string payload from Streamlit form data into boolean
        is_whitening_enabled = aggressive_whitening.lower() in ["true", "1", "yes"]

        ocr_result = process_image_with_gemini(contents, aggressive_whitening=is_whitening_enabled)

        return {
            "status": "success",
            "blur_score": blur_score,
            "latex": ocr_result.get("latex", ""),
            "text": ocr_result.get("text", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")