"""
Envelope encryption for Zuora client secrets.

We use Fernet (cryptography.io) with a single master key loaded from
settings.MASTER_ENCRYPTION_KEY. Fernet gives us:
  - AES-128-CBC + HMAC-SHA256 (auth + integrity)
  - urlsafe-base64-encoded ciphertext suitable for a TEXT column
  - automatic timestamping (we don't rely on expiry, but it's there)

If the master key is missing or invalid, we fail loudly at startup so the
app never silently runs with unencryptable storage.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CryptoError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = settings.MASTER_ENCRYPTION_KEY
    if not key:
        raise CryptoError(
            "MASTER_ENCRYPTION_KEY is not set. Generate one with:\n"
            "  python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'\n"
            "and add it to .env."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:  # noqa: BLE001
        raise CryptoError(
            "MASTER_ENCRYPTION_KEY is not a valid Fernet key (44 url-safe base64 chars). "
            f"Underlying error: {e}"
        ) from e


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns the urlsafe-base64 token as a str."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token back to a plaintext string."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise CryptoError(
            "Failed to decrypt token. Either the master key rotated or the ciphertext "
            "was corrupted."
        ) from e


def healthcheck() -> bool:
    """Verify the key works by round-tripping a short string. Called at startup."""
    try:
        token = encrypt("ping")
        return decrypt(token) == "ping"
    except Exception:  # noqa: BLE001
        return False
