from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.core.config import Settings, get_settings
from src.core.security import verify_api_key
from src.guardrails.injection_check import InjectionCheckResult, PromptInjectionChecker
from src.guardrails.pii_detector import PiiDetector
from src.services.llm_router import LLMRouter
from src.telemetry.metrics import RequestTelemetry, record_request_telemetry

router = APIRouter(tags=["chat"], dependencies=[Depends(verify_api_key)])


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | list[dict[str, Any]]
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=0.7, ge=0, le=2)
    stream: bool = False
    max_tokens: int | None = Field(default=None, gt=0)
    response_format: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


def _message_text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    text_parts: list[str] = []
    for part in content:
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
    return "\n".join(text_parts)


def _replace_message_content(
    content: str | list[dict[str, Any]],
    original_text: str,
    sanitized_text: str,
) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return sanitized_text

    replaced = False
    sanitized_parts: list[dict[str, Any]] = []
    for part in content:
        copied = dict(part)
        if not replaced and copied.get("type") == "text" and copied.get("text") == original_text:
            copied["text"] = sanitized_text
            replaced = True
        sanitized_parts.append(copied)
    return sanitized_parts


@router.post("/chat/completions")
async def create_chat_completion(
    payload: ChatCompletionRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if payload.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "stream_not_supported",
                "message": "Streaming is not supported by this gateway.",
            },
        )

    request_id = request.headers.get("x-request-id", str(uuid4()))
    pii_detector: PiiDetector = request.app.state.pii_detector
    injection_checker: PromptInjectionChecker = request.app.state.injection_checker
    llm_router: LLMRouter = request.app.state.llm_router

    sanitized_messages: list[dict[str, Any]] = []
    redaction_count = 0
    injection_results: list[InjectionCheckResult] = []

    for message in payload.messages:
        text = _message_text(message.content)
        pii_result = pii_detector.anonymize(text)
        redaction_count += len(pii_result.entities)

        injection_result = injection_checker.classify(pii_result.text)
        injection_results.append(injection_result)
        if injection_result.is_attack:
            background_tasks.add_task(
                record_request_telemetry,
                RequestTelemetry(
                    request_id=request_id,
                    model=payload.model or settings.primary_model,
                    status="blocked",
                    latency_ms=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_cost_usd=0,
                    redaction_count=redaction_count,
                    threat_detected=True,
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "prompt_injection_detected",
                    "message": "The request was blocked by input guardrails.",
                    "score": injection_result.score,
                },
            )

        sanitized_messages.append(
            message.model_dump()
            | {"content": _replace_message_content(message.content, text, pii_result.text)}
        )

    routed_payload = payload.model_dump(exclude_none=True) | {
        "model": payload.model or settings.primary_model,
        "messages": sanitized_messages,
    }

    response, routing_metadata = await llm_router.complete(routed_payload)
    safe_response = request.app.state.output_guardrails.validate(response)

    background_tasks.add_task(
        record_request_telemetry,
        RequestTelemetry.from_llm_response(
            request_id=request_id,
            model=routing_metadata.model,
            status="ok" if safe_response.allowed else "sanitized_output",
            latency_ms=routing_metadata.latency_ms,
            response=safe_response.payload,
            redaction_count=redaction_count,
            threat_detected=False,
        ),
    )

    return safe_response.payload
