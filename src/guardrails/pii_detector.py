import logging
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PiiEntity:
    entity_type: str
    start: int
    end: int


@dataclass(frozen=True)
class PiiResult:
    text: str
    entities: list[PiiEntity]


class PiiDetector:
    """PII anonymizer backed by Presidio with a deterministic regex fallback."""

    _logger = logging.getLogger(__name__)
    _fallback_patterns = {
        "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "CPF": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
        "PHONE": re.compile(
            r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,3}\)?[\s.-]?)?\d{4,5}[\s.-]?\d{4}\b"
        ),
    }

    def __init__(self, enable_presidio: bool = True) -> None:
        self._analyzer = None
        self._anonymizer = None
        if enable_presidio:
            self._load_presidio()

    def _load_presidio(self) -> None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
        except Exception:
            return

        try:
            self._analyzer = AnalyzerEngine()
            self._anonymizer = AnonymizerEngine()
        except Exception:
            self._analyzer = None
            self._anonymizer = None

    def anonymize(self, text: str) -> PiiResult:
        if not text:
            return PiiResult(text=text, entities=[])

        if self._analyzer and self._anonymizer:
            try:
                results = self._analyzer.analyze(text=text, language="en")
                anonymized = self._anonymizer.anonymize(text=text, analyzer_results=results)
                entities = [
                    PiiEntity(entity_type=result.entity_type, start=result.start, end=result.end)
                    for result in results
                ]
                return PiiResult(text=anonymized.text, entities=entities)
            except Exception as exc:
                self._logger.warning("Presidio anonymization failed; using regex fallback: %s", exc)

        return self._regex_anonymize(text)

    def _regex_anonymize(self, text: str) -> PiiResult:
        matches: list[tuple[int, int, str]] = []
        for entity_type, pattern in self._fallback_patterns.items():
            for match in pattern.finditer(text):
                matches.append((match.start(), match.end(), entity_type))

        if not matches:
            return PiiResult(text=text, entities=[])

        matches.sort(key=lambda item: item[0])
        merged: list[tuple[int, int, str]] = []
        last_end = -1
        for start, end, entity_type in matches:
            if start >= last_end:
                merged.append((start, end, entity_type))
                last_end = end

        chunks: list[str] = []
        cursor = 0
        entities: list[PiiEntity] = []
        for start, end, entity_type in merged:
            chunks.append(text[cursor:start])
            chunks.append(f"[REDACTED_{entity_type}]")
            entities.append(PiiEntity(entity_type=entity_type, start=start, end=end))
            cursor = end
        chunks.append(text[cursor:])
        return PiiResult(text="".join(chunks), entities=entities)
