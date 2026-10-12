import io
import re
import sys
import ast
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

# Model pool with active model identifiers for fallback rotation
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

    # Add 5% safety margin padding
    pad_w = int((xmax - xmin) * 0.05)
    pad_h = int((ymax - ymin) * 0.05)

    left = max(0, int((xmin / 1000.0) * width) - pad_w)
    top = max(0, int((ymin / 1000.0) * height) - pad_h)
    right = min(width, int((xmax / 1000.0) * width) + pad_w)
    bottom = min(height, int((ymax / 1000.0) * height) + pad_h)

    cropped = image.crop((left, top, right, bottom))
    img_np = np.array(cropped)

    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
    norm_img = cv2.divide(gray, bg, scale=255)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(norm_img)

    cleaned_image = Image.fromarray(enhanced)
    buffer = io.BytesIO()
    cleaned_image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"


def sanitize_code(code_str: str) -> str:
    """Strips function definitions and unsafe constructs using AST parsing

    to prevent recursive execution loops.
    """
    cleaned = code_str.replace("```python", "").replace("```", "").strip()
    try:
        parsed = ast.parse(cleaned)
        # Remove function/class definitions to block recursive calls
        filtered_body = [
            node for node in parsed.body
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        parsed.body = filtered_body
        return ast.unparse(parsed)
    except Exception:
        # Fallback regex stripping if AST parsing fails
        return re.sub(r'def\s+\w+\s*\(.*?\):[\s\S]*?(?=\n\S|\Z)', '', cleaned)


def render_matplotlib_code(code_str: str) -> str:
    """Executes Matplotlib code cleanly in an isolated scope.

    Returns base64 string on success, or None on error to trigger crop fallback.
    """
    buffer = io.BytesIO()
    plt.close('all')

    orig_recursion = sys.getrecursionlimit()
    sanitized_script = sanitize_code(code_str)

    exec_globals = {
        "plt": plt,
        "np": np,
        "scipy": scipy,
        "matplotlib": matplotlib
    }

    try:
        sys.setrecursionlimit(200)
        exec(sanitized_script, exec_globals)
        plt.savefig(buffer, format="png", bbox_inches='tight', facecolor='white', dpi=300)
        plt.close('all')
        return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"
    except Exception as e:
        plt.close('all')
        print(f"Matplotlib execution failed: {e}. Falling back to image crop.")
        return None  # Triggers crop fallback
    finally:
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
        "   b. HAND-DRAWN SKETCHES / GRAPHS / CURVES:\n"
        "      Output a SEPARATE, standalone Python script for EACH individual graph or curve in the document.\n"
        "      STRICT CODING RULES PER SCRIPT:\n"
        "      - Write ONLY linear, procedural Matplotlib code for THAT SINGLE figure (fig, ax = plt.subplots(figsize=(6, 3))).\n"
        "      - Do NOT combine multiple separate drawings into one giant script.\n"
        "      - Write purely sequential code (plt.plot, plt.fill_between, plt.xticks, plt.text). Absolutely NO custom `def` functions, recursion, or loops.\n"
        "      - Transcribe all x-axis values and region numbers (e.g. 34%, 13.5%, 2.35%, x-values) into `plt.xticks()` or `plt.text()`.\n"
        "      - Always include bounding box coordinates in a comment at the top like `# BOUNDS: ymin, xmin, ymax, xmax` for fallback.\n"
        "      - Wrap each script inside its own ```python ... ``` block tag directly where that specific figure belongs in the text flow."
    )

    client = genai.Client()
    raw_text = generate_with_model_fallback(client, [image, prompt])
    cleaned_latex = raw_text

    # 1. Process Path A: Crop printed schematics
    crop_pattern = r'\[CROP_DIAGRAM:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    crop_matches = re.findall(crop_pattern, cleaned_latex)

    for match in crop_matches:
        coords = [int(c) for c in match]
        b64_img = crop_and_clean_diagram(image, coords)
        tag_str = f"[CROP_DIAGRAM: {match[0]}, {match[1]}, {match[2]}, {match[3]}]"
        cleaned_latex = cleaned_latex.replace(tag_str, f"\n\n![]({b64_img})\n\n")

    # 2. Process Path B: Render Matplotlib code blocks with dynamic crop fallback
    python_block_pattern = r'```python\s*(.*?)\s*```'
    code_matches = re.findall(python_block_pattern, cleaned_latex, re.DOTALL)

    for code in code_matches:
        if "plt." in code or "matplotlib" in code:
            rendered_output = render_matplotlib_code(code)
            raw_block = f"```python\n{code}\n```"

            if rendered_output:
                markdown_img = f"\n\n![]({rendered_output})\n\n"
            else:
                # Fallback: Extract bounds comment if available, otherwise fallback to full crop
                bounds_match = re.search(r'#\s*BOUNDS:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)', code)
                if bounds_match:
                    coords = [int(c) for c in bounds_match.groups()]
                    b64_img = crop_and_clean_diagram(image, coords)
                    markdown_img = f"\n\n![]({b64_img})\n\n"
                else:
                    markdown_img = ""

            cleaned_latex = cleaned_latex.replace(raw_block, markdown_img)

    return {
        "latex": cleaned_latex,
        "text": raw_text
    }