import os
import io
from PIL import Image
from google import genai


def process_image_with_gemini(image_bytes: bytes) -> dict:
    """
    Extracts text and LaTeX from image bytes using Gemini API safely.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"latex": "Error: GEMINI_API_KEY environment variable is missing on Render."}

    try:
        # Initialize Gemini Client
        client = genai.Client(api_key=api_key)

        # Load image from bytes
        image = Image.open(io.BytesIO(image_bytes))

        prompt = (
            "Transcribe all handwritten text and mathematical formulas in this image accurately. "
            "Convert all math expressions into standard LaTeX syntax. "
            "Return ONLY the transcribed text and LaTeX code, with no preamble."
        )

        # Generate output using Gemini 2.5 Flash
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[image, prompt]
        )

        extracted_text = response.text.strip() if response.text else "No text detected."
        return {"latex": extracted_text, "text": extracted_text}

    except Exception as e:
        # Catch errors gracefully to avoid 502 server crashes
        return {"latex": f"OCR Error: {str(e)}", "text": f"OCR Error: {str(e)}"}