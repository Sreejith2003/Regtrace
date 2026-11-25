"""LLM access. All model calls in RegTrace go through this package."""

from regtrace.llm.client import (
    Embedder,
    LLMClient,
    LLMConnectionError,
    LLMError,
    LLMResponseError,
    OllamaClient,
    create_client,
)

__all__ = [
    "Embedder",
    "LLMClient",
    "LLMConnectionError",
    "LLMError",
    "LLMResponseError",
    "OllamaClient",
    "create_client",
]
