import streamlit as st
import requests
import pypandoc
import io

BACKEND_URL = "https://your-render-app.onrender.com"  # Replace with your actual Render URL

st.title("SnapTex - Mathematical OCR")

uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded Document", use_column_width=True)

    if st.button("Process Document"):
        with st.spinner("Processing OCR with Gemini..."):
            try:
                # 1. Send image to Render for Gemini OCR
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                response = requests.post(f"{BACKEND_URL}/process-document", files=files)

                if response.status_code == 200:
                    data = response.json()
                    latex_content = data.get("latex", "")

                    st.success("OCR Extraction Complete!")
                    st.text_area("Extracted LaTeX / Text", latex_content, height=300)

                    # Store in session state for export button
                    st.session_state["latex_output"] = latex_content
                else:
                    st.error(f"Backend error: {response.status_code} - {response.text}")
            except Exception as e:
                st.error(f"Failed to connect to backend: {str(e)}")

# 2. Convert to DOCX directly on Streamlit Cloud using Streamlit's local Pandoc
if "latex_output" in st.session_state and st.session_state["latex_output"]:
    if st.button("Export to Word (.docx)"):
        with st.spinner("Generating native Word equations via Pandoc..."):
            try:
                # Direct local Pandoc conversion on Streamlit Cloud
                docx_bytes = pypandoc.convert_text(
                    st.session_state["latex_output"],
                    to='docx',
                    format='markdown+tex_math_dollars',
                    outputfile=None
                )

                st.download_button(
                    label="Download .docx File",
                    data=docx_bytes,
                    file_name="SnapTex_Transcribed_Notes.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
            except Exception as e:
                st.error(f"Pandoc conversion failed on Streamlit: {str(e)}")