import io
import tempfile
import os
import re
import base64
import pypandoc


def replace_base64_with_temp_files(markdown_text: str, temp_dir: str) -> str:
    """Extracts base64 image strings from Markdown, saves them as temporary PNG files,
    and replaces the markdown image links with normalized absolute file paths for Pandoc.
    """
    # Regex matches both empty ![] and alt text ![text](data:image/...) across png, jpg, jpeg
    pattern = r'!\[(.*?)\]\(data:image/(?:png|jpeg|jpg);base64,([A-Za-z0-9+/=]+)\)'
    matches = re.findall(pattern, markdown_text)

    processed_text = markdown_text

    for idx, (alt_text, b64_str) in enumerate(matches):
        try:
            img_bytes = base64.b64decode(b64_str)
            img_filename = f"diagram_{idx}.png"
            img_path = os.path.join(temp_dir, img_filename).replace("\\", "/")

            with open(img_path, "wb") as f:
                f.write(img_bytes)

            # Reconstruct the original tag to replace with local image path
            raw_pattern = re.compile(
                r'!\[\s*' + re.escape(alt_text) + r'\s*\]\(data:image/(?:png|jpeg|jpg);base64,' + re.escape(b64_str) + r'\)'
            )
            file_tag = f"![{alt_text}]({img_path})"
            processed_text = raw_pattern.sub(file_tag, processed_text, count=1)
        except Exception as e:
            print(f"Failed to decode base64 image {idx}: {e}")

    return processed_text


def create_docx_from_transcription(transcription_text: str, filename: str = "SnapTex_Doc") -> io.BytesIO:
    """Converts Gemini's Markdown + LaTeX transcription into a native Word (.docx)

    document with formatted math equations, clean embedded images, and custom table borders.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        sanitized_markdown = replace_base64_with_temp_files(transcription_text, temp_dir)

        md_path = os.path.join(temp_dir, "input.md")
        docx_path = os.path.join(temp_dir, "output.docx")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(sanitized_markdown)

        # Path to your reference template (e.g., located in your backend root directory)
        ref_doc_path = os.path.abspath("reference.docx")

        extra_args = ['--from=markdown+tex_math_dollars']
        if os.path.exists(ref_doc_path):
            extra_args.append(f'--reference-doc={ref_doc_path}')

        pypandoc.convert_file(
            md_path,
            'docx',
            outputfile=docx_path,
            extra_args=extra_args
        )

        with open(docx_path, "rb") as f:
            file_stream = io.BytesIO(f.read())
            file_stream.seek(0)

        return file_stream