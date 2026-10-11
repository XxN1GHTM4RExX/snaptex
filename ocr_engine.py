import os
import io
import time
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

    # Sequence of models to try (if primary cluster is overloaded, fallback instantly)
    models_to_try = [
        "gemini-3.8-flash",  # Primary choice
        "gemini-2.5-flash",  # High-accuracy fallback
        "gemini-2.0-flash"  # High-availability fallback
    ]

    last_error = "Unknown error"

    # Multi-model and multi-key rotation loop
    for model_name in models_to_try:
        for key in api_keys:
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model=model_name,
                    contents=[image, prompt]
                )
                extracted_text = response.text.strip() if (response and response.text) else "No text detected."
                return {"latex": extracted_text, "text": extracted_text}
            except Exception as e:
                last_error = str(e)
                error_msg = last_error.lower()

                rate_limit_keywords = ["429", "503", "rate limit", "quota", "unavailable", "resource_exhausted",
                                       "exceeded", "high demand"]

                if any(keyword in error_msg for keyword in rate_limit_keywords):
                    time.sleep(0.5)  # Brief delay to permit server congestion clearing
                    continue  # Move to next key or model

                return {"latex": f"OCR Processing Error: {last_error}", "text": f"OCR Processing Error: {last_error}"}

    return {
        "latex": f"Error: All API keys and model fallbacks were attempted. Last response: {last_error}",
        "text": "Error: All keys and models busy."
    }