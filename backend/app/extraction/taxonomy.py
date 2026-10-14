"""Controlled AUTOSAR MVP taxonomy; model outputs outside these values are rejected.

Extension (ADR-005): ``FUNCTIONAL_FLOW`` and the flow relationships ``PRECEDES`` / ``TRIGGERS`` /
``SENDS_TO`` represent the functional flows the HLD case study asks for; ``TEST_CASE`` and
``VERIFIED_BY`` connect requirements and design elements to the tests that verify them (change
impact on tests). The taxonomy stays closed: nothing outside these values reaches the graph.
"""

from typing import Literal, TypeAlias

EntityType: TypeAlias = Literal[
    "COMPONENT",
    "SOFTWARE_COMPONENT",
    "INTERFACE",
    "PORT",
    "SIGNAL",
    "DATA_ELEMENT",
    "RUNNABLE",
    "FUNCTION",
    "ECU",
    "COMMUNICATION_CHANNEL",
    "DATA_TYPE",
    "REQUIREMENT",
    "FUNCTIONAL_FLOW",
    "TEST_CASE",
]
RelationshipType: TypeAlias = Literal[
    "USES",
    "REQUIRES",
    "PROVIDES",
    "CONSUMES",
    "PRODUCES",
    "CARRIES",
    "DEPENDS_ON",
    "CONNECTS_TO",
    "PART_OF",
    "IMPLEMENTED_BY",
    "PRECEDES",
    "TRIGGERS",
    "SENDS_TO",
    "VERIFIED_BY",
]

ENTITY_TYPES: tuple[str, ...] = (
    "COMPONENT",
    "SOFTWARE_COMPONENT",
    "INTERFACE",
    "PORT",
    "SIGNAL",
    "DATA_ELEMENT",
    "RUNNABLE",
    "FUNCTION",
    "ECU",
    "COMMUNICATION_CHANNEL",
    "DATA_TYPE",
    "REQUIREMENT",
    "FUNCTIONAL_FLOW",
    "TEST_CASE",
)
RELATIONSHIP_TYPES: tuple[str, ...] = (
    "USES",
    "REQUIRES",
    "PROVIDES",
    "CONSUMES",
    "PRODUCES",
    "CARRIES",
    "DEPENDS_ON",
    "CONNECTS_TO",
    "PART_OF",
    "IMPLEMENTED_BY",
    "PRECEDES",
    "TRIGGERS",
    "SENDS_TO",
    "VERIFIED_BY",
)
