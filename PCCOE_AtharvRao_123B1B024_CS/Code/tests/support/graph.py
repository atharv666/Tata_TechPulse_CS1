"""Builders that put knowledge-graph rows straight into the database for focused tests."""

from __future__ import annotations

from decimal import Decimal
from itertools import count
from uuid import UUID

from app.models.enums import (
    ExtractionType,
    SourceClassification,
    TrustState,
    ValidationState,
)
from app.models.schema import (
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    EntityAlias,
    EntityEvidence,
    Project,
    Relationship,
    RelationshipCandidate,
    RelationshipEvidence,
    Section,
)
from sqlalchemy.orm import Session

_counter = count(1)


def normalized(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


class GraphBuilder:
    """One project with one document; each ``chunk`` is a real section/chunk row."""

    def __init__(self, session: Session, name: str = "graph-tests") -> None:
        self.session = session
        self.project = Project(name=f"{name}-{next(_counter)}")
        session.add(self.project)
        session.flush()
        document = Document(
            project_id=self.project.id,
            name="Doc.md",
            media_type="text/markdown",
            storage_uri="memory://doc",
            created_by="tester",
        )
        session.add(document)
        session.flush()
        self.version = DocumentVersion(
            project_id=self.project.id,
            document_id=document.id,
            version_number=1,
            checksum="x" * 64,
        )
        session.add(self.version)
        session.flush()
        self._ordinal = count(1)

    @property
    def project_id(self) -> UUID:
        return self.project.id

    def chunk(self, text: str, breadcrumb: str | None = None) -> Chunk:
        ordinal = next(self._ordinal)
        section = Section(
            project_id=self.project_id,
            document_version_id=self.version.id,
            ordinal=ordinal,
            heading=f"Section {ordinal}",
            level=1,
            path=f"Section {ordinal}",
        )
        self.session.add(section)
        self.session.flush()
        chunk = Chunk(
            project_id=self.project_id,
            document_version_id=self.version.id,
            section_id=section.id,
            ordinal=1,
            content=text,
            token_count=max(1, len(text.split())),
            breadcrumb=breadcrumb or f"Doc > Section {ordinal}",
        )
        self.session.add(chunk)
        self.session.flush()
        return chunk

    def entity(
        self,
        name: str,
        entity_type: str = "SOFTWARE_COMPONENT",
        *,
        aliases: tuple[str, ...] = (),
        state: ValidationState = ValidationState.PENDING,
        confidence: str = "0.900",
        extraction: ExtractionType = ExtractionType.EXPLICIT,
        text: str | None = None,
        evidence: bool = True,
    ) -> Entity:
        entity = Entity(
            project_id=self.project_id,
            canonical_name=name,
            normalized_name=normalized(name),
            entity_type=entity_type,
            trust_state=TrustState.CANDIDATE,
            extraction_type=extraction,
            validation_state=state,
            raw_confidence=Decimal(confidence),
            confidence=Decimal(confidence),
        )
        self.session.add(entity)
        self.session.flush()
        if evidence:
            body = text or f"`{name}` is a `{entity_type}` described in this section."
            chunk = self.chunk(body)
            self.session.add(
                EntityEvidence(
                    project_id=self.project_id,
                    entity_id=entity.id,
                    chunk_id=chunk.id,
                    source_classification=SourceClassification.DIRECT_TEXT,
                    excerpt=body,
                    start_offset=0,
                    end_offset=len(body),
                )
            )
        for alias in aliases:
            self.session.add(
                EntityAlias(
                    project_id=self.project_id,
                    entity_id=entity.id,
                    alias=alias,
                    normalized_alias=normalized(alias),
                )
            )
        self.session.flush()
        return entity

    def candidate(
        self,
        source: str,
        relationship_type: str,
        target: str,
        *,
        confidence: str = "0.900",
        extraction: str = "EXPLICIT",
        chunk: Chunk | None = None,
    ) -> RelationshipCandidate:
        excerpt = f"{source} {relationship_type} {target}"
        chunk = chunk or self.chunk(excerpt)
        row = RelationshipCandidate(
            project_id=self.project_id,
            chunk_id=chunk.id,
            source_name=source,
            target_name=target,
            normalized_source=normalized(source),
            normalized_target=normalized(target),
            relationship_type=relationship_type,
            confidence=Decimal(confidence),
            extraction_type=extraction,
            source_classification="DIRECT_TEXT",
            excerpt=excerpt,
            start_offset=0,
            end_offset=len(excerpt),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def relationship(
        self,
        source: Entity,
        relationship_type: str,
        target: Entity,
        *,
        state: ValidationState = ValidationState.PENDING,
        confidence: str = "0.900",
        extraction: ExtractionType = ExtractionType.EXPLICIT,
        evidence_text: str | None = None,
    ) -> Relationship:
        """A relationship with real provenance (a chunk and an evidence excerpt)."""
        row = Relationship(
            project_id=self.project_id,
            source_entity_id=source.id,
            target_entity_id=target.id,
            relationship_type=relationship_type,
            trust_state=TrustState.CANDIDATE,
            extraction_type=extraction,
            validation_state=state,
            raw_confidence=Decimal(confidence),
            confidence=Decimal(confidence),
            attributes={},
        )
        self.session.add(row)
        self.session.flush()
        text = evidence_text or (
            f"{source.canonical_name} {relationship_type} {target.canonical_name}."
        )
        chunk = self.chunk(text)
        self.session.add(
            RelationshipEvidence(
                project_id=self.project_id,
                relationship_id=row.id,
                chunk_id=chunk.id,
                source_classification=SourceClassification.DIRECT_TEXT,
                excerpt=text,
                start_offset=0,
                end_offset=len(text),
            )
        )
        self.session.flush()
        return row
