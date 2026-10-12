import io
import re
import base64
import cv2
import numpy as np
from PIL import Image
from google import genai


def crop_and_clean_diagram(image: Image.Image, coords: list) -> str:
    """Crops a diagram region based on [ymin, xmin, ymax, xmax] (0-1000 scale),

    cleans background to pure white (#FFFFFF), reinforces lines to pure black,
    and returns a base64 PNG string.
    """
    width, height = image.size
    ymin, xmin, ymax, xmax = coords

    # 1. Convert normalized 0-1000 scale to pixel coordinates
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

    # 3. Crop image
    cropped = image.crop((left, top, right, bottom))

    # 4. Convert PIL Image to OpenCV numpy array (RGB to BGR/Gray)
    img_np = np.array(cropped)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

    # 5. Adaptive Thresholding: Background to #FFFFFF, lines to pure black
    cleaned_bw = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15,
        C=8
    )

    # 6. Convert OpenCV B&W array back to PIL Image
    cleaned_image = Image.fromarray(cleaned_bw)

    # 7. Convert to Base64 PNG string
    buffer = io.BytesIO()
    cleaned_image.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"


def process_image_with_gemini(image_bytes: bytes) -> dict:
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "Transcribe all handwritten and printed content in this document accurately.\n"
        "1. Ignore vertical, rotated, or sideways text printed on the extreme outer page margins.\n"
        "2. Convert mathematical expressions into standard LaTeX syntax using $...$ for inline math and $$...$$ for display math.\n"
        "3. Format all tables using strict Markdown table syntax. Each table row MUST be on a single continuous line starting and ending with '|'. Always include the delimiter row (| --- | --- |).\n"
        "4. If there are any photo illustrations, schematics, graphs, or visual drawings, identify their location "
        "and return bounding boxes in normalized 0-1000 coordinates using exact tags like: [DIAGRAM: ymin, xmin, ymax, xmax]. "
        "Place the [DIAGRAM: ...] tag directly where the image appears in the document flow."
    )

    client = genai.Client()
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[image, prompt]
    )

    raw_text = response.text or ""

    # Parse [DIAGRAM: ymin, xmin, ymax, xmax] tags
    diagram_pattern = r'\[DIAGRAM:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    matches = re.findall(diagram_pattern, raw_text)

    cleaned_latex = raw_text
    for match in matches:
        coords = [int(c) for c in match]
        b64_img = crop_and_clean_diagram(image, coords)

        tag_str = f"[DIAGRAM: {match[0]}, {match[1]}, {match[2]}, {match[3]}]"
        markdown_img = f"\n\n![]({b64_img})\n\n"
        cleaned_latex = cleaned_latex.replace(tag_str, markdown_img)

    return {
        "latex": cleaned_latex,
        "text": raw_text
    }