import pytest
from pydantic import ValidationError

from regtrace.config import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    Settings,
    load_settings,
)


def test_defaults_when_env_is_empty():
    settings = load_settings(env={})

    assert settings.llm_model == DEFAULT_MODEL
    assert settings.llm_num_ctx == DEFAULT_NUM_CTX
    assert settings.llm_embed_model == DEFAULT_EMBED_MODEL
    assert str(settings.llm_host).startswith("http://localhost:11434")


def test_reads_values_from_env():
    settings = load_settings(
        env={
            "LLM_HOST": "http://gpu-box:11434",
            "LLM_MODEL": "qwen2.5:14b",
            "LLM_NUM_CTX": "16384",
            "LLM_EMBED_MODEL": "mxbai-embed-large",
        }
    )

    assert settings.llm_embed_model == "mxbai-embed-large"

    assert settings.llm_model == "qwen2.5:14b"
    assert settings.llm_num_ctx == 16384
    assert settings.llm_host.host == "gpu-box"


def test_blank_values_fall_back_to_defaults():
    settings = load_settings(env={"LLM_MODEL": "   ", "LLM_NUM_CTX": ""})

    assert settings.llm_model == DEFAULT_MODEL
    assert settings.llm_num_ctx == DEFAULT_NUM_CTX


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_NUM_CTX": "0"},
        {"LLM_NUM_CTX": "not-a-number"},
        {"LLM_HOST": "not a url"},
    ],
)
def test_invalid_values_raise(env):
    with pytest.raises(ValidationError):
        load_settings(env=env)


def test_settings_are_immutable():
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.llm_model = "other"
