"""Deterministic validation and confidence rules for derived graph candidates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.canonicalization.core import canonical_relationship_type
from app.models.enums import ExtractionType, SourceClassification
from app.models.schema import Entity, EntityEvidence, Relationship, RelationshipEvidence

INFERRED_FACTOR = Decimal("0.85")
OCR_FACTOR = Decimal("0.95")
CORROBORATION_BONUS = Decimal("0.02")


@dataclass(frozen=True)
class ValidationOutcome:
    valid: bool
    confidence: Decimal
    reasons: tuple[str, ...] = ()


def calculate_confidence(
    raw_confidence: Decimal,
    extraction_type: ExtractionType,
    evidence_count: int,
    *,
    ocr_only: bool = False,
) -> Decimal:
    """Pure function of the extractor's value and the evidence: rebuilding never compounds it.

    Inferred facts are discounted, facts read only from OCR'd text are discounted slightly, and
    independent corroboration adds a small bonus. This never grants human verification.
    """
    value = raw_confidence
    if extraction_type is ExtractionType.INFERRED:
        value *= INFERRED_FACTOR
    if ocr_only:
        value *= OCR_FACTOR
    if evidence_count == 0:
        value = Decimal("0")
    elif evidence_count > 1:
        value = min(Decimal("1"), value + CORROBORATION_BONUS)
    return value.quantize(Decimal("0.001"))


def _ocr_only(evidence: list[EntityEvidence] | list[RelationshipEvidence]) -> bool:
    return bool(evidence) and all(
        item.source_classification is SourceClassification.OCR_TEXT for item in evidence
    )


def validate_entity(entity: Entity, evidence: list[EntityEvidence]) -> ValidationOutcome:
    reasons: list[str] = []
    if not entity.canonical_name.strip() or not entity.normalized_name.strip():
        reasons.append("Entity name is missing.")
    if not entity.entity_type.strip():
        reasons.append("Entity type is missing.")
    if any(item.project_id != entity.project_id for item in evidence):
        reasons.append("Entity evidence crosses project boundary.")
    raw = entity.raw_confidence if entity.raw_confidence is not None else entity.confidence
    confidence = calculate_confidence(
        raw, entity.extraction_type, len(evidence), ocr_only=_ocr_only(evidence)
    )
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
    if canonical_relationship_type(relationship.relationship_type) is None:
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
    raw = (
        relationship.raw_confidence
        if relationship.raw_confidence is not None
        else relationship.confidence
    )
    confidence = calculate_confidence(
        raw, relationship.extraction_type, len(evidence), ocr_only=_ocr_only(evidence)
    )
    return ValidationOutcome(not reasons, confidence, tuple(reasons))
