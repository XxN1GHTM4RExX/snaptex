import io
import tempfile
import os
import pypandoc


def create_docx_from_transcription(transcription_text: str, filename: str = "SnapTex_Doc") -> io.BytesIO:
    """
    Converts Gemini's Markdown + LaTeX transcription directly into a native Word (.docx)
    document with formatted equations using Pandoc.
    """
    # Create temporary input (.md) and output (.docx) files
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as md_file:
        md_file.write(transcription_text)
        md_path = md_file.name

    docx_path = md_path.replace(".md", ".docx")

    try:
        # Pandoc converts Markdown + LaTeX directly into DOCX with native Word math elements
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

    finally:
        # Clean up temporary files
        if os.path.exists(md_path):
            os.remove(md_path)
        if os.path.exists(docx_path):
            os.remove(docx_path)