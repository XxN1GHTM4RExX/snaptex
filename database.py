import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase environment variables (SUPABASE_URL, SUPABASE_KEY) are missing.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def save_transcription(filename: str, markdown_content: str, blur_score: float, whitening_enabled: bool) -> dict:
    """Saves a transcription record to the Supabase database."""
    try:
        supabase = get_supabase_client()
        data = {
            "filename": filename,
            "markdown_content": markdown_content,
            "blur_score": blur_score,
            "whitening_enabled": whitening_enabled
        }
        response = supabase.table("transcriptions").insert(data).execute()
        return response.data[0] if response.data else {}
    except Exception as e:
        print(f"Database insertion failed: {e}")
        return {}


def fetch_recent_transcriptions(limit: int = 10) -> list:
    """Fetches the most recent transcriptions from the database."""
    try:
        supabase = get_supabase_client()
        response = supabase.table("transcriptions").select("*").order("created_at", desc=True).limit(limit).execute()
        return response.data or []
    except Exception as e:
        print(f"Database fetch failed: {e}")
        return []