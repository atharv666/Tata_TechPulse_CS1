"""Compare two document versions: metadata, sections, entities and relationships.

Everything here is deterministic. A difference is reported as a *change*, never as a
contradiction or an error; consequences are shown through the bounded impact analysis on the live
graph, and every finding carries the source passages of the version(s) it comes from.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.canonicalization.view import type_group
from app.comparison.diff import MAX_LISTED, diff_statements
from app.comparison.matching import VersionSection, match_sections
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import ComparisonState, ValidationState
from app.models.schema import (
    Chunk,
    Comparison,
    ComparisonFinding,
    Document,
    DocumentVersion,
    Entity,
    EntityEvidence,
    Relationship,
    RelationshipEvidence,
    Section,
)
from app.retrieval.evidence import Citation
from app.retrieval.impact import ImpactAnalysisService, ImpactResult

EVIDENCE_PER_FACT = 2
IMPACT_FINDING_LIMIT = 10
IMPACT_ATTEMPT_LIMIT = 40
IMPACT_NODE_LIMIT = 20
RENAME_THRESHOLD = 0.80


class ChangeClassification(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    RENAMED = "RENAMED"
    TYPE_CHANGED = "TYPE_CHANGED"
    TARGET_CHANGED = "TARGET_CHANGED"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    RELATIONSHIP_TYPE_CHANGED = "RELATIONSHIP_TYPE_CHANGED"


class ChangeSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RevisionEvidence(BaseModel):
    citations: list[Citation] = Field(default_factory=list)


class RevisionFinding(BaseModel):
    scope: Literal["DOCUMENT", "SECTION", "ENTITY", "RELATIONSHIP"]
    classification: ChangeClassification
    severity: ChangeSeverity
    #: Deterministic text/set differences are certain; for graph facts this is the fact's own
    #: extraction confidence.
    confidence: float = Field(default=1.0, ge=0, le=1)
    entity_id: UUID | None = None
    old_fact_id: UUID | None = None
    new_fact_id: UUID | None = None
    summary: str
    changes: dict[str, Any] = Field(default_factory=dict)
    old_evidence: RevisionEvidence = Field(default_factory=RevisionEvidence)
    new_evidence: RevisionEvidence = Field(default_factory=RevisionEvidence)
    review_status: str = "NOT_APPLICABLE"
    impacts: list[ImpactResult] = Field(default_factory=list)


class RevisionComparisonResult(BaseModel):
    base_version_id: UUID
    target_version_id: UUID
    findings: list[RevisionFinding]
    notes: list[str] = Field(default_factory=list)


_SEVERITY_ORDER = {
    ChangeSeverity.HIGH: 0,
    ChangeSeverity.MEDIUM: 1,
    ChangeSeverity.LOW: 2,
    ChangeSeverity.INFO: 3,
}
_IMPACTING = {
    ChangeClassification.REMOVED,
    ChangeClassification.TARGET_CHANGED,
    ChangeClassification.SOURCE_CHANGED,
    ChangeClassification.TYPE_CHANGED,
    ChangeClassification.RELATIONSHIP_TYPE_CHANGED,
    ChangeClassification.RENAMED,
}


class RevisionComparisonService:
    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id

    def compare(self, base_version_id: UUID, target_version_id: UUID) -> RevisionComparisonResult:
        if base_version_id == target_version_id:
            raise ValueError("Comparison requires two distinct document versions.")
        base = self._version(base_version_id)
        target = self._version(target_version_id)
        findings = [
            *self._metadata_findings(base, target),
            *self._section_findings(base, target),
            *self._entity_findings(base, target),
            *self._relationship_findings(base, target),
        ]
        notes = self._attach_impacts(findings)
        findings.sort(key=lambda item: (_SEVERITY_ORDER[item.severity], item.scope, item.summary))
        return RevisionComparisonResult(
            base_version_id=base.id,
            target_version_id=target.id,
            findings=findings,
            notes=notes,
        )

    # -- versions and metadata ------------------------------
    def _version(self, version_id: UUID) -> DocumentVersion:
        version = self._session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.project_id == self._project_id, DocumentVersion.id == version_id
            )
        )
        if version is None:
            raise NotFoundError(
                "VERSION_NOT_FOUND", "Document version is not available in this project."
            )
        return version

    @staticmethod
    def _metadata_findings(base: DocumentVersion, target: DocumentVersion) -> list[RevisionFinding]:
        findings: list[RevisionFinding] = []
        for key, label, severity in (
            ("version", "document version", ChangeSeverity.INFO),
            ("status", "document status", ChangeSeverity.MEDIUM),
            ("classification", "classification", ChangeSeverity.LOW),
            ("date", "document date", ChangeSeverity.INFO),
        ):
            before, after = base.properties.get(key), target.properties.get(key)
            if before == after or (before is None and after is None):
                continue
            findings.append(
                RevisionFinding(
                    scope="DOCUMENT",
                    classification=ChangeClassification.MODIFIED,
                    severity=severity,
                    summary=f"The {label} changed from '{before}' to '{after}'.",
                    changes={"field": key, "old": before, "new": after},
                )
            )
        return findings

    # -- sections ------------------------------
    def _sections(self, version: DocumentVersion) -> list[VersionSection]:
        rows = self._session.execute(
            select(Section, Chunk.id, Chunk.content, Chunk.ordinal)
            .outerjoin(Chunk, Chunk.section_id == Section.id)
            .where(
                Section.project_id == self._project_id, Section.document_version_id == version.id
            )
            .order_by(Section.ordinal, Chunk.ordinal)
        ).all()
        grouped: dict[UUID, dict[str, Any]] = {}
        for section, chunk_id, content, _ordinal in rows:
            entry = grouped.setdefault(
                section.id, {"section": section, "text": [], "first": chunk_id}
            )
            if content:
                entry["text"].append(content)
        return [
            VersionSection(
                id=item["section"].id,
                ordinal=item["section"].ordinal,
                heading=item["section"].heading,
                path=item["section"].path or "",
                text="\n".join(item["text"]),
                page_start=item["section"].page_start,
                page_end=item["section"].page_end,
                first_chunk_id=item["first"],
            )
            for item in grouped.values()
        ]

    def _section_findings(
        self, base: DocumentVersion, target: DocumentVersion
    ) -> list[RevisionFinding]:
        matches = match_sections(self._sections(base), self._sections(target))
        findings: list[RevisionFinding] = []
        for old, new in matches.pairs:
            diff = diff_statements(old.text, new.text)
            if diff.is_empty:
                continue
            severity = ChangeSeverity.MEDIUM if diff.changed or diff.removed else ChangeSeverity.LOW
            parts = []
            if diff.changed:
                parts.append(f"{len(diff.changed)} value change(s)")
            if diff.removed:
                parts.append(f"{len(diff.removed)} statement(s) removed")
            if diff.added:
                parts.append(f"{len(diff.added)} statement(s) added")
            if diff.reworded:
                parts.append(f"{len(diff.reworded)} reworded")
            findings.append(
                RevisionFinding(
                    scope="SECTION",
                    classification=ChangeClassification.MODIFIED,
                    severity=severity,
                    summary=f"Section modified: {new.label} ({', '.join(parts)}).",
                    changes={
                        "old_section": old.label,
                        "new_section": new.label,
                        "value_changes": [
                            {
                                "old_values": list(change.old_values),
                                "new_values": list(change.new_values),
                                "old_statement": change.old_statement,
                                "new_statement": change.new_statement,
                            }
                            for change in diff.changed[:MAX_LISTED]
                        ],
                        "removed": diff.removed[:MAX_LISTED],
                        "added": diff.added[:MAX_LISTED],
                        "reworded": [
                            {"old": before, "new": after}
                            for before, after in diff.reworded[:MAX_LISTED]
                        ],
                    },
                    old_evidence=self._section_evidence(old),
                    new_evidence=self._section_evidence(new),
                )
            )
        for old in matches.removed:
            findings.append(
                RevisionFinding(
                    scope="SECTION",
                    classification=ChangeClassification.REMOVED,
                    severity=ChangeSeverity.MEDIUM,
                    summary=f"Section removed: {old.label}.",
                    changes={"old_section": old.label},
                    old_evidence=self._section_evidence(old),
                )
            )
        for new in matches.added:
            findings.append(
                RevisionFinding(
                    scope="SECTION",
                    classification=ChangeClassification.ADDED,
                    severity=ChangeSeverity.INFO,
                    summary=f"Section added: {new.label}.",
                    changes={"new_section": new.label},
                    new_evidence=self._section_evidence(new),
                )
            )
        return findings

    def _section_evidence(self, section: VersionSection) -> RevisionEvidence:
        if section.first_chunk_id is None:
            return RevisionEvidence()
        return RevisionEvidence(
            citations=self._citations_for_chunks([section.first_chunk_id], section.text)
        )

    # -- entities ------------------------------
    def _entity_ids_in(self, version: DocumentVersion) -> set[UUID]:
        rows = self._session.scalars(
            select(EntityEvidence.entity_id)
            .join(Chunk, Chunk.id == EntityEvidence.chunk_id)
            .join(Entity, Entity.id == EntityEvidence.entity_id)
            .where(
                EntityEvidence.project_id == self._project_id,
                Chunk.document_version_id == version.id,
                Entity.merged_into_id.is_(None),
                Entity.superseded_by_id.is_(None),
                Entity.validation_state != ValidationState.REJECTED,
            )
        )
        return set(rows)

    def _entity_findings(
        self, base: DocumentVersion, target: DocumentVersion
    ) -> list[RevisionFinding]:
        old_ids, new_ids = self._entity_ids_in(base), self._entity_ids_in(target)
        removed_ids, added_ids = old_ids - new_ids, new_ids - old_ids
        if not removed_ids and not added_ids:
            return []
        entities = {
            row.id: row
            for row in self._session.scalars(
                select(Entity).where(
                    Entity.project_id == self._project_id, Entity.id.in_(removed_ids | added_ids)
                )
            )
        }
        removed = sorted((entities[i] for i in removed_ids), key=lambda e: e.canonical_name)
        added = sorted((entities[i] for i in added_ids), key=lambda e: e.canonical_name)
        findings: list[RevisionFinding] = []
        # same name, different type: one entity whose kind changed
        for old in list(removed):
            twin = next(
                (
                    item
                    for item in added
                    if item.normalized_name == old.normalized_name
                    and item.entity_type != old.entity_type
                ),
                None,
            )
            if twin is not None:
                removed.remove(old)
                added.remove(twin)
                findings.append(
                    self._entity_finding(
                        ChangeClassification.TYPE_CHANGED,
                        old,
                        twin,
                        base,
                        target,
                        f"Entity type changed: {old.canonical_name} "
                        f"({old.entity_type} -> {twin.entity_type}).",
                    )
                )
        # a rename: a similar name of the same kind, mutually the best candidate
        for old in list(removed):
            candidates = [
                item
                for item in added
                if type_group(item.entity_type) == type_group(old.entity_type)
            ]
            scored = sorted(
                (
                    (SequenceMatcher(None, old.normalized_name, item.normalized_name).ratio(), item)
                    for item in candidates
                ),
                key=lambda row: row[0],
                reverse=True,
            )
            if scored and scored[0][0] >= RENAME_THRESHOLD:
                twin = scored[0][1]
                removed.remove(old)
                added.remove(twin)
                findings.append(
                    self._entity_finding(
                        ChangeClassification.RENAMED,
                        old,
                        twin,
                        base,
                        target,
                        f"Entity possibly renamed: {old.canonical_name} -> {twin.canonical_name}.",
                    )
                )
        findings.extend(
            self._entity_finding(
                ChangeClassification.REMOVED,
                old,
                None,
                base,
                target,
                f"Entity removed: {old.canonical_name} ({old.entity_type}).",
            )
            for old in removed
        )
        findings.extend(
            self._entity_finding(
                ChangeClassification.ADDED,
                None,
                new,
                base,
                target,
                f"Entity added: {new.canonical_name} ({new.entity_type}).",
            )
            for new in added
        )
        return findings

    def _entity_finding(
        self,
        classification: ChangeClassification,
        old: Entity | None,
        new: Entity | None,
        base: DocumentVersion,
        target: DocumentVersion,
        summary: str,
    ) -> RevisionFinding:
        fact = new or old
        assert fact is not None
        return RevisionFinding(
            scope="ENTITY",
            classification=classification,
            severity=_graph_severity(classification),
            confidence=float(fact.confidence),
            entity_id=fact.id,
            old_fact_id=old.id if old else None,
            new_fact_id=new.id if new else None,
            summary=summary,
            old_evidence=self._entity_evidence(old, base) if old else RevisionEvidence(),
            new_evidence=self._entity_evidence(new, target) if new else RevisionEvidence(),
            review_status=fact.validation_state.value,
        )

    def _entity_evidence(self, entity: Entity, version: DocumentVersion) -> RevisionEvidence:
        rows = self._session.execute(
            select(EntityEvidence.chunk_id, EntityEvidence.excerpt)
            .join(Chunk, Chunk.id == EntityEvidence.chunk_id)
            .where(
                EntityEvidence.project_id == self._project_id,
                EntityEvidence.entity_id == entity.id,
                Chunk.document_version_id == version.id,
            )
            .order_by(Chunk.ordinal)
            .limit(EVIDENCE_PER_FACT)
        ).all()
        return RevisionEvidence(citations=self._citations(rows))

    # -- relationships ------------------------------
    def _relationship_ids_in(self, version: DocumentVersion) -> set[UUID]:
        rows = self._session.scalars(
            select(RelationshipEvidence.relationship_id)
            .join(Chunk, Chunk.id == RelationshipEvidence.chunk_id)
            .join(Relationship, Relationship.id == RelationshipEvidence.relationship_id)
            .where(
                RelationshipEvidence.project_id == self._project_id,
                Chunk.document_version_id == version.id,
                Relationship.superseded_by_id.is_(None),
                Relationship.validation_state != ValidationState.REJECTED,
            )
        )
        return set(rows)

    def _relationship_findings(
        self, base: DocumentVersion, target: DocumentVersion
    ) -> list[RevisionFinding]:
        old_ids, new_ids = self._relationship_ids_in(base), self._relationship_ids_in(target)
        removed_ids, added_ids = old_ids - new_ids, new_ids - old_ids
        if not removed_ids and not added_ids:
            return []
        rows = {
            row.id: row
            for row in self._session.scalars(
                select(Relationship).where(
                    Relationship.project_id == self._project_id,
                    Relationship.id.in_(removed_ids | added_ids),
                )
            )
        }
        names = self._names(
            {r.source_entity_id for r in rows.values()}
            | {r.target_entity_id for r in rows.values()}
        )
        removed = sorted((rows[i] for i in removed_ids), key=lambda r: str(r.id))
        added = sorted((rows[i] for i in added_ids), key=lambda r: str(r.id))
        findings: list[RevisionFinding] = []

        def describe(item: Relationship) -> str:
            return (
                f"{names.get(item.source_entity_id, '?')} {item.relationship_type} "
                f"{names.get(item.target_entity_id, '?')}"
            )

        def pair(classification: ChangeClassification, matches: Any, label: str) -> None:
            for old in list(removed):
                twin = next((item for item in added if matches(old, item)), None)
                if twin is None:
                    continue
                removed.remove(old)
                added.remove(twin)
                findings.append(
                    self._relationship_finding(
                        classification,
                        old,
                        twin,
                        base,
                        target,
                        f"Relationship {label}: {describe(old)}  ->  {describe(twin)}.",
                    )
                )

        pair(
            ChangeClassification.TARGET_CHANGED,
            lambda a, b: (
                a.source_entity_id == b.source_entity_id
                and a.relationship_type == b.relationship_type
            ),
            "target changed",
        )
        pair(
            ChangeClassification.SOURCE_CHANGED,
            lambda a, b: (
                a.target_entity_id == b.target_entity_id
                and a.relationship_type == b.relationship_type
            ),
            "source changed",
        )
        pair(
            ChangeClassification.RELATIONSHIP_TYPE_CHANGED,
            lambda a, b: (
                a.source_entity_id == b.source_entity_id
                and a.target_entity_id == b.target_entity_id
            ),
            "type changed",
        )
        findings.extend(
            self._relationship_finding(
                ChangeClassification.REMOVED,
                old,
                None,
                base,
                target,
                f"Relationship removed: {describe(old)}.",
            )
            for old in removed
        )
        findings.extend(
            self._relationship_finding(
                ChangeClassification.ADDED,
                None,
                new,
                base,
                target,
                f"Relationship added: {describe(new)}.",
            )
            for new in added
        )
        return findings

    def _relationship_finding(
        self,
        classification: ChangeClassification,
        old: Relationship | None,
        new: Relationship | None,
        base: DocumentVersion,
        target: DocumentVersion,
        summary: str,
    ) -> RevisionFinding:
        fact = new or old
        assert fact is not None
        return RevisionFinding(
            scope="RELATIONSHIP",
            classification=classification,
            severity=_graph_severity(classification),
            confidence=float(fact.confidence),
            entity_id=fact.source_entity_id,
            old_fact_id=old.id if old else None,
            new_fact_id=new.id if new else None,
            summary=summary,
            changes={
                "old": _edge(old),
                "new": _edge(new),
            },
            old_evidence=self._relationship_evidence(old, base) if old else RevisionEvidence(),
            new_evidence=self._relationship_evidence(new, target) if new else RevisionEvidence(),
            review_status=fact.validation_state.value,
        )

    def _relationship_evidence(
        self, relationship: Relationship, version: DocumentVersion
    ) -> RevisionEvidence:
        rows = self._session.execute(
            select(RelationshipEvidence.chunk_id, RelationshipEvidence.excerpt)
            .join(Chunk, Chunk.id == RelationshipEvidence.chunk_id)
            .where(
                RelationshipEvidence.project_id == self._project_id,
                RelationshipEvidence.relationship_id == relationship.id,
                Chunk.document_version_id == version.id,
            )
            .order_by(Chunk.ordinal)
            .limit(EVIDENCE_PER_FACT)
        ).all()
        return RevisionEvidence(citations=self._citations(rows))

    # -- impact ------------------------------
    def _attach_impacts(self, findings: list[RevisionFinding]) -> list[str]:
        """Potentially affected elements for the most consequential graph changes (bounded).

        Relationship changes come first (they say *what* depends on what), then entity changes by
        severity. At most ``IMPACT_ATTEMPT_LIMIT`` analyses run, and the search stops once
        ``IMPACT_FINDING_LIMIT`` findings have something to show.
        """
        impactful = [
            item
            for item in findings
            if item.scope in {"ENTITY", "RELATIONSHIP"} and item.classification in _IMPACTING
        ]
        impactful.sort(
            key=lambda item: (
                item.scope != "RELATIONSHIP",
                _SEVERITY_ORDER[item.severity],
                item.summary,
            )
        )
        service = ImpactAnalysisService(self._session, self._project_id)
        with_impacts = attempts = 0
        for finding in impactful:
            if with_impacts >= IMPACT_FINDING_LIMIT or attempts >= IMPACT_ATTEMPT_LIMIT:
                break
            attempts += 1
            seen: set[UUID] = set()
            for root in self._impact_roots(finding):
                try:
                    result = service.analyze(root, depth=2, node_limit=IMPACT_NODE_LIMIT)
                except (NotFoundError, ConflictError):
                    continue  # a removed or replaced root has nothing live to analyse
                for item in result.results:
                    if item.affected_entity_id is not None and item.affected_entity_id not in seen:
                        seen.add(item.affected_entity_id)
                        finding.impacts.append(item)
            with_impacts += bool(finding.impacts)
        if attempts < len(impactful):
            return [
                "Impact analysis covered the most severe graph changes; "
                f"{len(impactful) - attempts} further change(s) were not analysed."
            ]
        return []

    def _impact_roots(self, finding: RevisionFinding) -> list[UUID]:
        if finding.scope == "ENTITY":
            return [finding.entity_id] if finding.entity_id else []
        roots: list[UUID] = []
        for side in ("old", "new"):
            edge = finding.changes.get(side)
            if edge:
                roots.extend(UUID(edge[key]) for key in ("source_id", "target_id"))
        return list(dict.fromkeys(roots))

    # -- helpers ------------------------------
    def _names(self, entity_ids: set[UUID]) -> dict[UUID, str]:
        if not entity_ids:
            return {}
        return {
            entity_id: name
            for entity_id, name in self._session.execute(
                select(Entity.id, Entity.canonical_name).where(
                    Entity.project_id == self._project_id, Entity.id.in_(entity_ids)
                )
            )
        }

    def _citations(self, rows: Any) -> list[Citation]:
        excerpts = {chunk_id: excerpt for chunk_id, excerpt in rows}
        return self._citations_for_chunks(list(excerpts), excerpts=excerpts)

    def _citations_for_chunks(
        self,
        chunk_ids: list[UUID],
        fallback_excerpt: str = "",
        excerpts: dict[UUID, str] | None = None,
    ) -> list[Citation]:
        if not chunk_ids:
            return []
        rows = self._session.execute(
            select(Chunk, Section, DocumentVersion, Document)
            .join(Section, Section.id == Chunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Chunk.project_id == self._project_id, Chunk.id.in_(chunk_ids))
            .order_by(Chunk.ordinal)
        ).tuples()
        found: list[Citation] = []
        for chunk, section, version, document in rows:
            text = (excerpts or {}).get(chunk.id) or chunk.content or fallback_excerpt
            found.append(
                Citation(
                    citation_id=f"chunk:{chunk.id}",
                    chunk_id=chunk.id,
                    document_id=document.id,
                    document_version_id=version.id,
                    document_name=document.name,
                    section_heading=section.heading,
                    section_path=section.path or "",
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    excerpt=text[:1200],
                )
            )
        return found


def _graph_severity(classification: ChangeClassification) -> ChangeSeverity:
    if classification in {
        ChangeClassification.REMOVED,
        ChangeClassification.TARGET_CHANGED,
        ChangeClassification.SOURCE_CHANGED,
    }:
        return ChangeSeverity.HIGH
    if classification in {
        ChangeClassification.TYPE_CHANGED,
        ChangeClassification.RELATIONSHIP_TYPE_CHANGED,
        ChangeClassification.RENAMED,
    }:
        return ChangeSeverity.MEDIUM
    return ChangeSeverity.INFO


def _edge(item: Relationship | None) -> dict[str, str] | None:
    if item is None:
        return None
    return {
        "id": str(item.id),
        "source_id": str(item.source_entity_id),
        "target_id": str(item.target_entity_id),
        "relationship_type": item.relationship_type,
    }


class ComparisonRunner:
    """Executes a queued comparison and stores its findings (idempotent: a rerun replaces them)."""

    def execute(self, session: Session, comparison_id: UUID) -> RevisionComparisonResult:
        comparison = session.get(Comparison, comparison_id)
        if comparison is None:
            raise NotFoundError("COMPARISON_NOT_FOUND", "Comparison was not found.")
        result = RevisionComparisonService(session, comparison.project_id).compare(
            comparison.base_version_id, comparison.target_version_id
        )
        session.execute(
            delete(ComparisonFinding).where(ComparisonFinding.comparison_id == comparison.id)
        )
        for finding in result.findings:
            session.add(
                ComparisonFinding(
                    project_id=comparison.project_id,
                    comparison_id=comparison.id,
                    entity_id=finding.entity_id,
                    finding_type=finding.classification.value,
                    confidence=Decimal(str(round(finding.confidence, 3))),
                    summary=finding.summary,
                    details=finding.model_dump(mode="json"),
                )
            )
        comparison.state = ComparisonState.COMPLETED
        return result


def finding_groups(findings: list[RevisionFinding]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in findings:
        counts[f"{item.scope}:{item.classification.value}"] += 1
    return dict(sorted(counts.items()))
