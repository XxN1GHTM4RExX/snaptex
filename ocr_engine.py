import io
import re
import sys
import base64
import cv2
import numpy as np
import scipy
import matplotlib

matplotlib.use('Agg')  # Non-interactive backend for headless Render server
import matplotlib.pyplot as plt
from PIL import Image
from google import genai
from google.genai.errors import APIError

# Fully stocked model pool using all active Gemini Flash endpoints
MODEL_POOL = [
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]


def generate_with_model_fallback(client: genai.Client, contents: list) -> str:
    """Tries the primary model first, rotating through fallbacks if rate limits (429)

    or API errors occur.
    """
    last_exception = None

    for model_name in MODEL_POOL:
        try:
            print(f"Attempting OCR with model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=contents
            )
            if response.text:
                return response.text
        except APIError as e:
            print(f"Model {model_name} failed with API error: {e}. Rotating to next model...")
            last_exception = e
            continue
        except Exception as e:
            print(f"Unexpected error on {model_name}: {e}. Rotating to next model...")
            last_exception = e
            continue

    raise Exception(f"All models in fallback pool failed. Last error: {str(last_exception)}")


def crop_and_clean_diagram(image: Image.Image, coords: list) -> str:
    """Crops printed schematics/photos, removes page shadow gradients,

    boosts contrast, and returns base64 PNG string.
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
    img_np = np.array(cropped)

    # 4. Convert to Grayscale
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

    # 5. Remove shadow gradients using morphological background division
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
    norm_img = cv2.divide(gray, bg, scale=255)

    # 6. Apply CLAHE for crisp contrast on printed lines
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(norm_img)

    # 7. Convert back to PIL Image & Base64
    cleaned_image = Image.fromarray(enhanced)
    buffer = io.BytesIO()
    cleaned_image.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"


def render_matplotlib_code(code_str: str) -> str:
    """Safely executes generated Matplotlib code for hand-drawn sketches

    and returns a base64 PNG image on a pure #FFFFFF background.
    """
    buffer = io.BytesIO()
    plt.close('all')  # Clear any previous figures

    # Store original recursion depth
    orig_recursion = sys.getrecursionlimit()

    # Safe execution namespace with SciPy support
    exec_globals = {
        "plt": plt,
        "np": np,
        "scipy": scipy,
        "matplotlib": matplotlib
    }

    try:
        # Cap recursion depth to prevent runaway loops
        sys.setrecursionlimit(500)

        exec(code_str, exec_globals)
        plt.savefig(buffer, format="png", bbox_inches='tight', facecolor='white', dpi=300)
        plt.close('all')
        img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        plt.close('all')
        # Render a lightweight textual error placeholder without re-triggering subplots
        return f"**Diagram Rendering Error:** `{str(e)}`"
    finally:
        # Always restore default recursion ceiling
        sys.setrecursionlimit(orig_recursion)


def process_image_with_gemini(image_bytes: bytes) -> dict:
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "Transcribe all handwritten and printed content in this document accurately.\n"
        "1. Ignore vertical, rotated, or sideways text printed on the extreme outer page margins.\n"
        "2. Convert mathematical expressions into standard LaTeX syntax using $...$ for inline math and $$...$$ for display math.\n"
        "3. Format all tables using strict Markdown table syntax. Each table row MUST be on a single continuous line starting and ending with '|'. Always include the delimiter row (| --- | --- |).\n"
        "4. For visual elements, classify them into one of two categories:\n"
        "   a. PRINTED ILLUSTRATIONS / SCHEMATICS / PHOTOS:\n"
        "      Return exact bounding boxes using: [CROP_DIAGRAM: ymin, xmin, ymax, xmax].\n"
        "   b. HAND-DRAWN SKETCHES / GRAPHS ON RULED PAPER:\n"
        "      Do NOT crop. Instead, output a self-contained Python script using `matplotlib`, `numpy`, and `scipy` "
        "      that recreates a clean, publication-grade version of the chart/diagram on a pure white (#FFFFFF) background. "
        "      Wrap the script inside ```python ... ``` block tags directly where the figure belongs in the document flow."
    )

    client = genai.Client()
    raw_text = generate_with_model_fallback(client, [image, prompt])
    cleaned_latex = raw_text

    # 1. Process Path A: Crop printed schematics [CROP_DIAGRAM: ymin, xmin, ymax, xmax]
    crop_pattern = r'\[CROP_DIAGRAM:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    crop_matches = re.findall(crop_pattern, cleaned_latex)

    for match in crop_matches:
        coords = [int(c) for c in match]
        b64_img = crop_and_clean_diagram(image, coords)

        tag_str = f"[CROP_DIAGRAM: {match[0]}, {match[1]}, {match[2]}, {match[3]}]"
        markdown_img = f"\n\n![]({b64_img})\n\n"
        cleaned_latex = cleaned_latex.replace(tag_str, markdown_img)

    # 2. Process Path B: Render Matplotlib code blocks for hand-drawn sketches
    python_block_pattern = r'```python\s*(.*?)\s*```'
    code_matches = re.findall(python_block_pattern, cleaned_latex, re.DOTALL)

    for code in code_matches:
        if "plt." in code or "matplotlib" in code:
            rendered_output = render_matplotlib_code(code)
            raw_block = f"```python\n{code}\n```"

            # Format depending on whether rendering succeeded or failed
            if rendered_output.startswith("data:image"):
                markdown_img = f"\n\n![]({rendered_output})\n\n"
            else:
                markdown_img = f"\n\n{rendered_output}\n\n"

            cleaned_latex = cleaned_latex.replace(raw_block, markdown_img)

    return {
        "latex": cleaned_latex,
        "text": raw_text
    }