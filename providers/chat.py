"""LLM provider factory: native Anthropic or OpenRouter (OpenAI-compatible).

The agent arms don't hard-code a client. They ask this module for a LangChain
chat model given a canonical model name + a thinking flag, and the provider is
resolved from configuration / environment:

    provider = explicit arg
             | $LLM_PROVIDER
             | "openrouter" if $OPENROUTER_API_KEY is set
             | "anthropic"           (default)

OpenRouter is reached through its OpenAI-compatible endpoint via
``langchain_openai.ChatOpenAI`` pointed at ``$OPENROUTER_BASE_URL``. Extended
thinking maps to OpenRouter's unified ``reasoning`` request field; on native
Anthropic it maps to ``ChatAnthropic(thinking=...)``. Nothing here imports an
LLM SDK at module load — the heavy imports happen only inside
``build_chat_model`` — so the light core/CI path is unaffected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Canonical model names used across the repo.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Convenience mapping: canonical name -> an OpenRouter model id. Override any
# time with $OPENROUTER_MODEL, or pass a slash-style id directly.
OPENROUTER_MODEL_MAP = {
    "claude-sonnet-5": "anthropic/claude-sonnet-4.5",
    "claude-opus-4-8": "anthropic/claude-opus-4.1",
    "claude-haiku-4-5-20251001": "anthropic/claude-haiku-4.5",
}

DEFAULT_MAX_TOKENS = 8000
DEFAULT_THINKING_TOKENS = 4000


@dataclass
class ProviderConfig:
    """Fully-resolved settings for building a chat model."""

    provider: str  # "anthropic" | "openrouter"
    model: str
    thinking: bool
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking_tokens: int = DEFAULT_THINKING_TOKENS
    site_url: str | None = None
    app_name: str | None = None

    @property
    def api_key_present(self) -> bool:
        return bool(self.api_key)


def resolve_provider(explicit: str | None = None) -> str:
    """Decide which provider to use (see module docstring for precedence)."""
    if explicit and explicit != "auto":
        return explicit
    env = os.getenv("LLM_PROVIDER")
    if env:
        return env.strip().lower()
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return "anthropic"


def _openrouter_model(canonical: str | None) -> str:
    """Resolve the OpenRouter model id from a canonical name / env / passthrough."""
    if os.getenv("OPENROUTER_MODEL"):
        return os.environ["OPENROUTER_MODEL"]
    if canonical and canonical in OPENROUTER_MODEL_MAP:
        return OPENROUTER_MODEL_MAP[canonical]
    if canonical and "/" in canonical:  # already an OpenRouter-style id
        return canonical
    return DEFAULT_OPENROUTER_MODEL


def build_config(
    model: str | None = None,
    thinking: bool = False,
    provider: str | None = None,
) -> ProviderConfig:
    """Resolve a :class:`ProviderConfig` from args + environment."""
    prov = resolve_provider(provider)
    if prov == "openrouter":
        return ProviderConfig(
            provider="openrouter",
            model=_openrouter_model(model),
            thinking=thinking,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
            site_url=os.getenv("OPENROUTER_SITE_URL"),
            app_name=os.getenv("OPENROUTER_APP_NAME", "claims-audit-agent"),
        )
    return ProviderConfig(
        provider="anthropic",
        model=model or os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
        thinking=thinking,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
    )


def build_chat_model(cfg: ProviderConfig):
    """Instantiate a LangChain chat model for ``cfg`` (imports the SDK lazily)."""
    if cfg.provider == "openrouter":
        from langchain_openai import ChatOpenAI

        headers: dict[str, str] = {}
        if cfg.site_url:
            headers["HTTP-Referer"] = cfg.site_url
        if cfg.app_name:
            headers["X-Title"] = cfg.app_name

        # OpenRouter's unified reasoning field; only sent when thinking is on so
        # non-reasoning models aren't handed an unsupported parameter.
        extra_body: dict = {}
        if cfg.thinking:
            extra_body["reasoning"] = {"max_tokens": cfg.thinking_tokens}

        return ChatOpenAI(
            model=cfg.model,
            base_url=cfg.base_url or OPENROUTER_BASE_URL,
            api_key=cfg.api_key or "MISSING",
            max_tokens=cfg.max_tokens,
            default_headers=headers or None,
            extra_body=extra_body or None,
        )

    from langchain_anthropic import ChatAnthropic

    kwargs: dict = {"model": cfg.model, "max_tokens": cfg.max_tokens}
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    if cfg.thinking:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": cfg.thinking_tokens}
    return ChatAnthropic(**kwargs)
