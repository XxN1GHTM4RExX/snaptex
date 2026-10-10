import os
import io
from PIL import Image
from google import genai


def process_image_with_gemini(image_bytes: bytes) -> dict:
    """
    Safely processes image bytes using Gemini API without crashing the server.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "latex": "Error: GEMINI_API_KEY environment variable is missing on Render.",
            "text": "Error: GEMINI_API_KEY environment variable is missing on Render."
        }

    try:
        # Initialize Google GenAI client
        client = genai.Client(api_key=api_key)

        # Open image from memory
        image = Image.open(io.BytesIO(image_bytes))

        prompt = (
            "Transcribe all handwritten text and mathematical formulas in this image accurately. "
            "Convert all math expressions into standard LaTeX syntax. "
            "Return ONLY the transcribed text and LaTeX code, without any introductory or conversational text."
        )

        # Using gemini-3.8-flash as required by Google GenAI v1beta
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[image, prompt]
        )

        extracted_text = response.text.strip() if (response and response.text) else "No text detected."
        return {"latex": extracted_text, "text": extracted_text}

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            return {
                "latex": "Rate Limit Exceeded: Free tier quota reached for gemini-3.8-flash. Please wait a short while or try again later.",
                "text": "Rate Limit Exceeded: Free tier quota reached."
            }

        return {
            "latex": f"OCR Processing Error: {error_msg}",
            "text": f"OCR Processing Error: {error_msg}"
        }