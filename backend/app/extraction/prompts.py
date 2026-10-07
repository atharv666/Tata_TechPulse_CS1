"""Versioned, deterministic extraction prompt construction."""

from app.core.security import wrap_untrusted_document
from app.extraction.taxonomy import ENTITY_TYPES, RELATIONSHIP_TYPES

EXTRACTION_PROMPT_VERSION = "autosar-candidate-extraction-v2"


def build_extraction_prompt(
    chunk_content: str, page_start: int | None, page_end: int | None
) -> str:
    """Constrain extraction to source-supported candidate facts and the controlled taxonomy."""
    entity_types = ", ".join(ENTITY_TYPES)
    relationship_types = ", ".join(RELATIONSHIP_TYPES)
    page_context = f"pages {page_start or 'unknown'}–{page_end or page_start or 'unknown'}"
    return (
        f"Prompt version: {EXTRACTION_PROMPT_VERSION}\n"
        "Extract candidate AUTOSAR architecture facts only from the supplied chunk. "
        "Do not infer unsupported relationships. Every entity and relationship must include "
        "a literal source excerpt. Relationships are directed source_name -> target_name.\n"
        f"Allowed entity types: {entity_types}.\n"
        f"Allowed relationship types: {relationship_types}.\n"
        "Map only clearly equivalent wording into the controlled relationship taxonomy. "
        "If no allowed type preserves the source meaning, omit the relationship.\n"
        f"Chunk context ({page_context}):\n{wrap_untrusted_document(chunk_content)}"
    )
