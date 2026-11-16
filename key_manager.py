import os
import time
from typing import List, Dict, Optional, Any


class APIKeyPool:
    """Manages a pool of API keys with round-robin selection and dynamic rate-limit cooldown tracking."""

    def __init__(self, env_var_prefix: str):
        self.prefix = env_var_prefix
        self.keys: List[Dict[str, Any]] = []
        self.current_idx = 0
        self.reload_keys()

    def reload_keys(self):
        """Loads single or numbered environment variable keys (e.g., GROQ_API_KEY, GROQ_API_KEY_1, GROQ_API_KEY_2)."""
        self.keys = []

        # Check primary single key
        primary_key = os.getenv(self.prefix)
        if primary_key and primary_key.strip():
            self.keys.append({"key": primary_key.strip(), "cooldown_until": 0.0})

        # Check numbered keys (starts at 1; also checks 0 just in case)
        for index in range(0, 50):
            key_val = os.getenv(f"{self.prefix}_{index}")
            if key_val and key_val.strip():
                cleaned = key_val.strip()
                if cleaned not in [k["key"] for k in self.keys]:
                    self.keys.append({"key": cleaned, "cooldown_until": 0.0})
            elif index >= 1:
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
                print(f"[KeyManager] {self.prefix} Key ({key[:8]}...) placed on {cooldown_seconds}s cooldown.")
                break


class MultiProviderManager:
    """Cascades requests across Google AI Studio, Groq, and OpenRouter pools."""

    def __init__(self):
        self.google_pool = APIKeyPool("GOOGLE_API_KEY")
        self.groq_pool = APIKeyPool("GROQ_API_KEY")
        self.openrouter_pool = APIKeyPool("OPENROUTER_API_KEY")

    def reload_all(self):
        """Ensures all provider pools reload environment variables if initialized before load_dotenv()."""
        for pool in (self.google_pool, self.groq_pool, self.openrouter_pool):
            if not pool.keys:
                pool.reload_keys()


# Instantiated global manager
provider_manager = MultiProviderManager()