# app/core/config.py
import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ENV = os.getenv("APP_ENV", "dev")
ENV_FILE = f".env.{APP_ENV}"


class Settings(BaseSettings):
    # mapping env vars (case-insensitive) to settings field names
    app_env: str = APP_ENV
    debug: bool = False
    log_level: str = "INFO"
    database_url_template: str
    db_user: str | None = Field(default=None, repr=False)
    db_password: str | None = Field(default=None, repr=False)
    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: str = "./storage"
    s3_bucket: str | None = None
    s3_region: str | None = None
    jwt_secret_key: str = Field(..., repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_storage(self):
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return self

    def _fill_db_template(self, template: str) -> str:
        return template.format(
            DB_USER=self.db_user or "",
            DB_PASSWORD=self.db_password or "",
        )
    @property
    def database_url(self) -> str:
        return self._fill_db_template(self.database_url_template)


@lru_cache
def get_settings() -> Settings:
    return Settings()
