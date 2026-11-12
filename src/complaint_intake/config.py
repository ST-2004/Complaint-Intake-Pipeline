"""Settings loaded from the environment (and the git-ignored .env file).

Nothing here is a secret: authentication is Entra ID via azure-identity, so the
.env only holds endpoints, names and switches.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"  # noqa: S105 - OAuth scope, not a secret


class PiiProvider(StrEnum):
    AZURE = "azure"
    PRESIDIO = "presidio"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    azure_language_endpoint: str | None = None
    azure_ai_endpoint: str | None = None
    model_deployment: str | None = None
    azure_token_scope: str = DEFAULT_TOKEN_SCOPE
    pii_provider: PiiProvider = PiiProvider.AZURE
    presidio_model: str = "en_core_web_sm"
    db_path: str = "./triage.db"
    request_timeout_s: float = Field(default=30.0, gt=0)

    @field_validator("azure_language_endpoint", "azure_ai_endpoint")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not value.startswith("https://"):
            raise ValueError("endpoints must use https://")
        return value

    @field_validator("azure_ai_endpoint")
    @classmethod
    def _trailing_slash(cls, value: str | None) -> str | None:
        # The OpenAI client joins paths onto base_url; a trailing slash keeps
        # `/openai/v1/` + `chat/completions` correct.
        if value and not value.endswith("/"):
            return value + "/"
        return value

    def missing(self, *names: str) -> list[str]:
        """Return the env-var names (upper case) of any unset settings."""
        return [n.upper() for n in names if not getattr(self, n)]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
