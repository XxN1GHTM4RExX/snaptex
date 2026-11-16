import io
import re
import base64
import urllib.parse
import cv2
import numpy as np
from PIL import Image
import requests
import vtracer
from google import genai
from google.genai.errors import APIError

from key_manager import provider_manager

MODEL_POOL_GOOGLE = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3-flash-preview"
]

MODEL_POOL_GROQ = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview"
]

MODEL_POOL_OPENROUTER = [
    "openrouter/free",
    "qwen/qwen3-vl-30b-a3b-instruct:free",
    "qwen/qwen2.5-vl-72b-instruct:free",
    "meta-llama/llama-4-scout:free"
]


def _encode_image_for_openai_compat(image_obj: Image.Image, max_dim: int = 1600) -> str:
    """Resizes oversized images and encodes as JPEG base64 so Groq/OpenRouter don't reject large PNG payloads."""
    img = image_obj.convert("RGB")
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _discover_google_models(client: genai.Client) -> list:
    """Dynamically fetches live Gemini models supporting generateContent as a fallback if hardcoded slugs 404."""
    discovered = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "").replace("models/", "")
            methods = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", []) or []
            if "gemini" in name.lower() and "embedding" not in name.lower() and "tts" not in name.lower():
                if not methods or "generateContent" in methods:
                    discovered.append(name)
    except Exception as e:
        print(f"[Google Model Discovery Error]: {e}")
    return discovered


def _discover_groq_vision_models(api_key: str) -> list:
    """Queries Groq /models endpoint for currently active vision/multimodal models."""
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if resp.status_code == 200:
            models = [m["id"] for m in resp.json().get("data", [])]
            return [m for m in models if any(k in m.lower() for k in ("vision", "llama-4", "vl", "multimodal"))]
    except Exception as e:
        print(f"[Groq Model Discovery Error]: {e}")
    return []


def _discover_openrouter_free_vision_models() -> list:
    """Queries OpenRouter /models endpoint for active :free models that accept image inputs."""
    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
        if resp.status_code == 200:
            free_vision = []
            for m in resp.json().get("data", []):
                mid = m.get("id", "")
                modalities = m.get("architecture", {}).get("input_modalities", [])
                if mid.endswith(":free") and "image" in modalities:
                    free_vision.append(mid)
            return free_vision[:6]
    except Exception as e:
        print(f"[OpenRouter Model Discovery Error]: {e}")
    return []


def call_groq_ocr(api_key: str, contents: list) -> str:
    """Fallback OCR handler using Groq Cloud's Vision endpoint."""
    image_obj, prompt_text = contents[0], contents[1]
    b64_img = _encode_image_for_openai_compat(image_obj)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    models_to_try = list(MODEL_POOL_GROQ)
    discovered = _discover_groq_vision_models(api_key)
    for m in discovered:
        if m not in models_to_try:
            models_to_try.append(m)

    last_err = None
    for model_name in models_to_try:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                    ]
                }
            ],
            "temperature": 0.1
        }

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=25
        )
        print(f"[Groq Debug Status ({model_name})]: {response.status_code} | Response: {response.text[:200]}")

        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        elif response.status_code == 429:
            provider_manager.groq_pool.mark_rate_limited(api_key, cooldown_seconds=60)
            raise Exception("Groq rate limit reached (429).")
        else:
            last_err = f"Groq({model_name}) {response.status_code}: {response.text[:160]}"

    raise Exception(last_err or "Groq call failed.")


def call_openrouter_ocr(api_key: str, contents: list) -> str:
    """Fallback OCR handler using OpenRouter's free vision endpoints."""
    image_obj, prompt_text = contents[0], contents[1]
    b64_img = _encode_image_for_openai_compat(image_obj)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://snaptex.onrender.com",
        "X-Title": "Snaptex OCR",
        "Content-Type": "application/json"
    }

    models_to_try = list(MODEL_POOL_OPENROUTER)
    discovered = _discover_openrouter_free_vision_models()
    for m in discovered:
        if m not in models_to_try:
            models_to_try.append(m)

    last_err = None
    for model_name in models_to_try:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                    ]
                }
            ],
            "temperature": 0.1
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=25
        )
        print(f"[OpenRouter Debug Status ({model_name})]: {response.status_code} | Response: {response.text[:200]}")

        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        elif response.status_code == 429:
            provider_manager.openrouter_pool.mark_rate_limited(api_key, cooldown_seconds=60)
            raise Exception("OpenRouter rate limit reached (429).")
        else:
            last_err = f"OpenRouter({model_name}) {response.status_code}: {response.text[:160]}"

    raise Exception(last_err or "OpenRouter call failed.")


