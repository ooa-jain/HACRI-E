from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any
from pydantic import AliasChoices, Field, model_validator
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

    # SMTP — each field accepts several common env-var spellings so config from
    # different providers (Hostinger, Gmail, …) works without renaming keys.
    #   Host : SMTP_HOST | SMTP_SERVER
    #   Port : SMTP_PORT                 (465 = implicit TLS, 587 = STARTTLS)
    #   User : SMTP_USER | SMTP_EMAIL | EMAIL_USER
    #   Pass : SMTP_PASS | SMTP_PASSWORD | EMAIL_PASS
    smtp_host: str | None = Field(
        default=None, validation_alias=AliasChoices("smtp_host", "smtp_server"))
    smtp_port: int = Field(
        default=465, validation_alias=AliasChoices("smtp_port"))
    smtp_user: str | None = Field(
        default=None, validation_alias=AliasChoices("smtp_user", "smtp_email", "email_user"))
    smtp_pass: str | None = Field(
        default=None, validation_alias=AliasChoices("smtp_pass", "smtp_password", "email_pass"))
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

    @model_validator(mode="after")
    def _finalise_smtp(self) -> "Settings":
        # Gmail app passwords are displayed in 4×4 groups with spaces, but the
        # real secret has no spaces. Strip them for Gmail so login succeeds
        # whether the value was pasted with or without spaces.
        if self.smtp_pass and self.smtp_host and "gmail" in self.smtp_host.lower():
            self.smtp_pass = self.smtp_pass.replace(" ", "")

        # Most providers (Gmail especially) require the From address to match the
        # authenticated mailbox. If EMAIL_FROM was left at the default, use the
        # SMTP login address so mail isn't rejected or rewritten.
        if self.smtp_user and self.email_from == "HACRI-E <noreply@juooa.cloud>":
            self.email_from = f"JAIN Office of Academics <{self.smtp_user}>"
        return self



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

settings = get_settings()
