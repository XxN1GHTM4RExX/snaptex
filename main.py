import io
import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

from ocr_engine import process_image_with_gemini
from blur_detector import calculate_blur_score
from database import save_transcription, fetch_recent_transcriptions

app = FastAPI(title="SnapTex API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


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


@app.get("/")
def read_root():
    return {"message": "SnapTex API is online and healthy!"}


@app.post("/process-document")
async def process_document(
    file: UploadFile = File(...),
    aggressive_whitening: str = Form("false"),
    authorization: str = Header(...)
):
    try:
        auth_data = verify_token(authorization)
        token = auth_data["token"]
        user_id = auth_data["user_id"]

        contents = await file.read()
        blur_score = calculate_blur_score(contents)

        # Parse string payload from Streamlit form data into boolean
        is_whitening_enabled = aggressive_whitening.lower() in ["true", "1", "yes"]

        ocr_result = process_image_with_gemini(contents, aggressive_whitening=is_whitening_enabled)
        latex_text = ocr_result.get("latex", "")

        # Save record to Supabase bound to the authenticated user ID
        save_transcription(
            filename=file.filename,
            markdown_content=latex_text,
            blur_score=blur_score,
            whitening_enabled=is_whitening_enabled,
            user_id=user_id,
            access_token=token
        )

        return {
            "status": "success",
            "blur_score": blur_score,
            "latex": latex_text,
            "text": ocr_result.get("text", "")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/history")
def get_history(authorization: str = Header(...)):
    """Returns the 10 most recent transcriptions for the authenticated user."""
    auth_data = verify_token(authorization)
    token = auth_data["token"]
    return {"history": fetch_recent_transcriptions(access_token=token, limit=10)}