def generate_with_multi_provider_fallback(contents: list) -> str:
    """Tier 1: All Google Keys -> Tier 2: All Groq Keys -> Tier 3: All OpenRouter Keys."""
    provider_manager.reload_all()
    errors = []

    print(
        f"[Pool Status] Google: {provider_manager.google_pool.available_count()}/{len(provider_manager.google_pool.keys)} | "
        f"Groq: {provider_manager.groq_pool.available_count()}/{len(provider_manager.groq_pool.keys)} | "
        f"OpenRouter: {provider_manager.openrouter_pool.available_count()}/{len(provider_manager.openrouter_pool.keys)}"
    )

    # 1. Exhaust all available keys in Google Pool
    for _ in range(len(provider_manager.google_pool.keys)):
        g_key = provider_manager.google_pool.get_key()
        if not g_key:
            break
        try:
            client = genai.Client(api_key=g_key, http_options={"timeout": 30000})
            key_rate_limited = False
            models_to_try = list(MODEL_POOL_GOOGLE)
            discovered_added = False

            idx = 0
            while idx < len(models_to_try):
                model_name = models_to_try[idx]
                idx += 1
                try:
                    print(f"Attempting Google OCR ({g_key[:8]}...) with model: {model_name}")
                    response = client.models.generate_content(model=model_name, contents=contents)
                    if response.text:
                        return response.text
                except APIError as e:
                    print(f"[Google API Error]: Code {e.code} - {e.message}")
                    errors.append(f"Google({model_name}): {e.code}")
                    if e.code == 429 or "quota" in str(e).lower():
                        provider_manager.google_pool.mark_rate_limited(g_key, cooldown_seconds=60)
                        key_rate_limited = True
                        break
                    if e.code == 404 and not discovered_added:
                        discovered_added = True
                        for dm in _discover_google_models(client):
                            if dm not in models_to_try:
                                models_to_try.append(dm)
                except Exception as e:
                    print(f"[Google Model {model_name} Failed]: {e}")
                    errors.append(f"Google({model_name}): {e}")

            if not key_rate_limited:
                provider_manager.google_pool.mark_rate_limited(g_key, cooldown_seconds=60)
        except Exception as e:
            print(f"Google Client setup failed: {e}")
            errors.append(f"GoogleClient: {e}")

    # 2. Exhaust all available keys in Groq Pool
    for _ in range(len(provider_manager.groq_pool.keys)):
        groq_key = provider_manager.groq_pool.get_key()
        if not groq_key:
            break
        try:
            print(f"Cascading to Groq Vision API ({groq_key[:8]}...)...")
            return call_groq_ocr(groq_key, contents)
        except Exception as e:
            print(f"Groq failed: {e}")
            errors.append(f"Groq: {e}")

    # 3. Exhaust all available keys in OpenRouter Free Pool
    for _ in range(len(provider_manager.openrouter_pool.keys)):
        or_key = provider_manager.openrouter_pool.get_key()
        if not or_key:
            break
        try:
            print(f"Cascading to OpenRouter Free Vision API ({or_key[:8]}...)...")
            return call_openrouter_ocr(or_key, contents)
        except Exception as e:
            print(f"OpenRouter failed: {e}")
            errors.append(f"OpenRouter: {e}")

    raise Exception(
        f"All AI providers failed. Details: {' | '.join(errors) if errors else 'No API keys loaded in environment.'}"
    )


# ==============================================================================
# 4-TIER VISUAL PIPELINE:
# 1. TikZ / CircuiTikZ (QuickLaTeX \mbox bounded -> Kroki -> Crop fallback)
# 2. Vtracer B&W Binary Vectorization (replaces Potrace in compiled Rust)
# 3. Vtracer Multi-Color Vectorization
# 4. OpenCV Background Whitening Crop
# ==============================================================================

