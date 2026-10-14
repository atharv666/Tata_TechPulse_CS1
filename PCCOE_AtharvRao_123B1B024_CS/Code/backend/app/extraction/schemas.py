"""Structured candidate knowledge contract returned by the LLM provider."""

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.extraction.taxonomy import EntityType, RelationshipType


class EvidenceReference(BaseModel):
    excerpt: str = Field(min_length=1, max_length=4000)
    source_type: Literal["DIRECT_TEXT", "TABLE", "DIAGRAM", "MULTI_SOURCE_INFERENCE"]
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)


class CandidateEntity(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_type: Literal["EXPLICIT", "INFERRED"]
    evidence: EvidenceReference
    #: Other names the text *explicitly* says refer to this same item ("also referenced as ...").
    aliases: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("aliases")
    @classmethod
    def aliases_are_short_distinct_strings(cls, value: list[str]) -> list[str]:
        cleaned = {item.strip(): None for item in value if item.strip() and len(item) <= 512}
        return list(cleaned)


class CandidateRelationship(BaseModel):
    source_name: str = Field(min_length=1, max_length=512)
    target_name: str = Field(min_length=1, max_length=512)
    relationship_type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_type: Literal["EXPLICIT", "INFERRED"]
    evidence: EvidenceReference

    @field_validator("target_name")
    @classmethod
    def endpoints_must_differ(cls, value: str, info: ValidationInfo) -> str:
        source_name = info.data.get("source_name")
        if source_name is not None and value.casefold().strip() == source_name.casefold().strip():
            raise ValueError("Relationship source and target must differ.")
        return value


class ChunkExtraction(BaseModel):
    entities: list[CandidateEntity] = Field(default_factory=list)
    relationships: list[CandidateRelationship] = Field(default_factory=list)
