"""Configurable LLM providers for the AI analyst.

Providers receive a system prompt, a user message (containing only sanitised,
envelope-wrapped data) and a JSON schema, and must return a parsed JSON object.
The analyst layer validates the object independently – providers are not
trusted to follow instructions.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from shared.config import Settings


class ProviderError(Exception):
    pass


class LLMProvider(ABC):
    name: str
    model: str | None = None

    @abstractmethod
    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class AnthropicProvider(LLMProvider):
    """Claude via the official Anthropic SDK (structured JSON output)."""

    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ProviderError("install the 'ai' extra: pip install atlas-osint[ai]") from exc
        self._anthropic = anthropic
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        # With no explicit key the SDK resolves credentials from the environment.
        self._client = anthropic.AsyncAnthropic(api_key=key) if key else anthropic.AsyncAnthropic()
        self.model = settings.ai_model

    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        a = self._anthropic
        try:
            response = await self._client.beta.messages.create(  # type: ignore[call-overload]
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.RateLimitError as exc:
            raise ProviderError("AI provider rate limit reached") from exc
        except a.APIStatusError as exc:
            raise ProviderError(f"AI provider error (HTTP {exc.status_code})") from exc
        except a.APIConnectionError as exc:
            raise ProviderError("AI provider unreachable") from exc
        if response.stop_reason == "refusal":
            raise ProviderError("AI provider declined the request")
        if response.stop_reason == "max_tokens":
            raise ProviderError("AI response truncated")
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if not text:
            raise ProviderError("AI provider returned no text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("AI provider returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("AI provider returned a non-object")
        return data


class OpenAICompatibleProvider(LLMProvider):
    """Any self-hosted model exposing an OpenAI-style ``/chat/completions`` endpoint (e.g. vLLM, Ollama)."""

    name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_compatible_base_url:
            raise ProviderError("ATLAS_OPENAI_COMPATIBLE_BASE_URL is required")
        self.base_url = settings.openai_compatible_base_url.rstrip("/")
        self.api_key = (
            settings.openai_compatible_api_key.get_secret_value() if settings.openai_compatible_api_key else None
        )
        self.model = settings.ai_model

    async def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system + "\nReturn JSON matching this schema:\n" + json.dumps(schema)},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError("AI provider unreachable") from exc
        if resp.status_code != 200:
            raise ProviderError(f"AI provider error (HTTP {resp.status_code})")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError("AI provider returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("AI provider returned a non-object")
        return data


def build_provider(settings: Settings) -> LLMProvider | None:
    if settings.ai_provider == "anthropic":
        return AnthropicProvider(settings)
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    return None
