import io
import tempfile
import os
import re
import base64
import pypandoc
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _child_or_add(parent, tag: str, before: tuple):
    """Find an OOXML child or create it before the listed successor tags."""
    el = parent.find(qn(tag))
    if el is None:
        el = OxmlElement(tag)
        parent.insert_element_before(el, *before)
    return el


# OOXML child order for the elements we touch. python-docx does not enforce it,
# but Word and stricter readers do.
_TBLW_BEFORE = (
    'w:jc', 'w:tblCellSpacing', 'w:tblInd', 'w:tblBorders', 'w:shd',
    'w:tblLayout', 'w:tblCellMar', 'w:tblLook', 'w:tblCaption', 'w:tblDescription',
)
_LAYOUT_BEFORE = ('w:tblCellMar', 'w:tblLook', 'w:tblCaption', 'w:tblDescription')
_TCMAR_BEFORE = ('w:textDirection', 'w:tcFitText', 'w:vAlign', 'w:hideMark')
_PPR_TAIL = (
    'w:contextualSpacing', 'w:mirrorIndents', 'w:suppressOverlap', 'w:jc',
    'w:textDirection', 'w:textAlignment', 'w:textboxTightWrap', 'w:outlineLvl',
    'w:divId', 'w:cnfStyle', 'w:rPr', 'w:sectPr', 'w:pPrChange',
)


def compact_table_geometry(table):
    """Make pandoc tables fit Word pages without clipped text or page-split rows."""
    tblPr = table._tbl.tblPr

    tblW = _child_or_add(tblPr, 'w:tblW', _TBLW_BEFORE)
    tblW.set(qn('w:w'), '5000')       # percent units: 5000 = 100% of page width
    tblW.set(qn('w:type'), 'pct')

    layout = _child_or_add(tblPr, 'w:tblLayout', _LAYOUT_BEFORE)
    layout.set(qn('w:type'), 'autofit')

    for row in table.rows:
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcMar = _child_or_add(tcPr, 'w:tcMar', _TCMAR_BEFORE)
            for side, value in (('top', 60), ('left', 100), ('bottom', 60), ('right', 100)):
                node = tcMar.find(qn(f'w:{side}'))
                if node is None:
                    node = OxmlElement(f'w:{side}')
                    tcMar.append(node)
                node.set(qn('w:w'), str(value))
                node.set(qn('w:type'), 'dxa')

            for paragraph in cell.paragraphs:
                pPr = paragraph._p.get_or_add_pPr()
                if pPr.find(qn('w:numPr')) is None:
                    continue

                # Word's default ~0.5 in list indent eats narrow grid columns.
                ind = _child_or_add(pPr, 'w:ind', _PPR_TAIL)
                ind.set(qn('w:left'), '260')
                ind.set(qn('w:hanging'), '180')

                spacing = _child_or_add(pPr, 'w:spacing', ('w:ind',) + _PPR_TAIL)
                spacing.set(qn('w:before'), '0')
                spacing.set(qn('w:after'), '40')
                spacing.set(qn('w:line'), '240')
                spacing.set(qn('w:lineRule'), 'auto')


def apply_table_borders(docx_path: str):
    """Parses the generated docx file and forces explicit XML table grid borders
    on every table element, and stops rows splitting across page breaks.
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

        # OOXML fixes child order: tblBorders must precede tblLook.
        tblPr.insert_element_before(
            new_borders,
            'w:shd',
            'w:tblLayout',
            'w:tblCellMar',
            'w:tblLook',
            'w:tblCaption',
            'w:tblDescription',
        )

        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            # And cantSplit must precede trHeight / tblHeader.
            trPr.insert_element_before(
                OxmlElement('w:cantSplit'),
                'w:trHeight',
                'w:tblHeader',
                'w:tblCellSpacing',
                'w:jc',
                'w:hidden',
            )

        compact_table_geometry(table)

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