"""Versioned, deterministic extraction prompt construction."""

from app.core.security import wrap_untrusted_document
from app.extraction.taxonomy import ENTITY_TYPES, RELATIONSHIP_TYPES

EXTRACTION_PROMPT_VERSION = "autosar-candidate-extraction-v4"


def build_extraction_prompt(
    chunk_content: str,
    page_start: int | None,
    page_end: int | None,
    breadcrumb: str | None = None,
) -> str:
    """Constrain extraction to source-supported candidate facts and the controlled taxonomy."""
    entity_types = ", ".join(ENTITY_TYPES)
    relationship_types = ", ".join(RELATIONSHIP_TYPES)
    page_context = f"pages {page_start or 'unknown'}–{page_end or page_start or 'unknown'}"
    location = f"Document location: {breadcrumb}\n" if breadcrumb else ""
    return (
        f"Prompt version: {EXTRACTION_PROMPT_VERSION}\n"
        "Extract candidate AUTOSAR architecture facts only from the supplied chunk. "
        "Do not infer unsupported relationships. Every entity and relationship must include "
        "a literal source excerpt copied from the chunk. Relationships are directed "
        "source_name -> target_name and use the identifiers exactly as written.\n"
        "If a relationship names an item that is not defined in this chunk, still report the "
        "relationship with that name: the item may be defined elsewhere in the document.\n"
        "If the text explicitly says that another name refers to the same item (for example "
        "'also referenced as', 'abbreviated', 'alias'), list that name in the entity's `aliases` "
        "instead of creating a separate entity.\n"
        "Direction conventions (source_name -> target_name): an interface CARRIES the signals or "
        "data elements it transports ('S is carried by I' is I CARRIES S); a component PROVIDES "
        "an interface it offers and REQUIRES, USES or CONSUMES one it needs ('I is provided by C' "
        "is C PROVIDES I); 'A is part of B' is A PART_OF B; 'A is implemented by B' is A "
        "IMPLEMENTED_BY B; 'A precedes B' is A PRECEDES B.\n"
        "Only use named items (identifiers or proper names) as entities and relationship "
        "endpoints; never create entities for generic phrases such as 'wheel speed data' or "
        "'the controller'. Give an item the same type everywhere in the document.\n"
        f"Allowed entity types: {entity_types}.\n"
        f"Allowed relationship types: {relationship_types}.\n"
        "Map only clearly equivalent wording into the controlled relationship taxonomy. "
        "If no allowed type preserves the source meaning, omit the relationship.\n"
        f"{location}"
        f"Chunk context ({page_context}):\n{wrap_untrusted_document(chunk_content)}"
    )
