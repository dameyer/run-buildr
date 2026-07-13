"""Token-at-rest encryption.

Wahoo/Garmin third-party tokens are encrypted with Fernet (AES-128-CBC + HMAC)
before hitting the DB. ``FERNET_KEY`` is required and validated at startup.

``decrypt`` raises ``InvalidToken`` on a value that wasn't encrypted with the
current key (e.g. a legacy plaintext row, or a rotated key). Callers treat that
as "not connected" so the account simply reconnects — see ``garmin.get_client``
and ``wahoo.get_valid_token``.
"""
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_fernet = Fernet(settings.fernet_key)

__all__ = ["encrypt", "decrypt", "InvalidToken"]


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()
