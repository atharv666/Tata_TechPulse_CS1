"""Controlled AUTOSAR MVP taxonomy; model outputs outside these values are rejected."""

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
]

ENTITY_TYPES = (
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
)
RELATIONSHIP_TYPES = (
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
)
