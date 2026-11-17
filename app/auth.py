import hashlib
import secrets

KEY_PREFIX = "sk-proj-"


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(24)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def display_prefix(raw_key: str) -> str:
    return raw_key[: len(KEY_PREFIX) + 6] + "..."
