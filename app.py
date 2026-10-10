import io
import requests
import streamlit as st
from PIL import Image

# -----------------------------------------------------------------------------
# App Configuration & Backend Setup
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="SnapTex - Academic Document Processor",
    page_icon="📄",
    layout="centered"
)

# Ensure this matches your live Render API URL without a trailing slash!
API_BASE_URL = "https://snaptex.onrender.com"

st.title("📄 SnapTex")
st.subheader("Convert handwritten notes & math formulas into editable LaTeX & Word docs")

# Initialize Session State to cache results and prevent duplicate API calls
if "processed_data" not in st.session_state:
    st.session_state.processed_data = None


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def compress_image(uploaded_file, max_dimension=1600, quality=85):
    """
    Resizes and compresses large images taken on mobile phones
    to prevent HTTP 413 (Request Entity Too Large) errors.
    """
    image = Image.open(uploaded_file)
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    image.thumbnail((max_dimension, max_dimension))
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format="JPEG", quality=quality)
    return img_byte_arr.getvalue()


# -----------------------------------------------------------------------------
# Interface & User Interactions
# -----------------------------------------------------------------------------
uploaded_file = st.file_uploader(
    "Upload a document photo or handwritten page",
    type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded Document", use_column_width=True)

    if st.button("Process Document", type="primary"):
        with st.spinner("Processing document & converting formulas..."):
            try:
                # 1. Compress image
                compressed_bytes = compress_image(uploaded_file)
                files = {"file": ("document.jpg", compressed_bytes, "image/jpeg")}

                # 2. Call backend OCR endpoint (60s timeout to allow Render wake-ups)
                response = requests.post(f"{API_BASE_URL}/process-document", files=files, timeout=60)

                if response.status_code != 200:
                    st.error(f"Backend Server Error ({response.status_code}):")
                    st.text(response.text[:500])
                else:
                    try:
                        # Cache processed result in session state
                        st.session_state.processed_data = response.json()
                        st.success("Document processed successfully!")
                    except ValueError:
                        st.error("Received non-JSON output from backend.")
                        st.text(response.text[:500])

            except requests.exceptions.Timeout:
                st.error("The backend server timed out while starting up or calling AI servers. Please click 'Process Document' again!")
            except requests.exceptions.ConnectionError:
                st.error(f"Could not reach backend at '{API_BASE_URL}'. Please verify that the Render web service is live.")
            except Exception as e:
                st.error(f"An unexpected error occurred: {str(e)}")

# Display cached OCR output if available
if st.session_state.processed_data:
    data = st.session_state.processed_data
    latex_content = data.get("latex") or data.get("text") or data.get("extracted_text") or "No output returned."

    st.subheader("Extracted LaTeX & Text")
    st.code(latex_content, language="latex")

    if "blur_score" in data:
        st.caption(f"Image Blur Score: {data['blur_score']:.2f}")

    # Export to DOCX section
    if latex_content and not latex_content.startswith("Error") and not latex_content.startswith("Rate Limit"):
        st.divider()
        with st.spinner("Preparing Word Document download..."):
            try:
                export_resp = requests.post(
                    f"{API_BASE_URL}/export-docx",
                    json={"latex": latex_content},
                    timeout=30
                )
                if export_resp.status_code == 200:
                    st.download_button(
                        label="📥 Download Word Document (.docx)",
                        data=export_resp.content,
                        file_name="snaptex_output.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                else:
                    st.warning("Could not generate .docx file automatically, but you can copy the LaTeX code above!")
            except Exception:
                st.warning("Could not reach export endpoint.")