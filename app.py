import streamlit as st
import requests
import io

# Set Page Config
st.set_page_config(page_title="SnapTex - OCR Note Processing", page_icon="📝", layout="centered")

API_BASE_URL = "https://your-render-app-url.onrender.com"  # Replace with your actual Render URL

st.title("SnapTex 📝")
st.caption("Convert handwritten notes and mathematical formulas into formatted text and LaTeX.")


# Silent wakeup ping to eliminate Render free tier cold starts
@st.cache_data(ttl=300)
def wakeup_backend():
    try:
        requests.get(f"{API_BASE_URL}/", timeout=5)
    except Exception:
        pass


wakeup_backend()

# File Uploader
uploaded_file = st.file_uploader("Upload an image of your handwritten notes", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, caption="Uploaded Document", use_column_width=True)

    if st.button("Process Document", type="primary"):
        with st.spinner("Processing document & converting formulas..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                # Extended 120s timeout to allow Render boot + processing time
                response = requests.post(f"{API_BASE_URL}/process-document", files=files, timeout=120)

                if response.status_code == 200:
                    data = response.json()
                    st.session_state["extracted_result"] = data.get("latex", "")
                    st.session_state["blur_score"] = data.get("blur_score", None)
                else:
                    st.error(f"Backend error: {response.status_code} - {response.text}")
            except requests.exceptions.Timeout:
                st.error(
                    "The backend server timed out while starting up or calling AI servers. Please click 'Process Document' again!")
            except Exception as e:
                st.error(f"Could not connect to backend server: {str(e)}")

# Display Results and Export Options
if "extracted_result" in st.session_state and st.session_state["extracted_result"]:
    result_text = st.session_state["extracted_result"]

    if "blur_score" in st.session_state and st.session_state["blur_score"] is not None:
        st.info(f"Image Quality Score: {st.session_state['blur_score']:.2f}")

    st.subheader("Extracted Output")
    st.markdown(result_text)

    # Guardrail: Only call export if output is valid transcribed text, not an error string
    if not result_text.startswith("Error") and not result_text.startswith("Google AI") and not result_text.startswith(
            "OCR Processing"):

        # Call backend /export-docx route for styled document generation
        try:
            export_response = requests.post(
                f"{API_BASE_URL}/export-docx",
                json={"latex": result_text},
                timeout=30
            )

            if export_response.status_code == 200:
                st.download_button(
                    label="📄 Download as Word Document (.docx)",
                    data=export_response.content,
                    file_name="SnapTex_Notes.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
            else:
                st.warning("Word export service is currently unavailable.")
        except Exception:
            st.warning("Could not reach export engine.")