"""Deterministic stand-ins for the external providers.

``ScriptedLLM`` behaves like a competent extraction/answer model *for the synthetic HLD fixtures*:
it reads the structured markdown lines and returns schema-valid JSON, so the whole pipeline can be
exercised without network access. It checks wiring and data flow; it says nothing about the quality
of a real model (that is what the live evaluation is for).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.evaluation.offline import HashedEmbedder
from app.providers.contracts import (
    CandidateStructuredOutput,
    EmbeddingProvider,
    LLMProvider,
    LLMRequest,
    StructuredModel,
)
from app.providers.fake import register_fake_embedding, register_fake_llm

ENTITY_RE = re.compile(
    r"^- `(?P<name>[^`]+)` is an? (?:new |updated )?`(?P<type>[A-Z_]+)`"
)
REL_RE = re.compile(r"^- `(?P<src>[^`]+)` `(?P<rel>[A-Z_]+)` `(?P<dst>[^`]+)`")
PORT_RE = re.compile(r"through (?:input|output) port `(?P<port>[^`]+)`")
ALIAS_RE = re.compile(
    r"`(?P<owner>[^`]+)` \((?:also referenced as `(?P<a1>[^`]+)`(?: or `(?P<a2>[^`]+)`)?"
    r"|alias `(?P<a3>[^`]+)`)\)"
)
PAIR_LINE = re.compile(
    r"^\s*(?:Pair (?P<n>\d+):|(?P<side>[AB]): (?P<name>.+?) \[(?P<type>[A-Z_]+)\])"
)
TOKEN_RE = re.compile(r"[a-z0-9]+")
TOKEN_JOIN = re.compile(r"[^a-z0-9]+")
# One numbered source in the answer prompt: "[chunk:<id>] <breadcrumb> (role: HIT; ...)\n<text>"
SOURCE_BLOCK = (
    r"\[(chunk:[0-9a-f-]+)\][^\n]*\(role: (\w+);[^\n]*\n(.*?)(?=\n\n\[chunk:|\Z)"
)


class ScriptedLLM(LLMProvider):
    """Regex 'extraction' of the fixture format plus a grounded-answer stub."""

    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[LLMRequest] = []
        #: What the model proposes when asked to rephrase a question (empty = nothing useful).
        self.rewrites: list[str] = []
        #: Override the drafted claims, e.g. to simulate a hallucinating model.
        self.draft_override: dict[str, object] | None = None
        #: Entity-merge judgements: name pairs (any case/punctuation) this "model" says are SAME.
        self.same_pairs: set[frozenset[str]] = set()
        self.judged_pairs: list[tuple[str, str]] = []
        self.merge_confidence = 0.95

    async def generate_structured(
        self, request: LLMRequest, response_model: type[StructuredModel]
    ) -> CandidateStructuredOutput[StructuredModel]:
        self.calls += 1
        self.requests.append(request)
        name = response_model.__name__
        if name == "ChunkExtraction":
            payload = self._extract(request)
        elif name == "AnswerDraft":
            payload = self._draft(request)
        elif name == "MergeVerdictBatch":
            payload = self._merge_verdicts(request)
        elif name == "QueryRewrite":
            payload = {"queries": list(self.rewrites)}
        elif name == "GroundedAnswer":
            payload = self._answer(request)
        else:
            raise RuntimeError(f"ScriptedLLM does not know {name}")
        data = response_model.model_validate(payload)
        return CandidateStructuredOutput(
            data=data, provider="scripted", model="scripted-llm"
        )

    @staticmethod
    def _source_text(request: LLMRequest) -> str:
        user = request.messages[-1].content
        match = re.search(
            r"<UNTRUSTED_SOURCE_DOCUMENT>(.*?)</UNTRUSTED_SOURCE_DOCUMENT>",
            user,
            re.DOTALL,
        )
        return (match.group(1) if match else user).strip()

    def _extract(self, request: LLMRequest) -> dict[str, object]:
        full_prompt = request.messages[-1].content
        body = self._source_text(request)
        inferred = "Candidate Inferred" in full_prompt
        entities: list[dict[str, object]] = []
        relationships: list[dict[str, object]] = []
        for raw in body.splitlines():
            line = raw.strip()
            evidence = {"excerpt": line, "source_type": "DIRECT_TEXT"}
            if match := ENTITY_RE.match(line):
                entities.append(
                    {
                        "name": match["name"],
                        "entity_type": match["type"],
                        "confidence": 0.9,
                        "extraction_type": "EXPLICIT",
                        "evidence": evidence,
                    }
                )
            if match := REL_RE.match(line):
                relationships.append(
                    {
                        "source_name": match["src"],
                        "target_name": match["dst"],
                        "relationship_type": match["rel"],
                        "confidence": 0.8 if inferred else 0.93,
                        "extraction_type": "INFERRED" if inferred else "EXPLICIT",
                        "evidence": evidence,
                    }
                )
                if port := PORT_RE.search(line):
                    entities.append(
                        {
                            "name": port["port"],
                            "entity_type": "PORT",
                            "confidence": 0.85,
                            "extraction_type": "EXPLICIT",
                            "evidence": evidence,
                        }
                    )
            if alias := ALIAS_RE.search(line):
                names = [alias[key] for key in ("a1", "a2", "a3") if alias[key]]
                entities.append(
                    {
                        "name": alias["owner"],
                        "entity_type": "SOFTWARE_COMPONENT",
                        "confidence": 0.9,
                        "extraction_type": "EXPLICIT",
                        "evidence": evidence,
                        "aliases": names,
                    }
                )
        return {"entities": entities, "relationships": relationships}

    def _merge_verdicts(self, request: LLMRequest) -> dict[str, object]:
        """Answer entity-merge batches from ``same_pairs``; everything else is DIFFERENT."""
        text = self._source_text(request)
        pairs: dict[int, dict[str, str]] = {}
        current = 0
        for line in text.splitlines():
            match = PAIR_LINE.match(line)
            if match is None:
                continue
            if match["n"]:
                current = int(match["n"])
                pairs[current] = {}
            elif current:
                pairs[current][match["side"]] = match["name"]
        verdicts: list[dict[str, object]] = []
        for number, sides in pairs.items():
            left, right = sides.get("A", ""), sides.get("B", "")
            self.judged_pairs.append((left, right))
            key = frozenset(
                {TOKEN_JOIN.sub("", left.lower()), TOKEN_JOIN.sub("", right.lower())}
            )
            same = key in {
                frozenset(TOKEN_JOIN.sub("", item.lower()) for item in pair)
                for pair in self.same_pairs
            }
            verdicts.append(
                {
                    "pair": number,
                    "decision": "SAME" if same else "DIFFERENT",
                    "confidence": self.merge_confidence if same else 0.9,
                    "reason": "scripted verdict",
                }
            )
        return {"verdicts": verdicts}

    def _draft(self, request: LLMRequest) -> dict[str, object]:
        """One claim per retrieved HIT block: its first source line, cited to that block."""
        if self.draft_override is not None:
            return self.draft_override
        text = self._source_text(request)
        claims: list[dict[str, object]] = []
        for match in re.finditer(SOURCE_BLOCK, text, re.DOTALL):
            citation_id, role, body = match.groups()
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            if role == "HIT" and lines:
                # atomic claim: the first sentence of the first source line
                first_sentence = re.split(r"(?<=[.!?])\s+", lines[0])[0]
                claims.append(
                    {
                        "text": first_sentence.lstrip("- ").replace("`", ""),
                        "citation_ids": [citation_id],
                        "extraction_type": "EXPLICIT",
                    }
                )
        return {
            "summary": "scripted answer",
            "claims": claims,
            "insufficient_evidence": not claims,
        }

    def _answer(self, request: LLMRequest) -> dict[str, object]:
        text = self._source_text(request)
        try:
            bundle = json.loads(text)
        except json.JSONDecodeError:
            bundle = {"citations": [], "graph_facts": []}
        claims: list[dict[str, object]] = []
        for fact in bundle.get("graph_facts", []):
            claims.append(
                {
                    "text": f"{fact['source_entity']} {fact['relationship_type']} "
                    f"{fact['target_entity']}",
                    "citation_ids": fact["citation_ids"],
                    "extraction_type": fact["extraction_type"],
                }
            )
        if not claims and bundle.get("citations"):
            citation = bundle["citations"][0]
            claims.append(
                {
                    "text": citation["excerpt"][:80],
                    "citation_ids": [citation["citation_id"]],
                    "extraction_type": "EXPLICIT",
                }
            )
        return {"status": "x", "summary": "scripted answer", "claims": claims}


@contextmanager
def installed_fakes(
    llm: LLMProvider | None = None,
    embedder_factory: Callable[[int], EmbeddingProvider] | None = None,
) -> Iterator[tuple[LLMProvider, list[EmbeddingProvider]]]:
    """Make ``LLM_PROVIDER=fake`` / ``EMBEDDING_PROVIDER=fake`` return these objects."""
    scripted = llm or ScriptedLLM()
    created: list[EmbeddingProvider] = []

    def make_embedder(dimensions: int) -> EmbeddingProvider:
        embedder = (embedder_factory or HashedEmbedder)(dimensions)
        created.append(embedder)
        return embedder

    register_fake_llm(lambda: scripted)
    register_fake_embedding(make_embedder)
    try:
        yield scripted, created
    finally:
        register_fake_llm(None)
        register_fake_embedding(None)
