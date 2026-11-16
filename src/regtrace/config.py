"""Runtime settings loaded from environment variables (and an optional `.env` file)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_NUM_CTX = 8192


class Settings(BaseModel):
    """LLM connection settings for a local Ollama server."""

    model_config = ConfigDict(frozen=True)

    llm_host: HttpUrl = Field(default=HttpUrl(DEFAULT_HOST))
    llm_model: str = Field(default=DEFAULT_MODEL, min_length=1)
    llm_num_ctx: int = Field(default=DEFAULT_NUM_CTX, gt=0)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build `Settings` from `env`, or from the process environment plus `.env`.

    Passing `env` explicitly skips `.env` loading, which keeps tests isolated.
    """
    if env is None:
        load_dotenv()
        env = os.environ

    values: dict[str, str] = {}
    for field in Settings.model_fields:
        raw = env.get(field.upper())
        if raw is not None and raw.strip():
            values[field] = raw.strip()
    return Settings(**values)
