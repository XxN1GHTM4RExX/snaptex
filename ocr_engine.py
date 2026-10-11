import os
import io
from PIL import Image
from google import genai


def get_gemini_keys():
    """Gathers all available Gemini API keys from environment variables."""
    keys = []
    primary = os.getenv("GEMINI_API_KEY")
    if primary:
        keys.append(primary)
    for i in range(2, 8):
        k = os.getenv(f"GEMINI_API_KEY_{i}")
        if k:
            keys.append(k)
    return keys


def process_image_with_gemini(image_bytes: bytes) -> dict:
    api_keys = get_gemini_keys()
    if not api_keys:
        return {
            "latex": "Error: GEMINI_API_KEY missing in Render environment variables.",
            "text": "Error: GEMINI_API_KEY missing."
        }

    image = Image.open(io.BytesIO(image_bytes))
    prompt = (
        "Transcribe all handwritten text and mathematical formulas in this image accurately. "
        "Convert all math expressions into standard LaTeX syntax using $...$ for inline math "
        "and $$...$$ for display math. Do not wrap normal prose inside \\text{} blocks. "
        "Return ONLY the transcribed text and LaTeX code, without any introductory or conversational text."
    )

    last_error = "Unknown error"

    # Failover loop: Try each API key
    for key in api_keys:
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[image, prompt]
            )
            extracted_text = response.text.strip() if (response and response.text) else "No text detected."
            return {"latex": extracted_text, "text": extracted_text}
        except Exception as e:
            last_error = str(e)
            error_msg = last_error.lower()

            rate_limit_keywords = ["429", "503", "rate limit", "quota", "unavailable", "resource_exhausted", "exceeded"]

            if any(keyword in error_msg for keyword in rate_limit_keywords):
                continue  # Try next key

            return {"latex": f"OCR Processing Error: {last_error}", "text": f"OCR Processing Error: {last_error}"}

    # Fallback return so the function NEVER returns None
    return {
        "latex": f"Error: All available API keys were tried. Last response: {last_error}",
        "text": f"Error: All API keys exhausted."
    }