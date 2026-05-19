import logging
import re
from dataclasses import dataclass

from src.core.config import Settings


@dataclass(frozen=True)
class InjectionCheckResult:
    is_attack: bool
    score: float
    reason: str


class PromptInjectionChecker:
    """Prompt-injection classifier with optional local Transformer inference."""

    _logger = logging.getLogger(__name__)
    _attack_patterns = [
        re.compile(r"\bignore (all )?(previous|prior|above) instructions\b", re.IGNORECASE),
        re.compile(
            r"\bdisregard (the )?(system|developer|previous) (message|instructions)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\breveal (your|the) (system prompt|hidden instructions|developer message)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bjailbreak\b", re.IGNORECASE),
        re.compile(r"\bact as (dan|do anything now)\b", re.IGNORECASE),
    ]

    def __init__(self, settings: Settings) -> None:
        self._threshold = settings.injection_threshold
        self._classifier = None
        if settings.enable_transformer_guard:
            self._load_classifier(settings.prompt_injection_model)

    def _load_classifier(self, model_name: str) -> None:
        try:
            from transformers import pipeline

            self._classifier = pipeline(
                "text-classification",
                model=model_name,
                truncation=True,
                max_length=512,
            )
        except Exception:
            self._classifier = None

    def classify(self, text: str) -> InjectionCheckResult:
        if not text:
            return InjectionCheckResult(is_attack=False, score=0.0, reason="empty")

        if self._classifier:
            try:
                result = self._classifier(text)[0]
                label = str(result.get("label", "")).lower()
                score = float(result.get("score", 0.0))
                is_attack = score >= self._threshold and any(
                    keyword in label for keyword in ("injection", "attack", "malicious", "unsafe")
                )
                return InjectionCheckResult(
                    is_attack=is_attack,
                    score=score,
                    reason=f"transformer:{label}",
                )
            except Exception as exc:
                self._logger.warning("Transformer guard failed; using heuristics: %s", exc)

        max_score = 0.0
        matched_reason = "heuristic:clean"
        for pattern in self._attack_patterns:
            if pattern.search(text):
                max_score = 0.96
                matched_reason = f"heuristic:{pattern.pattern}"
                break

        return InjectionCheckResult(
            is_attack=max_score >= self._threshold,
            score=max_score,
            reason=matched_reason,
        )
