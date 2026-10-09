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

# Replace with your actual live Render API URL (no trailing slash!)
API_BASE_URL = "https://snaptex001.streamlit.app"

st.title("📄 SnapTex")
st.subheader("Convert handwritten notes & math formulas into editable LaTeX & Word docs")


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def compress_image(uploaded_file, max_dimension=1600, quality=85):
    """
    Resizes and compresses large images taken on mobile phones
    to prevent HTTP 413 (Request Entity Too Large) errors.
    """
    image = Image.open(uploaded_file)

    # Convert RGBA/Palette images to RGB before saving as JPEG
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    # Resize while maintaining aspect ratio
    image.thumbnail((max_dimension, max_dimension))

    # Save to memory stream as compressed JPEG
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
    # Preview uploaded image
    st.image(uploaded_file, caption="Uploaded Document", use_column_width=True)

    if st.button("Process Document", type="primary"):
        with st.spinner("Processing document & converting formulas..."):
            try:
                # 1. Compress image to stay within server payload limits
                compressed_bytes = compress_image(uploaded_file)
                files = {"file": ("document.jpg", compressed_bytes, "image/jpeg")}

                # 2. Call live FastAPI backend endpoint
                response = requests.post(f"{API_BASE_URL}/process-document", files=files)

                if response.status_code == 200:
                    data = response.json()

                    st.success("Document processed successfully!")

                    # Display detected text & LaTeX output
                    st.subheader("Extracted LaTeX & Text")
                    latex_content = data.get("latex", data.get("text", ""))
                    st.code(latex_content, language="latex")

                    # Display image quality metrics if returned
                    if "blur_score" in data:
                        st.caption(f"Image Blur Score: {data['blur_score']:.2f}")

                    # Option to download generated Word document (.docx)
                    if "docx_base64" in data or "download_url" in data:
                        # Handle export request if backend provides export endpoint
                        export_resp = requests.post(
                            f"{API_BASE_URL}/export-docx",
                            json={"latex": latex_content}
                        )
                        if export_resp.status_code == 200:
                            st.download_button(
                                label="📥 Download Word Document (.docx)",
                                data=export_resp.content,
                                file_name="snaptex_output.docx",
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            )
                else:
                    st.error(f"Error {response.status_code}: {response.text}")

            except requests.exceptions.ConnectionError:
                st.error("Could not connect to backend server. Please verify the API_BASE_URL in app.py.")
            except Exception as e:
                st.error(f"An unexpected error occurred: {str(e)}")