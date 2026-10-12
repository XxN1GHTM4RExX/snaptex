import io
import tempfile
import os
import re
import base64
import pypandoc


def replace_base64_with_temp_files(markdown_text: str, temp_dir: str) -> str:
    """Extracts base64 image strings from Markdown, saves them as temporary PNG files,

    and replaces the markdown image links with absolute file paths for Pandoc.
    """
    pattern = r'!\[\]\(data:image/png;base64,([A-Za-z0-9+/=]+)\)'
    matches = re.findall(pattern, markdown_text)

    processed_text = markdown_text

    for idx, b64_str in enumerate(matches):
        try:
            img_bytes = base64.b64decode(b64_str)
            img_filename = f"diagram_{idx}.png"
            img_path = os.path.join(temp_dir, img_filename)

            with open(img_path, "wb") as f:
                f.write(img_bytes)

            raw_tag = f"![](data:image/png;base64,{b64_str})"
            file_tag = f"![]({img_path})"
            processed_text = processed_text.replace(raw_tag, file_tag)
        except Exception as e:
            print(f"Failed to decode base64 image {idx}: {e}")

    return processed_text


def create_docx_from_transcription(transcription_text: str, filename: str = "SnapTex_Doc") -> io.BytesIO:
    """Converts Gemini's Markdown + LaTeX transcription into a native Word (.docx)

    document with formatted math equations and clean embedded vector images using Pandoc.
    """
    # Create temporary directory for writing markdown and image assets
    with tempfile.TemporaryDirectory() as temp_dir:
        # Pre-process base64 images into physical temp files for Pandoc
        sanitized_markdown = replace_base64_with_temp_files(transcription_text, temp_dir)

        md_path = os.path.join(temp_dir, "input.md")
        docx_path = os.path.join(temp_dir, "output.docx")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(sanitized_markdown)

        # Pandoc converts Markdown + LaTeX directly into native DOCX math elements
        pypandoc.convert_file(
            md_path,
            'docx',
            outputfile=docx_path,
            extra_args=['--from=markdown+tex_math_dollars']
        )

        # Read converted bytes into memory buffer
        with open(docx_path, "rb") as f:
            file_stream = io.BytesIO(f.read())
            file_stream.seek(0)

        return file_stream