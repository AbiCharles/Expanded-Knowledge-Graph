"""Pydantic settings loaded from .env / environment."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    LLM_PROVIDER: Literal["openai", "azure", "fake"] = "fake"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    AZURE_OPENAI_DEPLOYMENT: str = ""           # chat-completions deployment
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = ""  # embeddings deployment (vector store)

    # Neo4j (optional auto-registration of a `neo4j_default` data source).
    # When NEO4J_PASSWORD is set, the backend registers the source at boot
    # so it appears in the Knowledge tile ready to be mapped to ontology
    # classes. NEO4J_DATABASE is optional (Enterprise multi-DB).
    NEO4J_URI: str = ""
    NEO4J_USER: str = ""
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = ""

    # Server
    CORS_ORIGINS: str = "http://localhost:5173"
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
