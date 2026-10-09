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

        # Call Gemini 2.5 Flash
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[image, prompt]
        )

        extracted_text = response.text.strip() if (response and response.text) else "No text detected."
        return {"latex": extracted_text, "text": extracted_text}

    except Exception as e:
        # Prevent 502 server crashes by returning errors inside the JSON response safely
        return {
            "latex": f"OCR Error: {str(e)}",
            "text": f"OCR Error: {str(e)}"
        }