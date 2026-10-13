import streamlit as st
import requests
import pypandoc
import tempfile
import os
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# Backend Render API URL
BACKEND_URL = "https://snaptex.onrender.com"  # Update with your exact Render backend URL

st.set_page_config(page_title="SnapTex", page_icon="📐", layout="centered")

st.title("SnapTex - Mathematical OCR & Export")


def apply_table_borders(docx_path: str):
    """Parses the generated docx file and forces explicit XML table grid borders
    on every table element.
    """
    doc = Document(docx_path)

    for table in doc.tables:
        tblPr = table._tbl.tblPr
        tblBorders = tblPr.find(qn('w:tblBorders'))
        if tblBorders is not None:
            tblPr.remove(tblBorders)

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


# Sidebar settings for document processing
st.sidebar.header("Processing Settings")
aggressive_whitening = st.sidebar.checkbox(
    "Aggressive Diagram Whitening",
    value=False,
    help="Enable this for exam papers, worksheets, and line drawings to force backgrounds to pure white. Leave unchecked for continuous-tone photos or book scans."
)

# Fetch Recent Transcriptions History from Supabase
st.sidebar.markdown("---")
st.sidebar.header("📚 Document History")

if st.sidebar.button("🔄 Refresh History"):
    st.rerun()

try:
    history_response = requests.get(f"{BACKEND_URL}/history", timeout=10)
    if history_response.status_code == 200:
        history_data = history_response.json().get("history", [])
        if history_data:
            selected_doc = st.sidebar.selectbox(
                "Select a previous transcription:",
                options=history_data,
                format_func=lambda item: f"{item.get('filename', 'Doc')} ({item.get('created_at', '')[:10]})"
            )
            if st.sidebar.button("📖 Load Selected Document"):
                st.session_state["latex_output"] = selected_doc.get("markdown_content", "")
                st.sidebar.success("Loaded from database!")
        else:
            st.sidebar.info("No past transcriptions found.")
    else:
        st.sidebar.warning("Could not fetch document history.")
except Exception as e:
    st.sidebar.warning("Database offline or unreachable.")


uploaded_file = st.file_uploader("Upload an image containing mathematical notes...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded Document", width="stretch")

    if st.button("Process Document", type="primary"):
        with st.spinner("Processing OCR via Gemini Engine..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                data_payload = {"aggressive_whitening": str(aggressive_whitening).lower()}

                response = requests.post(
                    f"{BACKEND_URL}/process-document",
                    files=files,
                    data=data_payload,
                    timeout=60
                )

                if response.status_code == 200:
                    data = response.json()
                    latex_content = data.get("latex", "")
                    blur_score = data.get("blur_score", 0.0)

                    st.success("Extraction Complete & Saved to Database!")
                    st.info(f"Image Quality Score: {blur_score:.2f}")

                    st.subheader("Extracted Output")
                    st.text_area("LaTeX / Markdown Text", latex_content, height=300)

                    # Save to session state for Word export
                    st.session_state["latex_output"] = latex_content
                else:
                    st.error(f"Backend error: {response.status_code}\n{response.text}")
            except Exception as e:
                st.error(f"Failed to connect to backend: {str(e)}")

# Display loaded or extracted transcription
if "latex_output" in st.session_state and st.session_state["latex_output"]:
    st.markdown("---")
    st.subheader("Active Document")
    st.text_area("LaTeX / Markdown Content", st.session_state["latex_output"], height=300, key="active_doc_viewer")

    st.subheader("Export Options")

    try:
        # Create a temporary file path for Pandoc output
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_file:
            tmp_path = tmp_file.name

        # Prepare extra args for Pandoc (use reference.docx if present)
        extra_args = []
        if os.path.exists("reference.docx"):
            extra_args.append("--reference-doc=reference.docx")

        # Convert LaTeX to the temporary file using Streamlit's native Pandoc
        pypandoc.convert_text(
            st.session_state["latex_output"],
            to='docx',
            format='markdown+tex_math_dollars',
            outputfile=tmp_path,
            extra_args=extra_args
        )

        # Post-process docx to force visible table borders via Python XML injection
        apply_table_borders(tmp_path)

        # Read the generated docx file as bytes
        with open(tmp_path, "rb") as f:
            docx_bytes = f.read()

        # Clean up temporary file
        os.remove(tmp_path)

        st.download_button(
            label="📄 Download Native Word Document (.docx)",
            data=docx_bytes,
            file_name="SnapTex_Transcribed_Notes.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary"
        )
    except Exception as e:
        st.error(f"Word Conversion Error: {str(e)}")