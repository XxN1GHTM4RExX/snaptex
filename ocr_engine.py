import io
import re
import sys
import ast
import base64
import cv2
import numpy as np
import scipy
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
import requests
from google import genai
from google.genai.errors import APIError

from key_manager import provider_manager

MODEL_POOL_GOOGLE = [
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash"
]


def call_groq_ocr(api_key: str, contents: list) -> str:
    """Fallback OCR handler using Groq Cloud's Llama Vision endpoint."""
    image_obj, prompt_text = contents[0], contents[1]

    buffer = io.BytesIO()
    image_obj.save(buffer, format="PNG")
    b64_img = base64.b64encode(buffer.getvalue()).decode('utf-8')

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.2-11b-vision-instruct",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}}
                ]
            }
        ],
        "temperature": 0.1
    }

    response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload,
                             timeout=60)
    print(f"[Groq Debug Status]: {response.status_code} | Response: {response.text[:200]}")

    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    elif response.status_code == 429:
        provider_manager.groq_pool.mark_rate_limited(api_key, cooldown_seconds=60)
        raise Exception("Groq rate limit reached (429).")
    else:
        raise Exception(f"Groq API error {response.status_code}: {response.text}")


def call_openrouter_ocr(api_key: str, contents: list) -> str:
    """Fallback OCR handler using OpenRouter's free vision endpoint."""
    image_obj, prompt_text = contents[0], contents[1]

    buffer = io.BytesIO()
    image_obj.save(buffer, format="PNG")
    b64_img = base64.b64encode(buffer.getvalue()).decode('utf-8')

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://snaptex.onrender.com",
        "X-Title": "Snaptex OCR",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "qwen/qwen-2.5-vl-72b-instruct:free",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}}
                ]
            }
        ]
    }

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
    print(f"[OpenRouter Debug Status]: {response.status_code} | Response: {response.text[:200]}")

    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    elif response.status_code == 429:
        provider_manager.openrouter_pool.mark_rate_limited(api_key, cooldown_seconds=60)
        raise Exception("OpenRouter rate limit reached (429).")
    else:
        raise Exception(f"OpenRouter API error {response.status_code}: {response.text}")


def generate_with_multi_provider_fallback(contents: list) -> str:
    """Tier 1: Google AI Studio -> Tier 2: Groq -> Tier 3: OpenRouter."""

    # 1. Try Google Pool First
    g_key = provider_manager.google_pool.get_key()
    if g_key:
        try:
            client = genai.Client(api_key=g_key)
            for model_name in MODEL_POOL_GOOGLE:
                try:
                    print(f"Attempting Google OCR with model: {model_name}")
                    response = client.models.generate_content(model=model_name, contents=contents)
                    if response.text:
                        return response.text
                except APIError as e:
                    print(f"[Google API Error]: Code {e.code} - {e.message}")
                    if e.code == 429 or "quota" in str(e).lower():
                        provider_manager.google_pool.mark_rate_limited(g_key, cooldown_seconds=60)
                        break
                    continue
                except Exception as e:
                    print(f"[Google Model {model_name} Failed]: {e}")
                    continue

            # If all Google models failed for active key, set cooldown and trigger provider fallback
            print("All Google models failed for active key. Cascading to next provider...")
            provider_manager.google_pool.mark_rate_limited(g_key, cooldown_seconds=60)
        except Exception as e:
            print(f"Google Client setup failed: {e}")

    # 2. Cascade to Groq Pool
    groq_key = provider_manager.groq_pool.get_key()
    if groq_key:
        try:
            print("Cascading to Groq Vision API...")
            return call_groq_ocr(groq_key, contents)
        except Exception as e:
            print(f"Groq failed: {e}")

    # 3. Cascade to OpenRouter Free Pool
    or_key = provider_manager.openrouter_pool.get_key()
    if or_key:
        try:
            print("Cascading to OpenRouter Free Vision API...")
            return call_openrouter_ocr(or_key, contents)
        except Exception as e:
            print(f"OpenRouter failed: {e}")

    raise Exception("All configured free AI providers (Google, Groq, OpenRouter) are rate-limited or unavailable.")


def crop_and_clean_diagram(image: Image.Image, coords: list, aggressive_whitening: bool = False) -> str:
    width, height = image.size
    ymin, xmin, ymax, xmax = coords

    pad_w = int((xmax - xmin) * 0.05)
    pad_h = int((ymax - ymin) * 0.05)

    left = max(0, int((xmin / 1000.0) * width) - pad_w)
    top = max(0, int((ymin / 1000.0) * height) - pad_h)
    right = min(width, int((xmax / 1000.0) * width) + pad_w)
    bottom = min(height, int((ymax / 1000.0) * height) + pad_h)

    cropped = image.crop((left, top, right, bottom))
    img_np = np.array(cropped)

    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

    if aggressive_whitening:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
        bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
        norm = cv2.divide(gray, bg, scale=255)
        _, white_bg = cv2.threshold(norm, 205, 255, cv2.THRESH_TRUNC)
        final_img = cv2.normalize(white_bg, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 40))
        bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
        norm = cv2.divide(gray, bg, scale=255)
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        final_img = clahe.apply(norm)

    cleaned_image = Image.fromarray(final_img)
    buffer = io.BytesIO()
    cleaned_image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"


