"""Deterministic validation and confidence rules for derived graph candidates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.canonicalization.core import canonical_relationship_type
from app.models.enums import ExtractionType
from app.models.schema import Entity, EntityEvidence, Relationship, RelationshipEvidence


@dataclass(frozen=True)
class ValidationOutcome:
    valid: bool
    confidence: Decimal
    reasons: tuple[str, ...] = ()


def calculate_confidence(
    raw_confidence: Decimal, extraction_type: ExtractionType, evidence_count: int
) -> Decimal:
    """Apply deterministic provenance/extraction modifiers; this never grants human verification."""
    value = raw_confidence
    if extraction_type is ExtractionType.INFERRED:
        value *= Decimal("0.85")
    if evidence_count == 0:
        value = Decimal("0")
    elif evidence_count > 1:
        value = min(Decimal("1"), value + Decimal("0.02"))
    return value.quantize(Decimal("0.001"))


def validate_entity(entity: Entity, evidence: list[EntityEvidence]) -> ValidationOutcome:
    reasons: list[str] = []
    if not entity.canonical_name.strip() or not entity.normalized_name.strip():
        reasons.append("Entity name is missing.")
    if not entity.entity_type.strip():
        reasons.append("Entity type is missing.")
    if any(item.project_id != entity.project_id for item in evidence):
        reasons.append("Entity evidence crosses project boundary.")
    confidence = calculate_confidence(entity.confidence, entity.extraction_type, len(evidence))
    if not evidence:
        reasons.append("Entity has no source evidence.")
    return ValidationOutcome(not reasons, confidence, tuple(reasons))


def validate_relationship(
    relationship: Relationship,
    source: Entity | None,
    target: Entity | None,
    evidence: list[RelationshipEvidence],
) -> ValidationOutcome:
    reasons: list[str] = []
    canonical_type = canonical_relationship_type(relationship.relationship_type)
    if canonical_type is None:
        reasons.append("Relationship type is unsupported.")
    if source is None or target is None:
        reasons.append("Relationship endpoint is undefined or outside the project.")
    elif source.id == target.id:
        reasons.append("Relationship endpoints must differ.")
    elif (
        source.project_id != relationship.project_id or target.project_id != relationship.project_id
    ):
        reasons.append("Relationship endpoint crosses project boundary.")
    if not evidence:
        reasons.append("Relationship has no source evidence.")
    if any(item.project_id != relationship.project_id for item in evidence):
        reasons.append("Relationship evidence crosses project boundary.")
    confidence = calculate_confidence(
        relationship.confidence, relationship.extraction_type, len(evidence)
    )
    return ValidationOutcome(not reasons, confidence, tuple(reasons))


def interface_findings(
    entities: list[Entity], relationships: list[Relationship]
) -> dict[str, tuple[str, ...]]:
    """Emit non-blocking potential findings for interfaces lacking a provider relationship."""
    providers = {
        relationship.target_entity_id
        for relationship in relationships
        if relationship.relationship_type == "PROVIDES"
    }
    return {
        str(entity.id): ("Potential missing provider for interface.",)
        for entity in entities
        if entity.entity_type == "INTERFACE" and entity.id not in providers
    }
