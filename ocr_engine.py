import io
import re
import base64
from PIL import Image, ImageEnhance, ImageOps
from google import genai


def crop_and_clean_diagram(image: Image.Image, coords: list) -> str:
    """Crops a diagram region based on [ymin, xmin, ymax, xmax] (0-1000 scale),

    cleans contrast, and returns base64 string.
    """
    width, height = image.size
    ymin, xmin, ymax, xmax = coords

    # 1. Convert normalized 0-1000 scale to actual pixel coordinates
    left = int((xmin / 1000.0) * width)
    top = int((ymin / 1000.0) * height)
    right = int((xmax / 1000.0) * width)
    bottom = int((ymax / 1000.0) * height)

    # 2. Add 5% safety margin padding
    pad_w = int((right - left) * 0.05)
    pad_h = int((bottom - top) * 0.05)

    left = max(0, left - pad_w)
    top = max(0, top - pad_h)
    right = min(width, right + pad_w)
    bottom = min(height, bottom + pad_h)

    # 3. Crop
    cropped = image.crop((left, top, right, bottom))

    # 4. Clean image: boost contrast slightly
    enhancer = ImageEnhance.Contrast(cropped)
    cleaned = enhancer.enhance(1.5)

    # 5. Convert to Base64 PNG string
    buffer = io.BytesIO()
    cleaned.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"


def process_image_with_gemini(image_bytes: bytes) -> dict:
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "Transcribe all handwritten text and mathematical formulas in this image accurately into LaTeX. "
        "Use $...$ for inline math and $$...$$ for display math. "
        "If there are any diagrams, graphs, geometric figures, or drawings in this image, "
        "identify their bounding boxes in normalized 0-1000 coordinates using exact tags like: "
        "[DIAGRAM: ymin, xmin, ymax, xmax] "
        "Place the [DIAGRAM: ...] tag in the text exactly where the figure appears."
    )

    client = genai.Client()  # Uses GEMINI_API_KEY from environment
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[image, prompt]
    )

    raw_text = response.text or ""

    # Parse [DIAGRAM: ymin, xmin, ymax, xmax] tags
    diagram_pattern = r'\[DIAGRAM:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    matches = re.findall(diagram_pattern, raw_text)

    # Replace diagram tags with base64 embedded markdown images
    cleaned_latex = raw_text
    for idx, match in enumerate(matches):
        coords = [int(c) for c in match]
        b64_img = crop_and_clean_diagram(image, coords)

        # Replace the tag with Markdown image tag
        tag_str = f"[DIAGRAM: {match[0]}, {match[1]}, {match[2]}, {match[3]}]"
        markdown_img = f"\n\n![]({b64_img})\n\n"
        cleaned_latex = cleaned_latex.replace(tag_str, markdown_img)

    return {
        "latex": cleaned_latex,
        "text": raw_text
    }