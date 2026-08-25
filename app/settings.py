from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar
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

    # Admin accounts
    admin_username: str = "admin"
    admin_password: str = "admin123"
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

    # A second mailbox to fall back to when the first one refuses, times out or
    # hits its rate limit. Leave the host unset and nothing changes: one
    # account, one attempt, exactly as before.
    smtp_fallback_host: str | None = None
    smtp_fallback_port: int = 465
    smtp_fallback_user: str | None = None
    smtp_fallback_pass: str | None = None
    # Most providers refuse to relay a message whose From address is not one of
    # theirs. A fallback on a different provider therefore needs its own From,
    # or every failover is rejected at the door. Falls back to the fallback
    # user's own address when left unset.
    smtp_fallback_from: str | None = None

    # How long to wait on a single SMTP connection before giving up on it and
    # trying the next account. Hostinger answers in well under a second when
    # it is healthy; a minute of hanging is what a queue backing up looks like.
    smtp_timeout_seconds: float = 30.0

    # Seconds to pause between messages inside a bulk send. The batch reuses a
    # single SMTP connection, so this only needs to be a small courtesy delay to
    # stay under provider per-second limits. Set to 0 to send as fast as possible.
    email_batch_delay_seconds: float = 0.4

    # The names people actually type in a .env, mapped to the ones this class
    # reads. SMTP_SERVER / SMTP_EMAIL / SMTP_PASSWORD are what most hosting
    # panels call these fields, and an .env written that way used to configure
    # nothing at all: smtp_host stayed None, _is_dry_run() went true, and the
    # app logged every message to a file instead of sending it — silently, and
    # looking exactly like working software.
    SMTP_ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "smtp_host": ("smtp_server", "smtp_hostname"),
        "smtp_port": (),
        "smtp_user": ("smtp_email", "smtp_username", "email_user"),
        "smtp_pass": ("smtp_password", "email_pass"),
        "smtp_fallback_host": ("smtp_backup_host", "smtp_server_2", "smtp_host_2"),
        "smtp_fallback_port": ("smtp_backup_port", "smtp_port_2"),
        "smtp_fallback_user": ("smtp_backup_user", "smtp_email_2", "smtp_user_2"),
        "smtp_fallback_pass": ("smtp_backup_pass", "smtp_password_2", "smtp_pass_2"),
        "smtp_fallback_from": ("smtp_backup_from", "email_from_2"),
    }

    @model_validator(mode="before")
    @classmethod
    def populate_smtp_defaults(cls, data: Any) -> Any:
        """Accept the alias spellings, without overriding a canonical name.

        Pydantic-settings hands keys through in either case depending on where
        they came from, so every lookup tries both.
        """
        if not isinstance(data, dict):
            return data

        def value_of(name: str):
            for key in (name, name.upper()):
                if data.get(key) not in (None, ""):
                    return data[key]
            return None

        for canonical, aliases in cls.SMTP_ALIASES.items():
            if value_of(canonical) is not None:
                continue
            for alias in aliases:
                found = value_of(alias)
                if found is not None:
                    data[canonical] = found
                    break
        return data



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

settings = get_settings()
