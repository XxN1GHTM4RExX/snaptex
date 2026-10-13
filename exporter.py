import io
import tempfile
import os
import re
import base64
import pypandoc
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def apply_table_borders(docx_path: str):
    """Parses the generated docx file and forces explicit XML table grid borders
    on every table element.
    """
    doc = Document(docx_path)

    for table in doc.tables:
        tblPr = table._tbl.tblPr
        # Remove existing borders element if present
        tblBorders = tblPr.find(qn('w:tblBorders'))
        if tblBorders is not None:
            tblPr.remove(tblBorders)

        # Build explicit border XML tags
        new_borders = OxmlElement('w:tblBorders')
        for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '4')  # 0.5 pt line thickness
            border.set(qn('w:space'), '0')
            border.set(qn('w:color'), '000000')  # Solid black
            new_borders.append(border)

        tblPr.append(new_borders)

    doc.save(docx_path)


def replace_base64_with_temp_files(markdown_text: str, temp_dir: str) -> str:
    """Extracts base64 image strings from Markdown, saves them as temporary PNG files,
    and replaces the markdown image links with normalized absolute file paths for Pandoc.
    """
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

        # Force visible borders directly on the output XML
        apply_table_borders(docx_path)

        with open(docx_path, "rb") as f:
            file_stream = io.BytesIO(f.read())
            file_stream.seek(0)

        return file_stream