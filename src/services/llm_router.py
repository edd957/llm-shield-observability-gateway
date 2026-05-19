import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.core.config import Settings


@dataclass(frozen=True)
class RoutingMetadata:
    model: str
    latency_ms: float
    fallback_used: bool


class LLMRouter:
    """Provider-agnostic router built around LiteLLM with fallback semantics."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._models = [settings.primary_model, *settings.fallback_models]
        if settings.openai_api_key:
            os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key.get_secret_value())
        if settings.anthropic_api_key:
            os.environ.setdefault(
                "ANTHROPIC_API_KEY",
                settings.anthropic_api_key.get_secret_value(),
            )
        if settings.cohere_api_key:
            os.environ.setdefault("COHERE_API_KEY", settings.cohere_api_key.get_secret_value())

    async def complete(self, payload: dict[str, Any]) -> tuple[dict[str, Any], RoutingMetadata]:
        start = time.perf_counter()
        errors: list[str] = []
        requested_model = payload.get("model") or self._settings.primary_model
        ordered_models = [
            requested_model,
            *[model for model in self._models if model != requested_model],
        ]

        for index, model in enumerate(ordered_models):
            try:
                response = await self._litellm_completion(payload | {"model": model})
                return response, RoutingMetadata(
                    model=model,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    fallback_used=index > 0,
                )
            except (TimeoutError, httpx.HTTPError) as exc:
                errors.append(f"{model}: {exc}")
            except Exception as exc:
                errors.append(f"{model}: {exc}")

        raise RuntimeError(f"All configured LLM providers failed: {'; '.join(errors)}")

    async def _litellm_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from litellm import acompletion
        except Exception as exc:
            raise RuntimeError("LiteLLM is not installed.") from exc

        response = await acompletion(
            **payload,
            timeout=self._settings.request_timeout_seconds,
        )
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if isinstance(response, dict):
            return response
        return dict(response)