def _flatten_to_white_png(raw_bytes: bytes, pad: int = 20) -> str:
    """Composites any transparent PNG onto a solid white RGB canvas with padding."""
    raw_img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    white_bg = Image.new("RGBA", (raw_img.width + pad * 2, raw_img.height + pad * 2), (255, 255, 255, 255))
    white_bg.paste(raw_img, (pad, pad), raw_img)
    final_rgb = white_bg.convert("RGB")

    out_buf = io.BytesIO()
    final_rgb.save(out_buf, format="PNG")
    b64_png = base64.b64encode(out_buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_png}"


def _crop_region(image: Image.Image, coords: list) -> Image.Image:
    """Safely crops a normalized [0..1000] bounding box with 5% padding."""
    width, height = image.size
    ymin, xmin, ymax, xmax = coords

    pad_w = int(((xmax - xmin) / 1000.0) * width * 0.05)
    pad_h = int(((ymax - ymin) / 1000.0) * height * 0.05)

    left = max(0, int((xmin / 1000.0) * width) - pad_w)
    top = max(0, int((ymin / 1000.0) * height) - pad_h)
    right = min(width, int((xmax / 1000.0) * width) + pad_w)
    bottom = min(height, int((ymax / 1000.0) * height) + pad_h)

    if right <= left or bottom <= top:
        return image
    return image.crop((left, top, right, bottom))


def crop_and_clean_diagram(image: Image.Image, coords: list, aggressive_whitening: bool = False) -> str:
    """Tier 4: OpenCV background whitening & contrast enhancement for photos and dense figures."""
    cropped = _crop_region(image, coords).convert("RGB")
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


def vectorize_diagram_vtracer(image: Image.Image, coords: list, color_mode: str = "binary") -> str:
    """
    Tier 2 & Tier 3: Vectorizes cropped diagrams into crisp SVGs using Vtracer.
    - color_mode='binary': High-contrast B&W curve tracing (replaces Potrace).
    - color_mode='color': Layered multi-color SVG tracing.
    """
    try:
        cropped = _crop_region(image, coords).convert("RGB")
        img_np = np.array(cropped)

        if color_mode == "binary":
            gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 35))
            bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
            norm = cv2.divide(gray, bg, scale=255)
            binary = cv2.adaptiveThreshold(
                norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 12
            )
            prep_pil = Image.fromarray(binary).convert("RGBA")
        else:
            lab = cv2.cvtColor(img_np, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
            l = clahe.apply(l)
            balanced = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB)
            prep_pil = Image.fromarray(balanced).convert("RGBA")

        raw_pixels = list(prep_pil.getdata())
        width, height = prep_pil.size

        svg_str = vtracer.convert_pixels_to_svg(
            raw_pixels,
            size=(width, height),
            colormode=color_mode,
            hierarchical="stacked",
            mode="spline",
            filter_speckle=4,
            color_precision=6,
            layer_difference=16,
            corner_threshold=60,
            length_threshold=4.0,
            max_iterations=10,
            splice_threshold=45,
            path_precision=3
        )

        svg_b64 = base64.b64encode(svg_str.encode("utf-8")).decode("utf-8")
        return f"data:image/svg+xml;base64,{svg_b64}"
    except Exception as e:
        print(f"[Vtracer ({color_mode}) Error]: {e}. Falling back to OpenCV crop.")
        return crop_and_clean_diagram(image, coords, aggressive_whitening=(color_mode == "binary"))


def _clean_tikz_snippet(raw_code: str) -> str:
    """Strips markdown fences and comment lines to isolate the TikZ/CircuiTikZ body."""
    cleaned = re.sub(r'^[%#].*$', '', raw_code, flags=re.MULTILINE).strip()
    env_match = re.search(
        r'(\\begin\{(?:tikzpicture|circuitikz)\}[\s\S]*?\\end\{(?:tikzpicture|circuitikz)\})',
        cleaned
    )
    if env_match:
        return env_match.group(1)
    return cleaned


