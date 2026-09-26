import re

from pydantic import HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    app_name: str = "Armory Ledger"
    app_version: str = "0.1.2"

    # Optional identity of this installation, separate from upstream authorship.
    armory_operator_name: str | None = None
    armory_support_email: str | None = None
    armory_support_url: HttpUrl | None = None

    @field_validator(
        "armory_operator_name", "armory_support_email", "armory_support_url",
        mode="before",
    )
    @classmethod
    def clean_optional_instance_setting(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("armory_support_email")
    @classmethod
    def validate_support_email(cls, value):
        if value is not None:
            # A plain mailbox only: no mailto query parameters or headers.
            if not re.fullmatch(r"[A-Za-z0-9.!$%&'*+/=_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value):
                raise ValueError("ARMORY_SUPPORT_EMAIL must be a plain email address")
        return value

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str = "db"
    postgres_port: int = 5432

    # Authentik OIDC
    oidc_client_id: str
    oidc_client_secret: str
    oidc_issuer: str
    oidc_redirect_uri: str

    # Application sessions
    session_secret: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()