def sanitize_code(code_str: str) -> str:
    cleaned = code_str.replace("```python", "").replace("```", "").strip()
    try:
        parsed = ast.parse(cleaned)
        filtered_body = [
            node for node in parsed.body
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        parsed.body = filtered_body
        return ast.unparse(parsed)
    except Exception:
        return re.sub(r'def\s+\w+\s*\(.*?\):[\s\S]*?(?=\n\S|\Z)', '', cleaned)


def render_matplotlib_code(code_str: str) -> str:
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
        return None
    finally:
        sys.setrecursionlimit(orig_recursion)


def process_image_with_gemini(image_bytes: bytes, aggressive_whitening: bool = False) -> dict:
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "Transcribe all handwritten and printed content in this document accurately.\n"
        "1. Ignore vertical, rotated, or sideways text printed on the extreme outer page margins.\n"
        "2. Convert mathematical expressions into standard LaTeX syntax using $...$ for inline math and $$...$$ for display math.\n"
        "3. Format all tables using strict Markdown table syntax. Each table row MUST be on a single continuous line starting and ending with '|'. Always include the delimiter row (| --- | --- |).\n"
        "4. Transcribe key-value metadata lists, technical spec fields, and labeled pairs (e.g., Trade Name, Manufacturer, Type Set, Power Supply) into explicit 2-column Markdown tables (| Property | Value |) rather than stacked text.\n"
        "5. For visual elements, classify them into one of two categories:\n"
        "   a. PRINTED ILLUSTRATIONS / SCHEMATICS / PHOTOS:\n"
        "      Return exact bounding boxes using: [CROP_DIAGRAM: ymin, xmin, ymax, xmax].\n"
        "   b. HAND-DRAWN SKETCHES / GRAPHS / CURVES:\n"
        "      Output a SEPARATE, standalone Python script for EACH individual graph or curve in the document.\n"
        "      STRICT CODING RULES PER SCRIPT:\n"
        "      - Write ONLY linear, procedural Matplotlib code for THAT SINGLE figure (fig, ax = plt.subplots(figsize=(6, 3))).\n"
        "      - Do NOT combine multiple separate drawings into one giant script.\n"
        "      - Write purely sequential code (plt.plot, plt.fill_between, plt.xticks, plt.text). Absolutely NO custom `def` functions, recursion, or loops.\n"
        "      - Transcribe all x-axis values and region numbers (e.g., 34%, 13.5%, 2.35%, x-values) into `plt.xticks()` or `plt.text()`.\n"
        "      - Always include bounding box coordinates in a comment at the top like `# BOUNDS: ymin, xmin, ymax, xmax` for fallback.\n"
        "      - Wrap each script inside its own ```python ... ``` block tag directly where that specific figure belongs in the text flow."
    )

    raw_text = generate_with_multi_provider_fallback([image, prompt])
    cleaned_latex = raw_text

    crop_pattern = r'\[CROP_DIAGRAM:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    crop_matches = re.findall(crop_pattern, cleaned_latex)

    for match in crop_matches:
        coords = [int(c) for c in match]
        b64_img = crop_and_clean_diagram(image, coords, aggressive_whitening=aggressive_whitening)
        tag_str = f"[CROP_DIAGRAM: {match[0]}, {match[1]}, {match[2]}, {match[3]}]"
        cleaned_latex = cleaned_latex.replace(tag_str, f"\n\n![]({b64_img})\n\n")

    python_block_pattern = r'```python\s*(.*?)\s*```'
    code_matches = re.findall(python_block_pattern, cleaned_latex, re.DOTALL)

    for code in code_matches:
        if "plt." in code or "matplotlib" in code:
            rendered_output = render_matplotlib_code(code)
            raw_block = f"```python\n{code}\n```"

            if rendered_output:
                markdown_img = f"\n\n![]({rendered_output})\n\n"
            else:
                bounds_match = re.search(r'#\s*BOUNDS:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)', code)
                if bounds_match:
                    coords = [int(c) for c in bounds_match.groups()]
                    b64_img = crop_and_clean_diagram(image, coords, aggressive_whitening=aggressive_whitening)
                    markdown_img = f"\n\n![]({b64_img})\n\n"
                else:
                    markdown_img = ""

            cleaned_latex = cleaned_latex.replace(raw_block, markdown_img)

    return {
        "latex": cleaned_latex,
        "text": raw_text
    }