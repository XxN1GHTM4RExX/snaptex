import streamlit as st
import requests
import pypandoc
import tempfile
import os
import re
import pandas as pd
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from supabase import create_client

# Backend Render API URL
BACKEND_URL = "https://snaptex.onrender.com"  # Update with your exact Render backend URL

# Supabase Credentials for Direct Auth Client in Streamlit
SUPABASE_URL = "https://vjlnjwlarhznomhxtcgd.supabase.co"
SUPABASE_KEY = "sb_publishable_vo0NHPSxsNswuWX0BA34ew_RmsOFfhP"

st.set_page_config(page_title="SnapTex", page_icon="📐", layout="centered")


@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


supabase = init_supabase()

st.title("SnapTex - Mathematical OCR & Export")


def parse_markdown_to_blocks(markdown_text: str) -> list:
    """Parses raw Markdown content into visual blocks (text blocks vs. table blocks)."""
    blocks = []
    lines = markdown_text.split("\n")
    current_text = []
    table_lines = []
    in_table = False

    for line in lines:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if current_text:
                blocks.append({"type": "text", "content": "\n".join(current_text)})
                current_text = []
            in_table = True
            table_lines.append(line)
        else:
            if in_table:
                blocks.append({"type": "table", "content": "\n".join(table_lines)})
                table_lines = []
                in_table = False
            current_text.append(line)

    if current_text:
        blocks.append({"type": "text", "content": "\n".join(current_text)})
    if table_lines:
        blocks.append({"type": "table", "content": "\n".join(table_lines)})

    return blocks