def _render_via_quicklatex(tikz_body: str) -> str:
    """Primary TikZ/CircuiTikZ renderer via QuickLaTeX with full STEM package preamble."""
    preamble = (
        "\\usepackage{amsmath,amssymb}\n"
        "\\usepackage{tikz}\n"
        "\\usepackage{circuitikz}\n"
        "\\usetikzlibrary{arrows.meta,patterns,angles,quotes,calc,positioning,decorations.pathmorphing,decorations.markings}"
    )
    # Wrapping inside \mbox forces QuickLaTeX to preserve the full TikZ bounding box instead of collapsing labels
    wrapped_body = f"\\mbox{{{tikz_body}}}"
    payload = (
        f"formula={urllib.parse.quote(wrapped_body)}"
        f"&fsize=18px"
        f"&fcolor=000000"
        f"&mode=0"
        f"&out=1"
        f"&remhost=quicklatex.com"
        f"&preamble={urllib.parse.quote(preamble)}"
    )
    resp = requests.post(
        "https://quicklatex.com/latex3.f",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=12
    )
    if resp.status_code == 200:
        lines = resp.text.strip().splitlines()
        if len(lines) >= 2 and lines[0].strip() == "0":
            img_url = lines[1].split()[0]
            img_resp = requests.get(img_url, timeout=10)
            if img_resp.status_code == 200 and img_resp.content:
                return _flatten_to_white_png(img_resp.content)
    return None


def _render_via_kroki(tikz_body: str) -> str:
    """Secondary TikZ renderer via Kroki standalone LaTeX engine."""
    resp = requests.post(
        "https://kroki.io/tikz/png",
        data=tikz_body.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=12
    )
    if resp.status_code == 200 and resp.content:
        return _flatten_to_white_png(resp.content)
    return None


def render_tikz_diagram(raw_code: str) -> str:
    """Tier 1: Compiles any TikZ/CircuiTikZ via QuickLaTeX (\\mbox bounded) -> Kroki fallback."""
    tikz_body = _clean_tikz_snippet(raw_code)
    if not tikz_body:
        return None

    def _is_valid_render(data_uri: str) -> bool:
        if not data_uri:
            return False
        try:
            b64_part = data_uri.split(",", 1)[1]
            check_img = Image.open(io.BytesIO(base64.b64decode(b64_part)))
            return check_img.width >= 90 and check_img.height >= 90
        except Exception:
            return False

    # 1. Try QuickLaTeX first (supports circuitikz, decorations.pathmorphing springs, patterns, etc.)
    try:
        res = _render_via_quicklatex(tikz_body)
        if _is_valid_render(res):
            print("[TikZ Renderer]: Compiled successfully via QuickLaTeX.")
            return res
        elif res:
            print("[TikZ Renderer]: QuickLaTeX output collapsed, rejecting.")
    except Exception as e:
        print(f"[QuickLaTeX Error]: {e}")

    # 2. Try Kroki second (for standard tikzpicture diagrams)
    try:
        res = _render_via_kroki(tikz_body)
        if _is_valid_render(res):
            print("[TikZ Renderer]: Compiled successfully via Kroki fallback.")
            return res
    except Exception as e:
        print(f"[Kroki TikZ Error]: {e}")

    return None


