from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter, Histogram

REQUESTS_TOTAL = Counter(
    "llm_shield_requests_total",
    "Total LLM Shield requests by status and model.",
    ["status", "model"],
)
THREATS_TOTAL = Counter("llm_shield_threats_total", "Total blocked prompt-injection attempts.")
REDACTIONS_TOTAL = Counter("llm_shield_redactions_total", "Total PII redactions.")
COST_TOTAL = Counter("llm_shield_cost_usd_total", "Estimated LLM spend in USD.", ["model"])
LATENCY_SECONDS = Histogram(
    "llm_shield_latency_seconds",
    "End-to-end upstream provider latency in seconds.",
    ["model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

MODEL_PRICING_PER_1M_TOKENS = {
    "openai/gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "openai/gpt-4.1-mini": {"prompt": 0.40, "completion": 1.60},
    "anthropic/claude-3-5-haiku-latest": {"prompt": 0.80, "completion": 4.00},
}


@dataclass(frozen=True)
class RequestTelemetry:
    request_id: str
    model: str
    status: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float
    redaction_count: int
    threat_detected: bool

    @classmethod
    def from_llm_response(
        cls,
        request_id: str,
        model: str,
        status: str,
        latency_ms: float,
        response: dict[str, Any],
        redaction_count: int,
        threat_detected: bool,
    ) -> "RequestTelemetry":
        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return cls(
            request_id=request_id,
            model=model,
            status=status,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_cost_usd=calculate_cost_usd(model, prompt_tokens, completion_tokens),
            redaction_count=redaction_count,
            threat_detected=threat_detected,
        )


def calculate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING_PER_1M_TOKENS.get(model, {"prompt": 0.0, "completion": 0.0})
    return round(
        (prompt_tokens / 1_000_000 * pricing["prompt"])
        + (completion_tokens / 1_000_000 * pricing["completion"]),
        8,
    )


def record_request_telemetry(telemetry: RequestTelemetry) -> None:
    """Record metrics; database persistence can be wired behind this boundary."""

    REQUESTS_TOTAL.labels(status=telemetry.status, model=telemetry.model).inc()
    LATENCY_SECONDS.labels(model=telemetry.model).observe(telemetry.latency_ms / 1000)
    COST_TOTAL.labels(model=telemetry.model).inc(telemetry.total_cost_usd)
    REDACTIONS_TOTAL.inc(telemetry.redaction_count)
    if telemetry.threat_detected:
        THREATS_TOTAL.inc()
