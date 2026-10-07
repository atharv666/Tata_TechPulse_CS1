"""Controlled persistence vocabularies required by the MVP specifications."""

from enum import StrEnum


class MembershipRole(StrEnum):
    VIEWER = "VIEWER"
    ENGINEER = "ENGINEER"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"


class TrustState(StrEnum):
    CANDIDATE = "CANDIDATE"
    TRUSTED = "TRUSTED"


class ExtractionType(StrEnum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"


class SourceClassification(StrEnum):
    DIRECT_TEXT = "DIRECT_TEXT"
    TABLE = "TABLE"
    DIAGRAM = "DIAGRAM"
    MULTI_SOURCE_INFERENCE = "MULTI_SOURCE_INFERENCE"


class ValidationState(StrEnum):
    PENDING = "PENDING"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    HUMAN_CORRECTED = "HUMAN_CORRECTED"
    REJECTED = "REJECTED"


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ComparisonState(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
