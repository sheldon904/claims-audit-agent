"""Provider-agnostic LLM configuration.

Lets the LLM agent arms run against native Anthropic *or* OpenRouter
(OpenAI-compatible) without touching agent code. See ``providers.chat``.
"""

from providers.chat import (
    ProviderConfig,
    build_chat_model,
    build_config,
    resolve_provider,
)

__all__ = [
    "ProviderConfig",
    "build_chat_model",
    "build_config",
    "resolve_provider",
]
