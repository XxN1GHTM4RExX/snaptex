import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_supabase_client(access_token: str = None) -> Client:
    """Returns a Supabase client. If a user access token is provided,
    it sets the authorization header to enforce Row Level Security (RLS).
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase environment variables (SUPABASE_URL, SUPABASE_KEY) are missing.")

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    if access_token:
        # Attach user token so Supabase knows who is executing the query
        client.postgrest.auth(access_token)

    return client


def save_transcription(
        filename: str,
        markdown_content: str,
        blur_score: float,
        whitening_enabled: bool,
        user_id: str,
        access_token: str
) -> dict:
    """Saves a transcription record to the Supabase database under the user's ID."""
    try:
        supabase = get_supabase_client(access_token=access_token)
        data = {
            "filename": filename,
            "markdown_content": markdown_content,
            "blur_score": blur_score,
            "whitening_enabled": whitening_enabled,
            "user_id": user_id
        }
        response = supabase.table("transcriptions").insert(data).execute()
        return response.data[0] if response.data else {}
    except Exception as e:
        print(f"Database insertion failed: {e}")
        return {}


def fetch_recent_transcriptions(access_token: str, limit: int = 10) -> list:
    """Fetches the most recent transcriptions for the authenticated user."""
    try:
        supabase = get_supabase_client(access_token=access_token)
        response = supabase.table("transcriptions").select("*").order("created_at", desc=True).limit(limit).execute()
        return response.data or []
    except Exception as e:
        print(f"Database fetch failed: {e}")
        return []


def update_transcription_filename(transcription_id: str, new_filename: str, access_token: str) -> dict:
    """Updates the filename of a specific transcription record in-place."""
    try:
        supabase = get_supabase_client(access_token=access_token)
        response = supabase.table("transcriptions").update({"filename": new_filename}).eq("id",
                                                                                          transcription_id).execute()

        if response.data and len(response.data) > 0:
            return response.data[0]

        print(f"No matching row found for transcription ID: {transcription_id}")
        return None
    except Exception as e:
        print(f"Database update failed: {e}")
        return None