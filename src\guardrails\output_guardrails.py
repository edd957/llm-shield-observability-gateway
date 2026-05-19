import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutputGuardrailResult:
    allowed: bool
    payload: dict[str, Any]
    reason: str | None = None


class OutputGuardrails:
    """Validate and sanitize model responses before egress."""

    _blocked_terms = {"kill yourself", "build a bomb", "credit card dump"}

    def validate(self, response: dict[str, Any]) -> OutputGuardrailResult:
        content = self._extract_text(response)
        if any(term in content.lower() for term in self._blocked_terms):
            return OutputGuardrailResult(
                allowed=False,
                payload=self._replacement_response(response, "Output safety policy violation."),
                reason="toxicity_or_harmful_instruction",
            )

        response_format = response.get("response_format")
        if response_format and response_format.get("type") == "json_object":
            try:
                json.loads(content)
            except json.JSONDecodeError:
                return OutputGuardrailResult(
                    allowed=False,
                    payload=self._replacement_response(
                        response,
                        "The model returned invalid JSON.",
                    ),
                    reason="invalid_json",
                )

        return OutputGuardrailResult(allowed=True, payload=response)

    def _extract_text(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        return content if isinstance(content, str) else json.dumps(content)

    def _replacement_response(self, response: dict[str, Any], reason: str) -> dict[str, Any]:
        safe = dict(response)
        safe["choices"] = [
            {
                "index": 0,
                "finish_reason": "content_filter",
                "message": {
                    "role": "assistant",
                    "content": f"The response was withheld by LLM Shield. {reason}",
                },
            }
        ]
        return safe
