"""Provider-resolution + chat-model factory tests (no network, no real key)."""

import pytest

from providers.chat import (
    OPENROUTER_BASE_URL,
    build_chat_model,
    build_config,
    resolve_provider,
)

ENV_KEYS = [
    "LLM_PROVIDER",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_resolve_precedence_explicit_wins(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    assert resolve_provider("anthropic") == "anthropic"


def test_resolve_env_llm_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert resolve_provider("auto") == "openrouter"


def test_resolve_openrouter_when_key_present(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    assert resolve_provider() == "openrouter"


def test_resolve_defaults_to_anthropic():
    assert resolve_provider() == "anthropic"


def test_openrouter_model_mapping(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    cfg = build_config(model="claude-sonnet-5", provider="openrouter")
    assert cfg.provider == "openrouter"
    assert cfg.model == "anthropic/claude-sonnet-4.5"
    assert cfg.base_url == OPENROUTER_BASE_URL


def test_openrouter_model_env_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
    cfg = build_config(model="claude-sonnet-5", provider="openrouter")
    assert cfg.model == "meta-llama/llama-3.3-70b-instruct"


def test_openrouter_slash_passthrough():
    cfg = build_config(model="anthropic/claude-opus-4.1", provider="openrouter")
    assert cfg.model == "anthropic/claude-opus-4.1"


def test_thinking_flag_carried():
    cfg = build_config(provider="openrouter", thinking=True)
    assert cfg.thinking is True


def test_build_openrouter_chat_model_is_openai_compatible():
    pytest.importorskip("langchain_openai")
    cfg = build_config(model="claude-sonnet-5", thinking=True, provider="openrouter")
    cfg.api_key = "sk-or-test"  # dummy; no network call is made
    model = build_chat_model(cfg)
    # points at OpenRouter, carries the reasoning body for the thinking arm
    assert str(model.openai_api_base).rstrip("/") == OPENROUTER_BASE_URL.rstrip("/")
    assert (model.extra_body or {}).get("reasoning", {}).get("max_tokens") == 4000


def test_build_openrouter_disables_reasoning_when_thinking_off():
    pytest.importorskip("langchain_openai")
    cfg = build_config(model="claude-sonnet-5", thinking=False, provider="openrouter")
    cfg.api_key = "sk-or-test"
    model = build_chat_model(cfg)
    # thinking OFF must explicitly disable reasoning (models like Qwen3 default it on)
    assert (model.extra_body or {}).get("reasoning") == {"enabled": False}


def test_build_anthropic_chat_model():
    pytest.importorskip("langchain_anthropic")
    cfg = build_config(model="claude-sonnet-5", provider="anthropic")
    cfg.api_key = "sk-ant-test"
    model = build_chat_model(cfg)
    assert model.model == "claude-sonnet-5"
