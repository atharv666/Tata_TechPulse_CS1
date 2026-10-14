"""Deterministic offline providers for evaluation, demos and tests.

``HashedEmbedder`` maps text to a bag-of-words hash vector: texts sharing vocabulary are
close in cosine distance. It is *not* semantic, so an offline run measures the plumbing and
the lexical channel; semantic quality needs the real embedding model (``--live``).

``ExtractiveLLM`` drafts answers by quoting the best-matching sentence of each matched
source, which makes the verification and citation machinery testable without a language
model.
"""

from __future__ import annotations

import hashlib
import math
import re

from app.ingestion.lexical import STOPWORDS, build_lexical_text, query_terms
from app.ingestion.text import stem
from app.providers.contracts import (
    CandidateStructuredOutput,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMRequest,
    StructuredModel,
)

_TOKEN = re.compile(r"[a-z0-9]+")
_SOURCE_BLOCK = re.compile(
    r"\[(chunk:[0-9a-f-]+)\][^\n]*\(role: (\w+);[^\n]*\n(.*?)(?=\n\n\[chunk:|\Z)", re.DOTALL
)
_UNTRUSTED = re.compile(r"<UNTRUSTED_SOURCE_DOCUMENT>(.*?)</UNTRUSTED_SOURCE_DOCUMENT>", re.DOTALL)


def hashed_vector(text: str, dimensions: int) -> list[float]:
    """Bag-of-words hashing with stop words ignored.

    Without a stop list, "is"/"the" overlap would count as relevance and an off-topic question
    would look similar to any short passage.
    """
    vector = [0.0] * dimensions
    for token in _TOKEN.findall(text.lower()):
        if token in STOPWORDS:
            continue
        vector[int(hashlib.md5(token.encode()).hexdigest(), 16) % dimensions] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class HashedEmbedder(EmbeddingProvider):
    def __init__(self, dimensions: int, model: str = "fake-embedding") -> None:
        self.dimensions = dimensions
        self.model = model
        self.calls = 0
        self.texts_seen = 0

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls += 1
        self.texts_seen += len(texts)
        return EmbeddingResult(
            vectors=[hashed_vector(text, self.dimensions) for text in texts],
            model=self.model,
            dimensions=self.dimensions,
        )


class ExtractiveLLM(LLMProvider):
    """Quotes sources; never rewrites questions and never extracts graph facts."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(
        self, request: LLMRequest, response_model: type[StructuredModel]
    ) -> CandidateStructuredOutput[StructuredModel]:
        self.calls += 1
        name = response_model.__name__
        if name == "AnswerDraft":
            payload: dict[str, object] = self._draft(request)
        elif name == "QueryRewrite":
            payload = {"queries": []}
        else:
            raise RuntimeError(f"ExtractiveLLM cannot produce {name}")
        data = response_model.model_validate(payload)
        return CandidateStructuredOutput(data=data, provider="extractive", model="extractive-llm")

    @staticmethod
    def _draft(request: LLMRequest) -> dict[str, object]:
        question = request.messages[1].content.removeprefix("Question:").strip()
        terms = {stem(t.joined) for t in query_terms(question)}
        match = _UNTRUSTED.search(request.messages[-1].content)
        text = (match.group(1) if match else "").strip()
        claims: list[dict[str, object]] = []
        for citation_id, role, body in _SOURCE_BLOCK.findall(text):
            lines = [line.strip() for line in body.splitlines() if line.strip()]
            if role != "HIT" or not lines:
                continue
            best = max(lines, key=lambda line: _overlap(terms, line))
            sentences = re.split(r"(?<=[.!?])\s+", best)
            sentence = max(sentences, key=lambda part: _overlap(terms, part))
            claims.append(
                {
                    "text": sentence.lstrip("- ").replace("`", ""),
                    "citation_ids": [citation_id],
                    "extraction_type": "EXPLICIT",
                }
            )
        return {"summary": "", "claims": claims, "insufficient_evidence": not claims}


def _overlap(terms: set[str], text: str) -> int:
    words = {stem(word) for word in build_lexical_text(text).split()}
    return len(terms & words)
