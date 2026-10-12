import streamlit as st
import requests
import pypandoc
import tempfile
import os

# Backend Render API URL
BACKEND_URL = "https://snaptex.onrender.com"  # Update with your exact Render backend URL

st.set_page_config(page_title="SnapTex", page_icon="📐", layout="centered")

st.title("SnapTex - Mathematical OCR & Export")

uploaded_file = st.file_uploader("Upload an image containing mathematical notes...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded Document", use_container_width=True)

    if st.button("Process Document", type="primary"):
        with st.spinner("Processing OCR via Gemini Engine..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                response = requests.post(f"{BACKEND_URL}/process-document", files=files)

                if response.status_code == 200:
                    data = response.json()
                    latex_content = data.get("latex", "")
                    blur_score = data.get("blur_score", 0.0)

                    st.success("Extraction Complete!")
                    st.info(f"Image Quality Score: {blur_score:.2f}")

                    st.subheader("Extracted Output")
                    st.text_area("LaTeX / Markdown Text", latex_content, height=300)

                    # Save to session state for Word export
                    st.session_state["latex_output"] = latex_content
                else:
                    st.error(f"Backend error: {response.status_code}\n{response.text}")
            except Exception as e:
                st.error(f"Failed to connect to backend: {str(e)}")

# Native Pandoc DOCX Export running locally on Streamlit Cloud
if "latex_output" in st.session_state and st.session_state["latex_output"]:
    st.markdown("---")
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