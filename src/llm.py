"""Shared LLM call utility — wraps litellm.acompletion boilerplate."""
import logging
from typing import Any

logger = logging.getLogger("llm")


async def call_llm(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 512,
    api_key: str | None = None,
    api_base: str | None = None,
) -> str:
    """
    Call litellm.acompletion with system+user messages.
    Returns the stripped response text.
    Re-raises on failure so callers can log at the appropriate level with context.

    Parameters default to config values when None:
      model    → AI_MODEL
      api_key  → AI_API_KEY (empty string treated as absent)
      api_base → AI_API_BASE (empty string treated as absent)
    """
    import litellm
    from src.config import AI_MODEL, AI_API_KEY, AI_API_BASE

    effective_model = model or AI_MODEL
    effective_key = api_key if api_key is not None else (AI_API_KEY or None)
    effective_base = api_base if api_base is not None else (AI_API_BASE or None)

    kwargs: dict[str, Any] = {
        "model": effective_model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if effective_key:
        kwargs["api_key"] = effective_key
    if effective_base:
        kwargs["api_base"] = effective_base

    response = await litellm.acompletion(**kwargs)
    return response.choices[0].message.content.strip()
