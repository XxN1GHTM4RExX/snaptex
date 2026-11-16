import os
import time
from typing import List, Dict, Optional, Any


class APIKeyPool:
    """Manages a pool of API keys with round-robin selection and dynamic rate-limit cooldown tracking."""

    def __init__(self, prefixes: List[str]):
        self.prefixes = prefixes
        self.keys: List[Dict[str, Any]] = []
        self.current_idx = 0
        self.reload_keys()

    def reload_keys(self):
        """Loads any matching environment variables by exact prefix or prefix + suffix (e.g., _1, _2, -1, -2)."""
        self.keys = []
        seen_values = set()

        for env_name, env_val in sorted(os.environ.items()):
            if not env_val or not env_val.strip():
                continue

            for prefix in self.prefixes:
                if (
                    env_name == prefix
                    or env_name.startswith(f"{prefix}_")
                    or env_name.startswith(f"{prefix}-")
                ):
                    cleaned = env_val.strip()
                    if cleaned not in seen_values:
                        seen_values.add(cleaned)
                        self.keys.append({"key": cleaned, "cooldown_until": 0.0})
                    break

    def get_key(self) -> Optional[str]:
        """Returns the next available API key not currently on cooldown, or None if all are exhausted."""
        if not self.keys:
            self.reload_keys()
            if not self.keys:
                return None

        now = time.time()
        num_keys = len(self.keys)

        for _ in range(num_keys):
            candidate = self.keys[self.current_idx]
            self.current_idx = (self.current_idx + 1) % num_keys
            if candidate["cooldown_until"] <= now:
                return candidate["key"]

        return None

    def available_count(self) -> int:
        """Returns how many keys in this pool are currently off cooldown."""
        if not self.keys:
            self.reload_keys()
        now = time.time()
        return sum(1 for k in self.keys if k["cooldown_until"] <= now)

    def mark_rate_limited(self, key: str, cooldown_seconds: int = 60):
        """Puts a specific key on temporary cooldown after receiving a 429 or quota response."""
        for k in self.keys:
            if k["key"] == key:
                k["cooldown_until"] = time.time() + cooldown_seconds
                print(f"[KeyManager] {self.prefixes[0]} Key ({key[:8]}...) placed on {cooldown_seconds}s cooldown.")
                break


class MultiProviderManager:
    """Cascades requests across Google AI Studio, Groq, and OpenRouter pools."""

    def __init__(self):
        self.google_pool = APIKeyPool(["GEMINI_API_KEY", "GOOGLE_API_KEY"])
        self.groq_pool = APIKeyPool(["GROQ_API_KEY", "snaptex-groq"])
        self.openrouter_pool = APIKeyPool(["OPENROUTER_API_KEY", "snaptex-openrouter"])

    def reload_all(self):
        """Ensures all provider pools reload environment variables if initialized before load_dotenv()."""
        for pool in (self.google_pool, self.groq_pool, self.openrouter_pool):
            if not pool.keys:
                pool.reload_keys()


# Instantiated global manager
provider_manager = MultiProviderManager()