def process_image_with_gemini(image_bytes: bytes, aggressive_whitening: bool = False) -> dict:
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "Transcribe all handwritten and printed content in this document accurately.\n"
        "1. Ignore vertical, rotated, or sideways text printed on the extreme outer page margins.\n"
        "2. Convert mathematical expressions into standard LaTeX syntax using $...$ for inline math and $$...$$ for display math.\n"
        "3. Format all tables using strict Markdown table syntax. Each table row MUST be on a single continuous line starting and ending with '|'. Always include the delimiter row (| --- | --- |).\n"
        "4. Transcribe key-value metadata lists, technical spec fields, and labeled pairs (e.g., Trade Name, Manufacturer, Type Set, Power Supply) into explicit 2-column Markdown tables (| Property | Value |) rather than stacked text.\n"
        "5. Classify EVERY visual figure, diagram, graph, or sketch into the best matching tier below:\n"
        "   a. MECHANICAL DIAGRAMS, FORCE VECTORS, CIRCUITS, & GEOMETRIC SCHEMATICS:\n"
        "      Output a standalone ```tikz ... ``` block directly where the diagram appears.\n"
        "      - First line inside the block MUST be: `% BOUNDS: ymin, xmin, ymax, xmax` (normalized 0-1000 coordinates for fallback).\n"
        "      - Use standard `\\begin{circuitikz} ... \\end{circuitikz}` for electrical circuits (using `to[R=$R_1$]`, `to[battery1, l=$E$]`, `to[C=$C$]`, `to[L=$L$]`, `i=$I$`, etc.) OR `\\begin{tikzpicture} ... \\end{tikzpicture}` (with libraries `arrows.meta`, `patterns`, `decorations.pathmorphing`, `angles`, `quotes`) for mechanics, springs, pulleys, and geometry.\n"
        "      - Write ONLY the environment block (no `\\documentclass` or `\\begin{document}`), and keep node distances >= 2.5cm so labels never overlap.\n"
        "   b. HAND-DRAWN CURVES, STATISTICAL GRAPHS, & BLACK-AND-WHITE LINE SKETCHES:\n"
        "      Return exact bounding boxes using: [VECTOR_BW: ymin, xmin, ymax, xmax].\n"
        "   c. COLORED DIAGRAMS, MULTI-INK CHARTS, & COLORED FLOWCHARTS:\n"
        "      Return exact bounding boxes using: [VECTOR_COLOR: ymin, xmin, ymax, xmax].\n"
        "   d. REAL-WORLD PHOTOS, TEXTBOOK SCREENSHOTS, & SHADED ILLUSTRATIONS:\n"
        "      Return exact bounding boxes using: [CROP_DIAGRAM: ymin, xmin, ymax, xmax]."
    )

    raw_text = generate_with_multi_provider_fallback([image, prompt])
    cleaned_latex = raw_text

    # 1. Process Tier 1: TikZ / CircuiTikZ blocks (QuickLaTeX \mbox -> Kroki -> OpenCV Crop fallback)
    tikz_pattern = r'```(?:tikz|latex)\s*(.*?)\s*```'
    tikz_matches = re.findall(tikz_pattern, cleaned_latex, re.DOTALL)

    for code in tikz_matches:
        if "\\begin{tikzpicture}" in code or "\\begin{circuitikz}" in code:
            rendered_uri = render_tikz_diagram(code)
            raw_block_re = re.compile(r'```(?:tikz|latex)\s*' + re.escape(code) + r'\s*```', re.DOTALL)

            if rendered_uri:
                replacement = f"\n\n![]({rendered_uri})\n\n"
            else:
                bounds_match = re.search(r'[%#]\s*BOUNDS:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)', code)
                if bounds_match:
                    coords = [int(c) for c in bounds_match.groups()]
                    b64_img = crop_and_clean_diagram(image, coords, aggressive_whitening=aggressive_whitening)
                    replacement = f"\n\n![]({b64_img})\n\n"
                else:
                    replacement = ""

            cleaned_latex = raw_block_re.sub(lambda _: replacement, cleaned_latex, count=1)

    # 2. Process Tier 2: B&W Vector Tracing (Vtracer binary mode)
    bw_pattern = r'\[VECTOR_BW:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    for match in re.findall(bw_pattern, cleaned_latex):
        coords = [int(c) for c in match]
        svg_uri = vectorize_diagram_vtracer(image, coords, color_mode="binary")
        tag_re = re.compile(rf'\[VECTOR_BW:\s*{match[0]},\s*{match[1]},\s*{match[2]},\s*{match[3]}\]')
        cleaned_latex = tag_re.sub(lambda _: f"\n\n![]({svg_uri})\n\n", cleaned_latex, count=1)

    # 3. Process Tier 3: Color Vector Tracing (Vtracer color mode)
    color_pattern = r'\[VECTOR_COLOR:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    for match in re.findall(color_pattern, cleaned_latex):
        coords = [int(c) for c in match]
        svg_uri = vectorize_diagram_vtracer(image, coords, color_mode="color")
        tag_re = re.compile(rf'\[VECTOR_COLOR:\s*{match[0]},\s*{match[1]},\s*{match[2]},\s*{match[3]}\]')
        cleaned_latex = tag_re.sub(lambda _: f"\n\n![]({svg_uri})\n\n", cleaned_latex, count=1)

    # 4. Process Tier 4: OpenCV Whitening Crop
    crop_pattern = r'\[CROP_DIAGRAM:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    for match in re.findall(crop_pattern, cleaned_latex):
        coords = [int(c) for c in match]
        b64_img = crop_and_clean_diagram(image, coords, aggressive_whitening=aggressive_whitening)
        tag_re = re.compile(rf'\[CROP_DIAGRAM:\s*{match[0]},\s*{match[1]},\s*{match[2]},\s*{match[3]}\]')
        cleaned_latex = tag_re.sub(lambda _: f"\n\n![]({b64_img})\n\n", cleaned_latex, count=1)

    return {
        "latex": cleaned_latex,
        "text": raw_text
    }