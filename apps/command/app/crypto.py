import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def fernet() -> Fernet:
    secret = settings.command_secret_key or "command-dev-key"
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    try:
        return fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"{salt.hex()}:{derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, derived_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    check = hash_password(password, salt)
    return hmac.compare_digest(check, stored)


def passwords_match(provided: str, expected: str) -> bool:
    if not expected:
        return False
    left = provided.encode()
    right = expected.encode()
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)
