"""Hybrid retrieval: dense (pgvector) + lexical (full-text), fused, gated and diversified.

Why both channels: dense vectors find passages that *mean* the same thing but are weak on
exact identifiers (``P_WheelSpeed_In``, ``BrakeCtrl``, ``0x22F190``); lexical search is the
opposite. Their ranked lists are combined with Reciprocal Rank Fusion, which needs no score
calibration. A passage is only treated as evidence if it is *relevant* (similar enough, or
sharing enough of the question's terms); otherwise the system answers "insufficient evidence"
instead of quoting the nearest irrelevant text.

Everything here is deterministic given the stored vectors/text. No LLM call happens in this module.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, defer

from app.ingestion.lexical import build_tsquery, matched_term_ratio
from app.models.schema import Chunk, Document, DocumentVersion, Section
from app.retrieval.vector import EmbeddingService


@dataclass(frozen=True)
class RetrievalConfig:
    dense_k: int = 30
    lexical_k: int = 30
    rrf_k: int = 60
    top_k: int = 8
    max_per_section: int = 2
    min_dense_similarity: float = 0.5
    min_lexical_ratio: float = 0.34
    dense_weight: float = 1.0
    lexical_weight: float = 1.0


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str
    section_id: UUID
    section_heading: str
    section_path: str
    section_ordinal: int
    chunk_ordinal: int
    breadcrumb: str
    content: str
    lexical_text: str
    page_start: int | None
    page_end: int | None
    kind: str
    dense_rank: int | None = None
    dense_similarity: float | None = None
    lexical_rank: int | None = None
    lexical_score: float | None = None
    matched_ratio: float = 0.0
    fused_score: float = 0.0
    relevant: bool = False

    def trace(self) -> dict[str, Any]:
        """Scores only; the text stays in the database (traces must not copy documents)."""
        return {
            "chunk_id": str(self.chunk_id),
            "section_path": self.section_path,
            "dense_rank": self.dense_rank,
            "dense_similarity": _round(self.dense_similarity),
            "lexical_rank": self.lexical_rank,
            "lexical_score": _round(self.lexical_score),
            "matched_ratio": _round(self.matched_ratio),
            "fused_score": _round(self.fused_score, 5),
            "relevant": self.relevant,
        }


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


@dataclass
class RetrievalResult:
    question: str
    candidates: list[RetrievedChunk]
    selected: list[RetrievedChunk]
    dense_count: int = 0
    lexical_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def relevant(self) -> list[RetrievedChunk]:
        return [c for c in self.selected if c.relevant]


def reciprocal_rank_fusion(
    ranked: dict[str, list[UUID]], weights: dict[str, float], k: int
) -> dict[UUID, float]:
    """``score(d) = sum_i w_i / (k + rank_i(d))`` over the lists that contain ``d``."""
    scores: dict[UUID, float] = defaultdict(float)
    for name, ids in ranked.items():
        weight = weights.get(name, 1.0)
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] += weight / (k + rank)
    return dict(scores)


def select_diverse(
    ordered: list[RetrievedChunk], top_k: int, max_per_section: int
) -> list[RetrievedChunk]:
    """Cap chunks per section so one long section cannot crowd out every other source.

    Skipped chunks are used to fill the remaining slots, so a document with a single big section
    still returns ``top_k`` results.
    """
    chosen: list[RetrievedChunk] = []
    skipped: list[RetrievedChunk] = []
    per_section: dict[UUID, int] = defaultdict(int)
    for candidate in ordered:
        if len(chosen) >= top_k:
            break
        if per_section[candidate.section_id] >= max_per_section:
            skipped.append(candidate)
            continue
        per_section[candidate.section_id] += 1
        chosen.append(candidate)
    for candidate in skipped:
        if len(chosen) >= top_k:
            break
        chosen.append(candidate)
    return chosen


class HybridRetriever:
    """Project-scoped; every query carries the project id and an optional version filter."""

    def __init__(
        self,
        session: Session,
        project_id: UUID,
        embeddings: EmbeddingService,
    ) -> None:
        self._session = session
        self._project_id = project_id
        self._embeddings = embeddings

    # -- public ------------------------------------------------------------------------------
    async def retrieve(
        self,
        question: str,
        config: RetrievalConfig,
        document_version_ids: list[UUID] | None = None,
        extra_queries: list[str] | None = None,
    ) -> RetrievalResult:
        queries = [question, *(extra_queries or [])]
        dense_lists: list[list[tuple[RetrievedChunk, float]]] = []
        lexical_lists: list[list[tuple[RetrievedChunk, float]]] = []
        for query in queries:
            vector = await self._embeddings.embed_query(query)
            dense_lists.append(self._dense(vector, config, document_version_ids))
            lexical_lists.append(self._lexical(query, config, document_version_ids))
        return self._fuse(question, queries, dense_lists, lexical_lists, config)

    # -- channels ----------------------------------------------------------------------------
    def _base(self, columns: list[Any], document_version_ids: list[UUID] | None) -> Any:
        statement = (
            select(
                Chunk,
                Document.id,
                Document.name,
                Section.heading,
                Section.path,
                Section.ordinal,
                *columns,
            )
            .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(Section, Chunk.section_id == Section.id)
            .where(Chunk.project_id == self._project_id)
            .options(defer(Chunk.embedding), defer(Chunk.search_vector))
        )
        if document_version_ids:
            statement = statement.where(Chunk.document_version_id.in_(document_version_ids))
        return statement

    def _dense(
        self,
        vector: list[float],
        config: RetrievalConfig,
        document_version_ids: list[UUID] | None,
    ) -> list[tuple[RetrievedChunk, float]]:
        model, version = self._embeddings.model_identity
        distance = Chunk.embedding.cosine_distance(vector)
        statement = (
            self._base([distance.label("distance")], document_version_ids)
            .where(
                Chunk.embedding.is_not(None),
                Chunk.embedding_model == model,
                Chunk.embedding_model_version == version,
            )
            .order_by(distance, Chunk.id)
            .limit(config.dense_k)
        )
        self._tune_hnsw(config.dense_k)
        rows = self._session.execute(statement).all()
        return [(_to_chunk(row), 1.0 - float(row[-1])) for row in rows]

    def _tune_hnsw(self, k: int) -> None:
        """Filtered HNSW scans can return fewer than ``k`` rows; ask pgvector to keep scanning.

        ``hnsw.iterative_scan`` exists from pgvector 0.8; older servers simply ignore the request.
        """
        try:
            with self._session.begin_nested():
                self._session.execute(
                    text(
                        "SELECT set_config('hnsw.ef_search', :ef, true), "
                        "set_config('hnsw.iterative_scan', 'relaxed_order', true)"
                    ),
                    {"ef": str(max(40, min(k * 3, 1000)))},
                )
        except DBAPIError:
            pass

    def _lexical(
        self,
        query: str,
        config: RetrievalConfig,
        document_version_ids: list[UUID] | None,
    ) -> list[tuple[RetrievedChunk, float]]:
        tsquery = build_tsquery(query)
        if tsquery is None:
            return []
        parsed = func.to_tsquery("english", tsquery)
        rank = func.ts_rank_cd(Chunk.search_vector, parsed, 32)
        statement = (
            self._base([rank.label("score")], document_version_ids)
            .where(Chunk.search_vector.op("@@")(parsed))
            .order_by(rank.desc(), Chunk.id)
            .limit(config.lexical_k)
        )
        rows = self._session.execute(statement).all()
        return [(_to_chunk(row), float(row[-1])) for row in rows]

    # -- fusion ------------------------------------------------------------------------------
    def _fuse(
        self,
        question: str,
        queries: list[str],
        dense_lists: list[list[tuple[RetrievedChunk, float]]],
        lexical_lists: list[list[tuple[RetrievedChunk, float]]],
        config: RetrievalConfig,
    ) -> RetrievalResult:
        by_id: dict[UUID, RetrievedChunk] = {}
        ranked: dict[str, list[UUID]] = {}
        for index, items in enumerate(dense_lists):
            ranked[f"dense{index}"] = [chunk.chunk_id for chunk, _ in items]
            for rank, (chunk, similarity) in enumerate(items, start=1):
                known = by_id.setdefault(chunk.chunk_id, chunk)
                if known.dense_similarity is None or similarity > known.dense_similarity:
                    known.dense_similarity = similarity
                    known.dense_rank = rank
        for index, items in enumerate(lexical_lists):
            ranked[f"lexical{index}"] = [chunk.chunk_id for chunk, _ in items]
            for rank, (chunk, score) in enumerate(items, start=1):
                known = by_id.setdefault(chunk.chunk_id, chunk)
                if known.lexical_score is None or score > known.lexical_score:
                    known.lexical_score = score
                    known.lexical_rank = rank
        weights = {
            name: config.dense_weight if name.startswith("dense") else config.lexical_weight
            for name in ranked
        }
        scores = reciprocal_rank_fusion(ranked, weights, config.rrf_k)
        for chunk_id, chunk in by_id.items():
            chunk.fused_score = scores.get(chunk_id, 0.0)
            chunk.matched_ratio = max(
                matched_term_ratio(query, chunk.lexical_text) for query in queries
            )
            chunk.relevant = (
                chunk.dense_similarity is not None
                and chunk.dense_similarity >= config.min_dense_similarity
            ) or (
                chunk.lexical_rank is not None and chunk.matched_ratio >= config.min_lexical_ratio
            )
        ordered = sorted(by_id.values(), key=lambda c: (-c.fused_score, str(c.chunk_id)))
        relevant_ordered = [c for c in ordered if c.relevant]
        selected = select_diverse(relevant_ordered, config.top_k, config.max_per_section)
        return RetrievalResult(
            question=question,
            candidates=ordered,
            selected=selected,
            dense_count=sum(len(items) for items in dense_lists),
            lexical_count=sum(len(items) for items in lexical_lists),
        )


def _to_chunk(row: Any) -> RetrievedChunk:
    chunk: Chunk = row[0]
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=row[1],
        document_version_id=chunk.document_version_id,
        document_name=row[2],
        section_id=chunk.section_id,
        section_heading=row[3],
        section_path=row[4] or "",
        section_ordinal=row[5],
        chunk_ordinal=chunk.ordinal,
        breadcrumb=chunk.breadcrumb or "",
        content=chunk.content,
        lexical_text=chunk.lexical_text or chunk.content,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        kind=chunk.chunk_kind,
    )
