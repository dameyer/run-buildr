import os

os.environ.setdefault("SESSION_SECRET", "test-secret-for-pytest-0123456789abcdef")
os.environ.setdefault("INVITE_CODE", "test-invite-code-for-pytest")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Fernet key for tests (throwaway; valid 32-byte urlsafe-base64 key)
os.environ.setdefault("FERNET_KEY", "xFmq1pUX_1HGbJ7lOmzcTOCOgIQVHycKgUBnIkgcha0=")
