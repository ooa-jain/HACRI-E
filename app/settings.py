from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        extra="ignore", case_sensitive=False,
    )
    mongodb_uri: str = Field(...)
    mongodb_db: str = "hacri_e2"
    session_secret: str = "dev-only-secret-do-not-use-in-production-32b"
    public_base_url: str = "http://localhost:8000"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    generated_root: Path = Path("generated")

    # Two separate admin accounts
    survey_admin_username: str = "survey"
    survey_admin_password: str = "survey2026"
    orientation_admin_username: str = "deeksha_admin"
    orientation_admin_password: str = "deeksha2026"

    # OTP login — admin OTPs are sent to these addresses
    survey_admin_otp_email: str = "santosh.ks@jainuniversity.ac.in"
    orientation_admin_otp_email: str = "santosh.ks@jainuniversity.ac.in"

    # SMTP
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_pass: str | None = None
    email_from: str = "HACRI-E <noreply@juooa.cloud>"
    email_dry_run: bool = True

    # Seconds to pause between messages inside a bulk send. The batch reuses a
    # single SMTP connection, so this only needs to be a small courtesy delay to
    # stay under provider per-second limits. Set to 0 to send as fast as possible.
    email_batch_delay_seconds: float = 0.4

    # When the provider replies with an outbound rate-limit (e.g. Hostinger 451
    # "hostinger_out_ratelimit"), wait this many seconds and retry the same
    # message once before giving up. If it is still limited, the batch stops
    # early and reports how many were sent so no recipients are burned.
    email_ratelimit_cooldown_seconds: float = 60.0

    @model_validator(mode="before")
    @classmethod
    def populate_smtp_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Case insensitive check for keys
            # Pydantic settings loads keys in lowercase or original depending on configuration.
            # We check both lowercase and original casing.
            email_user = data.get("email_user") or data.get("EMAIL_USER")
            email_pass = data.get("email_pass") or data.get("EMAIL_PASS")
            
            if not data.get("smtp_user") and not data.get("SMTP_USER") and email_user:
                data["smtp_user"] = email_user
            if not data.get("smtp_pass") and not data.get("SMTP_PASS") and email_pass:
                data["smtp_pass"] = email_pass
        return data



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

settings = get_settings()
