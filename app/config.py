from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    wahoo_client_id: str = ""
    wahoo_client_secret: str = ""
    session_secret: str
    # Required. Fernet key (from Fernet.generate_key()) encrypting Wahoo/Garmin
    # tokens at rest.
    fernet_key: str
    https_only: bool = True
    database_url: str = "sqlite:///./kickr.db"
    redirect_uri: str = "http://127.0.0.1:9000/auth/wahoo/callback"

    invite_code: str

    @field_validator("invite_code")
    @classmethod
    def _invite_code_set(cls, v: str) -> str:
        if not v or v == "change-this-invite-code":
            raise ValueError("INVITE_CODE must be set to a non-placeholder value in .env")
        return v

    @field_validator("fernet_key")
    @classmethod
    def _fernet_key_valid(cls, v: str) -> str:
        try:
            Fernet(v)
        except Exception:
            raise ValueError(
                'FERNET_KEY must be a valid Fernet key. Generate one with: '
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        return v

    wahoo_auth_url: str = "https://api.wahooligan.com/oauth/authorize"
    wahoo_token_url: str = "https://api.wahooligan.com/oauth/token"
    wahoo_api_base: str = "https://api.wahooligan.com"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
