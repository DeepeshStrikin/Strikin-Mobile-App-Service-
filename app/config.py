"""Application settings, loaded from environment (.env). No secrets in source."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Strikin API"
    environment: str = "development"
    # Safe-by-default: stays off in production unless DEBUG=true is set explicitly in .env.
    debug: bool = False

    database_url: str = "sqlite:///./strikin.db"
    # In production set CORS_ORIGINS to your real app/web origins (comma-separated),
    # NOT "*". "*" disables credentialed requests and lets any site call the API.
    cors_origins: str = "http://localhost:8081,http://localhost:19006,http://localhost:3000"

    default_gst_rate_percent: float = 18.0
    gst_hsn_sac_code: str = "999692"
    loyalty_earn_rate: float = 0.05

    # Control panel (admin) — set a strong value in production (Railway variable ADMIN_PASSWORD).
    admin_password: str = "strikin-admin-change-me"

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""
    gmail_user: str = ""
    gmail_app_password: str = ""
    restoworks_api_key: str = ""

    # Credentials pasted into Railway/.env often carry a trailing space or newline,
    # which silently breaks Basic-auth and HMAC signatures (Razorpay → 401). Strip them.
    @field_validator("razorpay_key_id", "razorpay_key_secret", mode="before")
    @classmethod
    def _strip_secret(cls, v):
        return v.strip() if isinstance(v, str) else v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
