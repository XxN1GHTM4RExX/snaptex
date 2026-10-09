import streamlit as st
import requests

# Set page configuration
st.set_page_config(
    page_title="SnapTex - Academic Document Processor",
    page_icon="📄",
    layout="centered"
)

# Backend API URLs
# Replace http://127.0.0.1:8000 with your actual Render API URL
API_BASE_URL = "https://snaptex-api.onrender.com"
PROCESS_URL = f"{API_BASE_URL}/process-document"
EXPORT_URL = f"{API_BASE_URL}/export-docx"

st.title("📄 SnapTex Document OCR")
st.write("Upload a handwritten or printed academic document to convert it into editable text and LaTeX equations.")

# File Uploader
uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Display uploaded image preview
    st.image(uploaded_file, caption="Uploaded Document", use_column_width=True)

    if st.button("Process Document", type="primary"):
        with st.spinner("Analyzing image quality and running OCR..."):
            try:
                # Prepare file payload for FastAPI
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                response = requests.post(PROCESS_URL, files=files)

                if response.status_code == 200:
                    data = response.json()

                    if data.get("is_blurry"):
                        st.error(f"❌ Document Rejected: {data.get('message')}")
                        st.info(f"Blur Score: {data.get('blur_score'):.2f} (Threshold: 150.0)")
                    else:
                        st.success("✅ Document processed successfully!")
                        st.session_state["transcription"] = data.get("transcription")
                        st.session_state["filename"] = uploaded_file.name.split('.')[0]
                else:
                    st.error(f"Error {response.status_code}: {response.text}")

            except requests.exceptions.ConnectionError:
                st.error(
                    "Could not connect to the FastAPI backend. Ensure your Uvicorn server is running on http://127.0.0.1:8000.")

# Display transcription and export options if available
if "transcription" in st.session_state and st.session_state["transcription"]:
    st.subheader("Transcribed Content & LaTeX")

    # Display editable text area containing the transcription
    transcription_text = st.text_area(
        "Edit transcription before export if needed:",
        value=st.session_state["transcription"],
        height=300
    )

    st.subheader("Rendered Preview")
    st.markdown(transcription_text)

    # Download DOCX Button
    if st.button("Generate & Download DOCX"):
        with st.spinner("Generating Word document with Pandoc..."):
            try:
                payload = {
                    "transcription": transcription_text,
                    "filename": st.session_state.get("filename", "SnapTex_Doc")
                }
                export_response = requests.post(EXPORT_URL, data=payload)

                if export_response.status_code == 200:
                    st.download_button(
                        label="💾 Click Here to Save .docx File",
                        data=export_response.content,
                        file_name=f"{st.session_state.get('filename', 'SnapTex_Doc')}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                else:
                    st.error("Failed to generate DOCX file.")
            except Exception as e:
                st.error(f"Export error: {str(e)}")