import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is not set in the .env file.")

client = genai.Client(api_key=api_key)


def transcribe_document(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """
    Sends document image bytes to Gemini to extract text and LaTeX math.
    Includes a built-in retry loop for handling temporary 503 server spikes.
    """
    prompt = (
        "You are an expert OCR engine for academic documents. "
        "Transcribe all readable text from this document accurately. "
        "Convert any mathematical equations, formulas, or symbols into standard LaTeX format "
        "enclosed in inline ($...$) or display ($$...$$) math blocks. "
        "Do not include conversational introductions or commentary—return only the transcribed content."
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt
                ]
            )
            return response.text
        except Exception as e:
            # If server is temporarily busy, wait 2 seconds and retry
            if "503" in str(e) and attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise e