"""Phone numbers are encrypted at rest. The key comes from the environment only."""

import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.environ.get("PHONE_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "PHONE_ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt_phone(phone: str) -> bytes:
    return _fernet().encrypt(phone.encode())


def decrypt_phone(token: bytes) -> str:
    return _fernet().decrypt(bytes(token)).decode()
