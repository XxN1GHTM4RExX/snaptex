"""Convert HTML tables inside Markdown into pandoc grid tables.

Why: the OCR engine emits tables as HTML so the editor can render lists inside
cells, but pandoc's Markdown reader **drops raw HTML blocks**, so a docx/tex
export would silently lose the table.

Pipe tables were tried first and rejected: pandoc folds `<br>` inside a pipe
cell into the surrounding run, so bulleted cells collapse into one line. Grid
tables carry real block content, so bullets stay bullet lists in Word.
"""

import re
from html.parser import HTMLParser

_TABLE_RE = re.compile(r"<table\b[\s\S]*?</table>", re.IGNORECASE)


class _TableParser(HTMLParser):
    """Collects rows of cells; each cell is a list of text lines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[list[str]]] = []
        self._row: list[list[str]] | None = None
        self._cell: list[str] | None = None
        self._list_depth = 0
        self._skip_depth = 0  # inside a math node whose latex was already emitted

    # -- cell line helpers -------------------------------------------------
    def _newline(self) -> None:
        if self._cell is not None and (not self._cell or self._cell[-1] != ""):
            self._cell.append("")

    def _append(self, text: str) -> None:
        if self._cell is None:
            return
        if not self._cell:
            self._cell.append("")
        self._cell[-1] += text

    # -- parser hooks ------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)

        if tag == "tr":
            self._row = []
            return
        if tag in ("td", "th") and self._row is not None:
            self._cell = []
            return
        if self._cell is None:
            return

        if a.get("data-type") == "inline-math":
            self._append(f"${a.get('data-latex', '').strip()}$")
            self._skip_depth += 1
            return
        if a.get("data-type") == "block-math":
            tex = a.get("data-latex", "").strip()
            self._newline()
            self._append(f"$${tex}$$")
            self._newline()
            self._skip_depth += 1
            return

        if tag in ("ul", "ol"):
            self._list_depth += 1
        elif tag == "li":
            self._newline()
            indent = "  " * max(0, self._list_depth - 1)
            self._append(f"{indent}- ")
        elif tag in ("br", "p", "div"):
            self._newline()
        elif tag in ("strong", "b"):
            self._append("**")
        elif tag in ("em", "i"):
            self._append("*")
        elif tag == "code":
            self._append("`")

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag in ("span", "div"):
                self._skip_depth -= 1
            return
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(self._cell)  # type: ignore[union-attr]
            self._cell = None
            return
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            return
        if self._cell is None:
            return

        if tag in ("ul", "ol"):
            self._list_depth = max(0, self._list_depth - 1)
            self._newline()
        elif tag == "li":
            self._newline()
        elif tag in ("strong", "b"):
            self._append("**")
        elif tag in ("em", "i"):
            self._append("*")
        elif tag == "code":
            self._append("`")

    def handle_data(self, data):
        if self._cell is not None and not self._skip_depth:
            self._append(re.sub(r"\s+", " ", data))


def _norm_cell(lines: list[str]) -> list[str]:
    cleaned = [line.rstrip().replace("|", "\\|") for line in lines]
    # drop leading/trailing blank lines, collapse doubles
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    out: list[str] = []
    for line in cleaned:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return out or [""]


def html_table_to_grid(html: str) -> str:
    parser = _TableParser()
    parser.feed(html)
    parser.close()

    rows = [[_norm_cell(cell) for cell in row] for row in parser.rows if row]
    rows = [row for row in rows if any("".join(c).strip() for c in row)]
    if not rows:
        return ""

    width_cols = max(len(row) for row in rows)
    rows = [row + [[""]] * (width_cols - len(row)) for row in rows]

    col_w = [3] * width_cols
    for row in rows:
        for i, cell in enumerate(row):
            for line in cell:
                col_w[i] = max(col_w[i], len(line))

    def border(char: str) -> str:
        return "+" + "+".join(char * (w + 2) for w in col_w) + "+"

    def render_row(cell_lines: list[list[str]]) -> list[str]:
        height = max(len(c) for c in cell_lines)
        lines = []
        for ln in range(height):
            parts = []
            for i, cell in enumerate(cell_lines):
                text = cell[ln] if ln < len(cell) else ""
                parts.append(f" {text.ljust(col_w[i])} ")
            lines.append("|" + "|".join(parts) + "|")
        return lines

    out = [border("-")]
    out += render_row(rows[0])
    out.append(border("="))
    for row in rows[1:]:
        out += render_row(row)
        out.append(border("-"))

    return "\n\n" + "\n".join(out) + "\n\n"


def html_tables_to_grid_markdown(text: str) -> str:
    """Replaces every <table> block in `text` with an equivalent pandoc grid table."""
    if not text or "<table" not in text.lower():
        return text
    return _TABLE_RE.sub(lambda m: html_table_to_grid(m.group(0)), text)
