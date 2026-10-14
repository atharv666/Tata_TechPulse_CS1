"""Structured export of the knowledge graph: JSON, CSV and XLSX (case study: structured output).

Every row keeps its provenance (document, section, page, excerpt), confidence, extraction type and
validation state, so an export is never a lossy summary of what the review UI shows. Rejected,
merged and replaced facts are left out unless asked for.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ValidationState
from app.models.schema import (
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    EntityAlias,
    EntityEvidence,
    Finding,
    Relationship,
    RelationshipEvidence,
    Section,
)

TABLES = ("entities", "relationships", "findings", "components")
COMPONENT_TYPES = ("COMPONENT", "SOFTWARE_COMPONENT", "ECU")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class UnknownTableError(ValueError):
    """An export table name outside ``TABLES``."""


def safe_cell(value: Any) -> Any:
    """Neutralise spreadsheet formula injection: text that starts like a formula is quoted."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


class ExportService:
    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id

    # -- dataset ---------------------------------------------------------------------------------
    def dataset(self, include_rejected: bool = False) -> dict[str, list[dict[str, Any]]]:
        entities = self._entities(include_rejected)
        names = {row["id"]: row for row in entities}
        relationships = self._relationships(names, include_rejected)
        return {
            "entities": entities,
            "relationships": relationships,
            "findings": self._findings(names),
            "components": self._components(entities, relationships),
        }

    def to_json(self, include_rejected: bool = False) -> dict[str, Any]:
        data = self.dataset(include_rejected)
        return {
            "project_id": str(self._project_id),
            "generated_at": datetime.now(UTC).isoformat(),
            "counts": {name: len(rows) for name, rows in data.items()},
            "documents": self._documents(),
            **data,
        }

    def to_csv(self, table: str, include_rejected: bool = False) -> bytes:
        if table not in TABLES:
            raise UnknownTableError(f"Unknown export table '{table}'. Choose one of {TABLES}.")
        rows = self.dataset(include_rejected)[table]
        buffer = io.StringIO()
        columns = list(rows[0]) if rows else []
        writer = csv.writer(buffer)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([safe_cell(_flat(row[column])) for column in columns])
        return ("﻿" + buffer.getvalue()).encode("utf-8")  # BOM: opens correctly in Excel

    def to_xlsx(self, include_rejected: bool = False) -> bytes:
        workbook = Workbook()
        workbook.remove(workbook.active)
        for name, rows in self.dataset(include_rejected).items():
            sheet = workbook.create_sheet(name.title())
            columns = list(rows[0]) if rows else ["(no rows)"]
            sheet.append(columns)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for row in rows:
                sheet.append([safe_cell(_flat(row[column])) for column in columns])
            for index, column in enumerate(columns, start=1):
                width = max([len(str(column))] + [len(str(_flat(r[column]))) for r in rows[:200]])
                sheet.column_dimensions[sheet.cell(1, index).column_letter].width = min(
                    60, max(10, width + 2)
                )
            sheet.freeze_panes = "A2"
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    # -- tables ----------------------------------------------------------------------------------
    def _entities(self, include_rejected: bool) -> list[dict[str, Any]]:
        statement = select(Entity).where(
            Entity.project_id == self._project_id,
            Entity.merged_into_id.is_(None),
            Entity.superseded_by_id.is_(None),
        )
        if not include_rejected:
            statement = statement.where(Entity.validation_state != ValidationState.REJECTED)
        entities = list(self._session.scalars(statement.order_by(Entity.canonical_name, Entity.id)))
        aliases: dict[UUID, list[str]] = defaultdict(list)
        for alias in self._session.scalars(
            select(EntityAlias)
            .where(EntityAlias.project_id == self._project_id)
            .order_by(EntityAlias.alias)
        ):
            aliases[alias.entity_id].append(alias.alias)
        sources = self._sources(EntityEvidence, EntityEvidence.entity_id)
        return [
            {
                "id": str(entity.id),
                "name": entity.canonical_name,
                "type": entity.entity_type,
                "aliases": aliases.get(entity.id, []),
                "confidence": float(entity.confidence),
                "extraction_type": entity.extraction_type.value,
                "validation_state": entity.validation_state.value,
                "trust_state": entity.trust_state.value,
                **_provenance(sources.get(entity.id, [])),
            }
            for entity in entities
        ]

    def _relationships(
        self, entities: dict[str, dict[str, Any]], include_rejected: bool
    ) -> list[dict[str, Any]]:
        statement = select(Relationship).where(
            Relationship.project_id == self._project_id,
            Relationship.superseded_by_id.is_(None),
            ~Relationship.attributes.has_key("inactive_reason"),
        )
        if not include_rejected:
            statement = statement.where(Relationship.validation_state != ValidationState.REJECTED)
        relationships = self._session.scalars(
            statement.order_by(Relationship.relationship_type, Relationship.id)
        )
        sources = self._sources(RelationshipEvidence, RelationshipEvidence.relationship_id)
        rows: list[dict[str, Any]] = []
        for item in relationships:
            source = entities.get(str(item.source_entity_id))
            target = entities.get(str(item.target_entity_id))
            if source is None or target is None:
                continue  # an endpoint that is rejected or inactive: not part of the live graph
            rows.append(
                {
                    "id": str(item.id),
                    "source": source["name"],
                    "source_type": source["type"],
                    "relationship_type": item.relationship_type,
                    "target": target["name"],
                    "target_type": target["type"],
                    "confidence": float(item.confidence),
                    "extraction_type": item.extraction_type.value,
                    "validation_state": item.validation_state.value,
                    "trust_state": item.trust_state.value,
                    **_provenance(sources.get(item.id, [])),
                }
            )
        return rows

    def _findings(self, entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(Finding)
            .where(Finding.project_id == self._project_id)
            .order_by(Finding.finding_type, Finding.created_at, Finding.id)
        )
        return [
            {
                "id": str(row.id),
                "finding_type": row.finding_type,
                "severity": row.severity,
                "status": row.status,
                "summary": row.summary,
                "entity": entities.get(str(row.entity_id), {}).get("name")
                if row.entity_id
                else None,
                "confidence": float(row.confidence) if row.confidence is not None else None,
                "dismissed_reason": row.dismissed_reason,
            }
            for row in rows
        ]

    @staticmethod
    def _components(
        entities: list[dict[str, Any]], relationships: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """One row per component with what it provides, requires, uses, consumes and is part of."""
        outgoing: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        incoming: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for row in relationships:
            outgoing[row["source"]][row["relationship_type"]].append(row["target"])
            incoming[row["target"]][row["relationship_type"]].append(row["source"])
        rows: list[dict[str, Any]] = []
        for entity in entities:
            if entity["type"] not in COMPONENT_TYPES:
                continue
            name = entity["name"]
            rows.append(
                {
                    "component": name,
                    "type": entity["type"],
                    "provides": sorted(outgoing[name].get("PROVIDES", [])),
                    "requires": sorted(outgoing[name].get("REQUIRES", [])),
                    "uses": sorted(outgoing[name].get("USES", [])),
                    "consumes": sorted(outgoing[name].get("CONSUMES", [])),
                    "produces": sorted(outgoing[name].get("PRODUCES", [])),
                    "depends_on": sorted(outgoing[name].get("DEPENDS_ON", [])),
                    "part_of": sorted(outgoing[name].get("PART_OF", [])),
                    "contains": sorted(incoming[name].get("PART_OF", [])),
                    "required_or_used_by": sorted(
                        {
                            *incoming[name].get("REQUIRES", []),
                            *incoming[name].get("USES", []),
                            *incoming[name].get("DEPENDS_ON", []),
                        }
                    ),
                    "validation_state": entity["validation_state"],
                    "confidence": entity["confidence"],
                    "extraction_type": entity["extraction_type"],
                    "source_document": entity["source_document"],
                    "source_section": entity["source_section"],
                    "source_page": entity["source_page"],
                }
            )
        return rows

    def _documents(self) -> list[dict[str, Any]]:
        rows = self._session.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(Document.project_id == self._project_id)
            .order_by(Document.name, DocumentVersion.version_number)
        ).tuples()
        return [
            {
                "document": document.name,
                "version_number": version.version_number,
                "version_id": str(version.id),
                "declared_status": version.properties.get("status"),
                "declared_version": version.properties.get("version"),
                "title": version.properties.get("title"),
            }
            for document, version in rows
        ]

    def _sources(self, model: Any, key_column: Any) -> dict[UUID, list[dict[str, Any]]]:
        rows = self._session.execute(
            select(key_column, model.excerpt, model.source_classification, Chunk, Section, Document)
            .join(Chunk, Chunk.id == model.chunk_id)
            .join(Section, Section.id == Chunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(model.project_id == self._project_id)
            .order_by(Document.name, Chunk.document_version_id, Chunk.ordinal)
        ).tuples()
        found: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for key, excerpt, classification, chunk, section, document in rows:
            found[key].append(
                {
                    "document": document.name,
                    "section": section.path or section.heading,
                    "page": chunk.page_start,
                    "source_type": classification.value,
                    "excerpt": excerpt[:500],
                }
            )
        return found


def _provenance(sources: list[dict[str, Any]]) -> dict[str, Any]:
    first = sources[0] if sources else {}
    return {
        "evidence_count": len(sources),
        "source_document": first.get("document"),
        "source_section": first.get("section"),
        "source_page": first.get("page"),
        "source_type": first.get("source_type"),
        "source_excerpt": first.get("excerpt"),
        "evidence": sources[:5],
    }


def _flat(value: Any) -> Any:
    """CSV/XLSX cells are scalar: lists join with '; ', structures are dropped to a count."""
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return f"{len(value)} passage(s)"
        return "; ".join(str(item) for item in value)
    return value
