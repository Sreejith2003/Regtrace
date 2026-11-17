"""Provider-agnostic LLM interface and its Ollama implementation.

Every model call in RegTrace goes through an `LLMClient`. Callers ask for a
Pydantic schema and get back a validated instance of it, never raw text.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

from regtrace.config import Settings, load_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for all LLM failures."""


class LLMConnectionError(LLMError):
    """The LLM server could not be reached."""


class LLMResponseError(LLMError):
    """The model kept returning output that does not match the requested schema."""


class LLMClient(Protocol):
    """What the rest of RegTrace depends on. Tests can pass any object with this shape."""

    model: str

    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        """Ask the model for an answer matching `schema` and return it validated."""
        ...


class ChatBackend(Protocol):
    """The part of `ollama.Client` that `OllamaClient` uses (lets tests inject a fake)."""

    def chat(self, **kwargs: Any) -> Any: ...


class OllamaClient:
    """`LLMClient` backed by a local Ollama server, using JSON-schema structured output."""

    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        max_retries: int = 2,
        backend: ChatBackend | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.host = str(settings.llm_host).rstrip("/")
        self.model = model or settings.llm_model
        self.num_ctx = settings.llm_num_ctx
        self.max_retries = max_retries
        self._backend: ChatBackend = backend if backend is not None else ollama.Client(self.host)

    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        """Return the model's answer as a validated `schema` instance.

        If the reply does not validate, the error is sent back to the model and it
        gets another try, up to `max_retries` times; then `LLMResponseError` is raised.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        json_schema = schema.model_json_schema()

        last_error: ValidationError | None = None
        for _attempt in range(self.max_retries + 1):
            content = self._chat(messages, json_schema)
            try:
                return schema.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                messages = [
                    *messages,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Your reply did not match the required JSON schema:\n"
                            f"{exc}\n"
                            "Reply again with only valid JSON."
                        ),
                    },
                ]

        raise LLMResponseError(
            f"Model {self.model!r} returned invalid output after "
            f"{self.max_retries + 1} attempts: {last_error}"
        )

    def _chat(self, messages: list[dict[str, str]], json_schema: dict[str, Any]) -> str:
        try:
            response = self._backend.chat(
                model=self.model,
                messages=messages,
                format=json_schema,
                options={"num_ctx": self.num_ctx, "temperature": 0},
            )
        except ConnectionError as exc:
            raise LLMConnectionError(
                f"Could not reach Ollama at {self.host}. Is it running? Try `ollama serve`."
            ) from exc
        except ollama.ResponseError as exc:
            raise LLMError(
                f"Ollama error for model {self.model!r}: {exc.error}. "
                f"If the model is missing, run `ollama pull {self.model}`."
            ) from exc
        return response.message.content or ""


def create_client(settings: Settings | None = None, *, model: str | None = None) -> OllamaClient:
    """Build the default client from settings (environment / `.env` if not given)."""
    return OllamaClient(settings or load_settings(), model=model)