def markdown_table_to_df(table_str: str) -> pd.DataFrame:
    """Converts a raw Markdown table string into a Pandas DataFrame for GUI editing."""
    lines = [line.strip().strip("|") for line in table_str.strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return pd.DataFrame()

    headers = [col.strip() for col in lines[0].split("|")]
    data_rows = []
    for line in lines[1:]:
        if re.match(r"^[\s\:\|-]+$", line):
            continue
        row = [cell.strip() for cell in line.split("|")]
        if len(row) < len(headers):
            row.extend([""] * (len(headers) - len(row)))
        data_rows.append(row[:len(headers)])

    return pd.DataFrame(data_rows, columns=headers)


def df_to_markdown_table(df: pd.DataFrame) -> str:
    """Converts an edited Pandas DataFrame back into Markdown table format."""
    return df.to_markdown(index=False)


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


# Session state initialization for user session
if "auth_token" not in st.session_state:
    st.session_state["auth_token"] = None
if "user_email" not in st.session_state:
    st.session_state["user_email"] = None
if "active_filename" not in st.session_state:
    st.session_state["active_filename"] = "SnapTex_Transcribed_Notes"
if "edit_mode" not in st.session_state:
    st.session_state["edit_mode"] = False

# --- SIDEBAR: USER AUTHENTICATION ---
st.sidebar.header("👤 Account")

if not st.session_state["auth_token"]:
    auth_mode = st.sidebar.radio("Choice", ["Login", "Sign Up"])
    email = st.sidebar.text_input("Email")
    password = st.sidebar.text_input("Password", type="password")

    if auth_mode == "Login":
        if st.sidebar.button("Log In"):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state["auth_token"] = res.session.access_token
                st.session_state["user_email"] = res.user.email
                st.sidebar.success(f"Welcome back, {res.user.email}!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Login failed: {str(e)}")
    else:
        if st.sidebar.button("Sign Up"):
            try:
                res = supabase.auth.sign_up({"email": email, "password": password})
                st.sidebar.success("Account created! Check your email to confirm registration or log in directly.")
            except Exception as e:
                st.sidebar.error(f"Sign up failed: {str(e)}")
else:
    st.sidebar.write(f"Logged in as: **{st.session_state['user_email']}**")
    if st.sidebar.button("Log Out"):
        supabase.auth.sign_out()
        st.session_state["auth_token"] = None
        st.session_state["user_email"] = None
        st.session_state["latex_output"] = None
        st.session_state["active_filename"] = "SnapTex_Transcribed_Notes"
        st.rerun()

# --- SIDEBAR: PROCESSING SETTINGS ---
st.sidebar.markdown("---")
st.sidebar.header("Processing Settings")
aggressive_whitening = st.sidebar.checkbox(
    "Aggressive Diagram Whitening",
    value=False,
    help="Enable this for exam papers, worksheets, and line drawings to force backgrounds to pure white."
)

# --- SIDEBAR: USER-ISOLATED DOCUMENT HISTORY ---
st.sidebar.markdown("---")
st.sidebar.header("📚 Document History")

if st.session_state["auth_token"]:
    if st.sidebar.button("🔄 Refresh History"):
        st.rerun()

    try:
        headers = {"Authorization": f"Bearer {st.session_state['auth_token']}"}
        history_response = requests.get(f"{BACKEND_URL}/history", headers=headers, timeout=10)

        if history_response.status_code == 200:
            history_data = history_response.json().get("history", [])
            if history_data:
                doc_options = {
                    f"{item.get('filename', 'Doc')} ({item.get('created_at', '')[:10]})": item
                    for item in history_data
                }

                selected_label = st.sidebar.selectbox("Select a previous transcription:", list(doc_options.keys()))
                selected_doc = doc_options[selected_label]

                col1, col2 = st.sidebar.columns(2)

                if col1.button("📖 Load"):
                    st.session_state["latex_output"] = selected_doc.get("markdown_content", "")
                    st.session_state["active_filename"] = selected_doc.get("filename", "SnapTex_Notes")
                    st.sidebar.success("Loaded!")
                    st.rerun()

                if col2.button("🗑️ Delete"):
                    doc_id = selected_doc.get("id")
                    del_res = requests.delete(f"{BACKEND_URL}/history/{doc_id}", headers=headers)
                    if del_res.status_code == 200:
                        st.sidebar.success("Deleted!")
                        st.session_state["latex_output"] = None
                        st.rerun()
                    else:
                        st.sidebar.error("Could not delete record.")

                # Rename Section
                new_title = st.sidebar.text_input("Rename selected document:", value=selected_doc.get("filename", ""))
                if st.sidebar.button("✏️ Save New Name"):
                    if new_title.strip():
                        doc_id = selected_doc.get("id")
                        rename_res = requests.patch(
                            f"{BACKEND_URL}/history/{doc_id}",
                            data={"new_filename": new_title.strip()},
                            headers=headers
                        )
                        if rename_res.status_code == 200:
                            st.sidebar.success("Renamed!")
                            st.session_state["active_filename"] = new_title.strip()
                            st.rerun()
                        else:
                            st.sidebar.error("Rename failed.")
            else:
                st.sidebar.info("No past transcriptions found.")
        else:
            st.sidebar.warning("Could not fetch document history.")
    except Exception as e:
        st.sidebar.warning("Database offline or unreachable.")
else:
    st.sidebar.info("Log in to access your saved document history.")

# --- MAIN AREA: UPLOAD & PROCESS ---
uploaded_file = st.file_uploader("Upload an image containing mathematical notes...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded Document", width="stretch")

    if st.button("Process Document", type="primary"):
        if not st.session_state["auth_token"]:
            st.error("Please log in from the sidebar before processing documents!")
        else:
            with st.spinner("Processing OCR via Gemini Engine..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    data_payload = {"aggressive_whitening": str(aggressive_whitening).lower()}
                    headers = {"Authorization": f"Bearer {st.session_state['auth_token']}"}

                    response = requests.post(
                        f"{BACKEND_URL}/process-document",
                        files=files,
                        data=data_payload,
                        headers=headers,
                        timeout=60
                    )

                    if response.status_code == 200:
                        data = response.json()
                        latex_content = data.get("latex", "")
                        blur_score = data.get("blur_score", 0.0)

                        st.success("Extraction Complete & Saved to Your Private Account!")
                        st.info(f"Image Quality Score: {blur_score:.2f}")

                        st.session_state["latex_output"] = latex_content
                        st.session_state["active_filename"] = uploaded_file.name.rsplit('.', 1)[0]
                    else:
                        st.error(f"Backend error: {response.status_code}\n{response.text}")
                except Exception as e:
                    st.error(f"Failed to connect to backend: {str(e)}")

# --- MAIN AREA: IN-APP VISUAL EDITOR & EXPORT ---
if "latex_output" in st.session_state and st.session_state["latex_output"]:
    st.markdown("---")

    col_title, col_btn = st.columns([3, 1])
    col_title.subheader(f"Document: {st.session_state['active_filename']}")

    if st.session_state["edit_mode"]:
        if col_btn.button("👁️ View Preview", type="secondary"):
            st.session_state["edit_mode"] = False
            st.rerun()
    else:
        if col_btn.button("✏️ Visual Edit", type="primary"):
            st.session_state["edit_mode"] = True
            st.rerun()

    # --- MODE 1: VISUAL EDIT MODE ---
    if st.session_state["edit_mode"]:
        st.info("Visual Edit Mode Active: Edit text blocks or table cells directly below.")

        blocks = parse_markdown_to_blocks(st.session_state["latex_output"])
        updated_blocks = []

        for idx, block in enumerate(blocks):
            if block["type"] == "text":
                edited_text = st.text_area(
                    f"Text Block #{idx + 1}",
                    value=block["content"],
                    height=150,
                    key=f"block_text_{idx}"
                )
                updated_blocks.append(edited_text)

            elif block["type"] == "table":
                st.write(f"**Table Block #{idx + 1} (Interactive Grid Editor)**")
                df = markdown_table_to_df(block["content"])

                if not df.empty:
                    edited_df = st.data_editor(
                        df,
                        num_rows="dynamic",
                        key=f"block_table_{idx}",
                        use_container_width=True
                    )
                    updated_blocks.append(df_to_markdown_table(edited_df))
                else:
                    updated_blocks.append(block["content"])

        st.session_state["latex_output"] = "\n\n".join(updated_blocks)

    # --- MODE 2: READ / PREVIEW MODE ---
    else:
        st.subheader("Formatted Preview")
        st.markdown(st.session_state["latex_output"])

    # --- EXPORT SECTION ---
    st.subheader("Export Options")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_file:
            tmp_path = tmp_file.name

        extra_args = []
        if os.path.exists("reference.docx"):
            extra_args.append("--reference-doc=reference.docx")

        pypandoc.convert_text(
            st.session_state["latex_output"],
            to='docx',
            format='markdown+tex_math_dollars',
            outputfile=tmp_path,
            extra_args=extra_args
        )

        apply_table_borders(tmp_path)

        with open(tmp_path, "rb") as f:
            docx_bytes = f.read()

        os.remove(tmp_path)

        download_filename = f"{st.session_state['active_filename']}.docx"

        st.download_button(
            label=f"📄 Download Editable Word Document ({download_filename})",
            data=docx_bytes,
            file_name=download_filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary"
        )
    except Exception as e:
        st.error(f"Word Conversion Error: {str(e)}")