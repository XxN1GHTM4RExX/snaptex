import io
from fastapi import FastAPI, UploadFile, File, HTTPException
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