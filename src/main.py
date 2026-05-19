import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.api.v1.router import api_router
from src.core.config import get_settings
from src.guardrails.injection_check import PromptInjectionChecker
from src.guardrails.output_guardrails import OutputGuardrails
from src.guardrails.pii_detector import PiiDetector
from src.services.llm_router import LLMRouter


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    app.state.pii_detector = PiiDetector(enable_presidio=settings.enable_presidio)
    app.state.injection_checker = PromptInjectionChecker(settings)
    app.state.output_guardrails = OutputGuardrails()
    app.state.llm_router = LLMRouter(settings)
    yield


app = FastAPI(
    title="LLM Shield & Observability Gateway",
    version="1.0.0",
    description="OpenAI-compatible gateway for LLM security, routing, and cost observability.",
    lifespan=lifespan,
)
app.include_router(api_router)


@app.exception_handler(TimeoutError)
async def timeout_handler(_: Request, exc: TimeoutError) -> JSONResponse:
    return _error_response("upstream_timeout", "The upstream LLM provider timed out.", 504, exc)


@app.exception_handler(RuntimeError)
async def runtime_handler(_: Request, exc: RuntimeError) -> JSONResponse:
    return _error_response(
        "upstream_failure",
        "The LLM gateway could not complete the request.",
        502,
        exc,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return _error_response("internal_error", "An unexpected gateway error occurred.", 500, exc)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _error_response(code: str, message: str, status_code: int, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).warning("%s: %s", code, exc)
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    return JSONResponse(status_code=status_code, content=payload)
