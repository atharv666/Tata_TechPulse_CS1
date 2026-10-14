"""Small-to-big context assembly: match on small chunks, give the model a structured, bigger view.

Retrieval matches *small* chunks (precise). Before generation each hit is enriched using the
document hierarchy:

* ``HIT``          - the matched chunk, verbatim.
* ``PARENT_LEAD``  - the lead text of the nearest ancestor section that has its own text (often the
                     paragraph that defines terms or aliases used by its children), truncated to a
                     token cap. Only a *slice* of the parent is sent, never the whole subtree.
* ``NEIGHBOR``     - adjacent chunks of the same section, so a list/table/paragraph that was split
                     for size is seen in one piece.

Blocks are de-duplicated, kept within a token budget (hits are never dropped) and returned in
document order. Every block carries its own citation id, so the answer can cite exactly where a
statement came from (including text that only appeared as parent context).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.text import estimate_tokens, truncate_at_sentence
from app.models.schema import Chunk, Document, DocumentVersion, Section
from app.retrieval.rag import RetrievedChunk

MAX_ANCESTOR_CLIMB = 4


@dataclass
class ContextBlock:
    citation_id: str
    chunk_id: UUID
    role: str  # HIT | PARENT_LEAD | NEIGHBOR
    document_id: UUID
    document_version_id: UUID
    document_name: str
    section_id: UUID
    section_heading: str
    section_path: str
    section_ordinal: int
    chunk_ordinal: int
    breadcrumb: str
    page_start: int | None
    page_end: int | None
    text: str
    kind: str = "TEXT"
    truncated: bool = False
    score: float | None = None

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    def trace(self) -> dict[str, Any]:
        return {
            "chunk_id": str(self.chunk_id),
            "role": self.role,
            "section_path": self.section_path,
            "truncated": self.truncated,
        }


class ContextAssembler:
    def __init__(
        self,
        session: Session,
        project_id: UUID,
        token_budget: int = 3500,
        parent_lead_tokens: int = 150,
        neighbor_chunks: int = 1,
    ) -> None:
        self._session = session
        self._project_id = project_id
        self._budget = token_budget
        self._lead_tokens = parent_lead_tokens
        self._neighbors = neighbor_chunks

    def assemble(self, hits: list[RetrievedChunk]) -> list[ContextBlock]:
        blocks: dict[UUID, ContextBlock] = {}
        used = 0
        for hit in hits:  # hits are always included
            block = _block_from_hit(hit)
            blocks[hit.chunk_id] = block
            used += block.tokens
        if self._lead_tokens > 0:
            used = self._add_parent_leads(hits, blocks, used)
        if self._neighbors > 0:
            used = self._add_neighbors(hits, blocks, used)
        return sorted(blocks.values(), key=_document_order)

    def blocks_for_chunks(
        self, chunk_ids: set[UUID], role: str = "GRAPH_EVIDENCE"
    ) -> list[ContextBlock]:
        """Whole-chunk blocks for passages a graph fact cites (so the answer can cite them)."""
        if not chunk_ids:
            return []
        rows = self._session.execute(
            _chunk_rows().where(Chunk.project_id == self._project_id, Chunk.id.in_(chunk_ids))
        ).all()
        return sorted(
            (_block_from_row(row[0], row, role, row[0].content, False) for row in rows),
            key=_document_order,
        )

    # -- parents -----------------------------------------------------------------------------
    def _add_parent_leads(
        self, hits: list[RetrievedChunk], blocks: dict[UUID, ContextBlock], used: int
    ) -> int:
        """Attach the nearest ancestor's lead text (climbing past ancestors that have no text)."""
        parents = self._parents_of({hit.section_id for hit in hits})
        cursor: dict[UUID, UUID] = {
            hit.section_id: parent
            for hit in hits
            if (parent := parents.get(hit.section_id)) is not None
        }
        resolved: dict[UUID, tuple[Chunk, Any]] = {}
        for _ in range(MAX_ANCESTOR_CLIMB):
            if not cursor:
                break
            leads = self._lead_chunks(set(cursor.values()))
            unresolved: dict[UUID, UUID] = {}
            for origin, ancestor in cursor.items():
                if ancestor in leads:
                    resolved[origin] = leads[ancestor]
                else:
                    unresolved[origin] = ancestor
            above = self._parents_of(set(unresolved.values())) if unresolved else {}
            cursor = {
                origin: parent
                for origin, ancestor in unresolved.items()
                if (parent := above.get(ancestor)) is not None
            }
        for hit in hits:
            found = resolved.get(hit.section_id)
            if found is None or found[0].id in blocks:
                continue
            chunk, row = found
            text, truncated = truncate_at_sentence(chunk.content, self._lead_tokens)
            block = _block_from_row(chunk, row, "PARENT_LEAD", text, truncated)
            if used + block.tokens > self._budget:
                break
            blocks[chunk.id] = block
            used += block.tokens
        return used

    def _parents_of(self, section_ids: set[UUID]) -> dict[UUID, UUID | None]:
        rows = self._session.execute(
            select(Section.id, Section.parent_section_id).where(
                Section.project_id == self._project_id, Section.id.in_(section_ids)
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    def _lead_chunks(self, section_ids: set[UUID]) -> dict[UUID, tuple[Chunk, Any]]:
        rows = self._session.execute(
            _chunk_rows().where(
                Chunk.project_id == self._project_id,
                Chunk.section_id.in_(section_ids),
                Chunk.ordinal == 1,
            )
        ).all()
        return {row[0].section_id: (row[0], row) for row in rows}

    # -- neighbours --------------------------------------------------------------------------
    def _add_neighbors(
        self, hits: list[RetrievedChunk], blocks: dict[UUID, ContextBlock], used: int
    ) -> int:
        for hit in hits:
            low, high = hit.chunk_ordinal - self._neighbors, hit.chunk_ordinal + self._neighbors
            rows = self._session.execute(
                _chunk_rows().where(
                    Chunk.project_id == self._project_id,
                    Chunk.section_id == hit.section_id,
                    Chunk.ordinal.between(low, high),
                    Chunk.ordinal != hit.chunk_ordinal,
                )
            ).all()
            for row in rows:
                chunk: Chunk = row[0]
                if chunk.id in blocks:
                    continue
                block = _block_from_row(chunk, row, "NEIGHBOR", chunk.content, False)
                if used + block.tokens > self._budget:
                    return used
                blocks[chunk.id] = block
                used += block.tokens
        return used


def _document_order(block: ContextBlock) -> tuple[str, str, int, int]:
    return (
        block.document_name,
        str(block.document_version_id),
        block.section_ordinal,
        block.chunk_ordinal,
    )


def merge_blocks(blocks: list[ContextBlock], extra: list[ContextBlock]) -> list[ContextBlock]:
    """Add ``extra`` blocks not already present (an existing role wins), in document order."""
    known = {block.chunk_id for block in blocks}
    merged = [*blocks, *(block for block in extra if block.chunk_id not in known)]
    return sorted(merged, key=_document_order)


def _chunk_rows() -> Any:
    return (
        select(Chunk, Document.id, Document.name, Section.heading, Section.path, Section.ordinal)
        .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(Section, Chunk.section_id == Section.id)
    )


def _block_from_hit(hit: RetrievedChunk) -> ContextBlock:
    return ContextBlock(
        citation_id=f"chunk:{hit.chunk_id}",
        chunk_id=hit.chunk_id,
        role="HIT",
        document_id=hit.document_id,
        document_version_id=hit.document_version_id,
        document_name=hit.document_name,
        section_id=hit.section_id,
        section_heading=hit.section_heading,
        section_path=hit.section_path,
        section_ordinal=hit.section_ordinal,
        chunk_ordinal=hit.chunk_ordinal,
        breadcrumb=hit.breadcrumb,
        page_start=hit.page_start,
        page_end=hit.page_end,
        text=hit.content,
        kind=hit.kind,
        score=hit.fused_score,
    )


def _block_from_row(
    row_chunk: Chunk, row: Any, role: str, text: str, truncated: bool
) -> ContextBlock:
    return ContextBlock(
        citation_id=f"chunk:{row_chunk.id}",
        chunk_id=row_chunk.id,
        role=role,
        document_id=row[1],
        document_version_id=row_chunk.document_version_id,
        document_name=row[2],
        section_id=row_chunk.section_id,
        section_heading=row[3],
        section_path=row[4] or "",
        section_ordinal=row[5],
        chunk_ordinal=row_chunk.ordinal,
        breadcrumb=row_chunk.breadcrumb or "",
        page_start=row_chunk.page_start,
        page_end=row_chunk.page_end,
        text=text,
        kind=row_chunk.chunk_kind,
        truncated=truncated,
    )
