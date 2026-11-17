from types import SimpleNamespace

import ollama
import pytest
from pydantic import BaseModel

from regtrace.config import Settings
from regtrace.llm import LLMConnectionError, LLMError, LLMResponseError, OllamaClient


class Answer(BaseModel):
    summary: str


class FakeBackend:
    """Stands in for `ollama.Client`: records calls and returns scripted replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(message=SimpleNamespace(content=reply))


def make_client(replies, **kwargs):
    backend = FakeBackend(replies)
    settings = Settings(llm_model="test-model", llm_num_ctx=4096)
    return OllamaClient(settings, backend=backend, **kwargs), backend


def test_valid_reply_is_parsed_into_schema():
    client, _ = make_client(['{"summary": "Describes data collection."}'])

    result = client.generate_structured("Summarise.", Answer)

    assert result == Answer(summary="Describes data collection.")


def test_request_uses_model_schema_and_options():
    client, backend = make_client(['{"summary": "ok"}'])

    client.generate_structured("Summarise.", Answer, system="You are precise.")

    call = backend.calls[0]
    assert call["model"] == "test-model"
    assert call["format"] == Answer.model_json_schema()
    assert call["options"] == {"num_ctx": 4096, "temperature": 0}
    assert call["messages"] == [
        {"role": "system", "content": "You are precise."},
        {"role": "user", "content": "Summarise."},
    ]


def test_model_override_is_used():
    client, backend = make_client(['{"summary": "ok"}'], model="qwen2.5:14b")

    client.generate_structured("Summarise.", Answer)

    assert backend.calls[0]["model"] == "qwen2.5:14b"


def test_invalid_reply_is_retried_with_error_feedback():
    client, backend = make_client(["not json", '{"summary": "ok"}'])

    result = client.generate_structured("Summarise.", Answer)

    assert result.summary == "ok"
    assert len(backend.calls) == 2
    retry_messages = backend.calls[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": "not json"}
    assert "did not match the required JSON schema" in retry_messages[-1]["content"]


def test_gives_up_after_max_retries():
    client, backend = make_client(["{}", "{}"], max_retries=1)

    with pytest.raises(LLMResponseError, match="after 2 attempts"):
        client.generate_structured("Summarise.", Answer)
    assert len(backend.calls) == 2


def test_connection_failure_gives_helpful_error():
    client, _ = make_client([ConnectionError("refused")])

    with pytest.raises(LLMConnectionError, match="ollama serve"):
        client.generate_structured("Summarise.", Answer)


def test_missing_model_suggests_pull():
    client, _ = make_client([ollama.ResponseError("model 'test-model' not found", 404)])

    with pytest.raises(LLMError, match="ollama pull test-model"):
        client.generate_structured("Summarise.", Answer)


def test_negative_max_retries_is_rejected():
    with pytest.raises(ValueError):
        OllamaClient(Settings(), max_retries=-1, backend=FakeBackend([]))
