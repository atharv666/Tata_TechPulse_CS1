"""Entity and relationship canonicalization."""

from app.canonicalization.core import EntityResolver, UnionFind, canonical_relationship_type

__all__ = ["EntityResolver", "UnionFind", "canonical_relationship_type"]
