"""Which entity types may appear on each side of a relationship type.

These rules are *advisory*: a violation produces a "potential inconsistency" finding for a human to
look at, it never rejects or rewrites a fact (the HLD may be unusual, or the extraction wrong; code
cannot tell which). They are also the ruleset documented in ADR-005 and can be refined per project.
"""

from __future__ import annotations

from dataclasses import dataclass

_BEHAVIOUR = frozenset({"COMPONENT", "SOFTWARE_COMPONENT", "ECU", "RUNNABLE", "FUNCTION"})
_ENDPOINTS = frozenset({"INTERFACE", "SIGNAL", "DATA_ELEMENT"})
_ANY: frozenset[str] | None = None


@dataclass(frozen=True)
class RelationshipRule:
    sources: frozenset[str] | None  # ``None`` = any entity type
    targets: frozenset[str] | None


RELATIONSHIP_RULES: dict[str, RelationshipRule] = {
    "PROVIDES": RelationshipRule(
        frozenset({"COMPONENT", "SOFTWARE_COMPONENT", "PORT", "ECU"}),
        _ENDPOINTS | {"FUNCTION"},
    ),
    "REQUIRES": RelationshipRule(
        _BEHAVIOUR | {"PORT", "FUNCTIONAL_FLOW"},
        _ENDPOINTS | {"COMPONENT", "SOFTWARE_COMPONENT", "FUNCTION", "REQUIREMENT"},
    ),
    "USES": RelationshipRule(
        _BEHAVIOUR | {"PORT"},
        _ENDPOINTS | {"DATA_TYPE", "COMPONENT", "SOFTWARE_COMPONENT", "FUNCTION"},
    ),
    "CONSUMES": RelationshipRule(_BEHAVIOUR | {"PORT"}, _ENDPOINTS),
    "PRODUCES": RelationshipRule(_BEHAVIOUR | {"PORT"}, _ENDPOINTS),
    "CARRIES": RelationshipRule(
        frozenset({"INTERFACE", "COMMUNICATION_CHANNEL", "PORT"}),
        frozenset({"SIGNAL", "DATA_ELEMENT", "DATA_TYPE"}),
    ),
    "DEPENDS_ON": RelationshipRule(_ANY, _ANY),
    "CONNECTS_TO": RelationshipRule(
        frozenset({"PORT", "COMPONENT", "SOFTWARE_COMPONENT", "ECU", "COMMUNICATION_CHANNEL"}),
        frozenset({"PORT", "COMPONENT", "SOFTWARE_COMPONENT", "ECU", "COMMUNICATION_CHANNEL"}),
    ),
    "PART_OF": RelationshipRule(
        _ANY,
        frozenset(
            {
                "COMPONENT",
                "SOFTWARE_COMPONENT",
                "ECU",
                "INTERFACE",
                "FUNCTIONAL_FLOW",
                "REQUIREMENT",
                "COMMUNICATION_CHANNEL",
            }
        ),
    ),
    "IMPLEMENTED_BY": RelationshipRule(
        frozenset({"REQUIREMENT", "INTERFACE", "FUNCTIONAL_FLOW", "FUNCTION"}),
        _BEHAVIOUR,
    ),
    "PRECEDES": RelationshipRule(
        _BEHAVIOUR | {"FUNCTIONAL_FLOW"}, _BEHAVIOUR | {"FUNCTIONAL_FLOW"}
    ),
    "TRIGGERS": RelationshipRule(
        _BEHAVIOUR | {"FUNCTIONAL_FLOW", "SIGNAL"}, _BEHAVIOUR | {"FUNCTIONAL_FLOW"}
    ),
    "SENDS_TO": RelationshipRule(
        _BEHAVIOUR | {"PORT"}, _BEHAVIOUR | {"PORT", "COMMUNICATION_CHANNEL"}
    ),
    "VERIFIED_BY": RelationshipRule(
        frozenset({"REQUIREMENT", "FUNCTION", "COMPONENT", "SOFTWARE_COMPONENT", "INTERFACE"}),
        frozenset({"TEST_CASE"}),
    ),
}

# Relationship pairs that contradict each other when stated between the same two entities.
OPPOSING_TYPES = (("PROVIDES", "CONSUMES"), ("PROVIDES", "REQUIRES"))


def check_relationship(relationship_type: str, source_type: str, target_type: str) -> str | None:
    """A short description of the rule violated, or ``None`` when the triple is plausible."""
    rule = RELATIONSHIP_RULES.get(relationship_type)
    if rule is None:
        return None
    if rule.sources is not None and source_type not in rule.sources:
        return f"{relationship_type} is not expected to start at a {source_type}."
    if rule.targets is not None and target_type not in rule.targets:
        return f"{relationship_type} is not expected to end at a {target_type}."
    return None


# How a change propagates along each relationship type, as seen from the changed entity.
# ``IN``  = from the edge's target back to its source ("A REQUIRES X": changing X affects A);
# ``OUT`` = from the source forward to its target ("X IMPLEMENTED_BY C": changing X affects C).
# These are the impact rules documented in ADR-005; they are data, not model output.
IMPACT_PROPAGATION: dict[str, frozenset[str]] = {
    "REQUIRES": frozenset({"IN"}),
    "USES": frozenset({"IN"}),
    "DEPENDS_ON": frozenset({"IN"}),
    "CONSUMES": frozenset({"IN"}),
    "PROVIDES": frozenset({"IN", "OUT"}),
    "PRODUCES": frozenset({"IN", "OUT"}),
    "CARRIES": frozenset({"IN", "OUT"}),
    "CONNECTS_TO": frozenset({"IN", "OUT"}),
    "PART_OF": frozenset({"IN", "OUT"}),
    "IMPLEMENTED_BY": frozenset({"IN", "OUT"}),
    "PRECEDES": frozenset({"OUT"}),
    "TRIGGERS": frozenset({"OUT"}),
    "SENDS_TO": frozenset({"OUT"}),
    "VERIFIED_BY": frozenset({"OUT"}),
}


def impact_directions() -> tuple[frozenset[str], frozenset[str]]:
    """``(follow_out, follow_in)`` relationship-type sets for an impact traversal."""
    follow_out = frozenset(kind for kind, ways in IMPACT_PROPAGATION.items() if "OUT" in ways)
    follow_in = frozenset(kind for kind, ways in IMPACT_PROPAGATION.items() if "IN" in ways)
    return follow_out, follow_in
