"""Human review tests: reviewer actions preserve source candidates and audit history."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.models.enums import ExtractionType, MembershipRole, TrustState, ValidationState
from app.models.schema import Entity, Relationship
from app.services.review import ReviewActor, ReviewPermissionError, ReviewService


class FakeReviewRepository:
    def __init__(self, project_id: UUID, entities: list[Entity]) -> None:
        self.project_id = project_id
        self.entities = {entity.id: entity for entity in entities}
        self.relationships: dict[UUID, Relationship] = {}
        self.validations: list[object] = []
        self.audits: list[object] = []
        self.session = SimpleNamespace(added=[])
        self.session.add = self.session.added.append

    def pending_entities(self) -> list[Entity]:
        return [
            entity
            for entity in self.entities.values()
            if entity.validation_state is ValidationState.PENDING
            and entity.trust_state is TrustState.CANDIDATE
        ]

    def pending_relationships(self) -> list[Relationship]:
        return []

    def get_entity(self, entity_id: UUID) -> Entity | None:
        return self.entities.get(entity_id)

    def get_relationship(self, relationship_id: UUID) -> Relationship | None:
        return self.relationships.get(relationship_id)

    def add_entity(self, entity: Entity) -> Entity:
        self.entities[entity.id] = entity
        return entity

    def add_relationship(self, relationship: Relationship) -> Relationship:
        self.relationships[relationship.id] = relationship
        return relationship

    def entity_evidence(self, entity_id: UUID) -> list[object]:
        return []

    def relationship_evidence(self, relationship_id: UUID) -> list[object]:
        return []

    def entity_provenance(self, entity_id: UUID) -> list[object]:
        return []

    def relationship_provenance(self, relationship_id: UUID) -> list[object]:
        return []

    def record_validation(self, event: object) -> object:
        self.validations.append(event)
        return event

    def record_audit(self, event: object) -> object:
        self.audits.append(event)
        return event

    def validation_history(
        self, entity_id: UUID | None = None, relationship_id: UUID | None = None
    ) -> list[object]:
        return self.validations

    def audit_history(self, resource_id: UUID | None = None) -> list[object]:
        return self.audits


def candidate(project_id: UUID) -> Entity:
    return Entity(
        id=uuid4(),
        project_id=project_id,
        canonical_name="BrakeController",
        normalized_name="brakecontroller",
        entity_type="SOFTWARE_COMPONENT",
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.850"),
        extraction_metadata={"raw_mention": "Brake Controller"},
    )


def service(
    project_id: UUID, role: MembershipRole, fact: Entity
) -> tuple[ReviewService, FakeReviewRepository]:
    repository = FakeReviewRepository(project_id, [fact])
    return ReviewService(
        repository, ReviewActor("reviewer-1", project_id, role)
    ), repository  # type: ignore[arg-type]


def test_verify_marks_candidate_trusted_without_changing_confidence() -> None:
    project, fact = uuid4(), candidate(uuid4())
    fact.project_id = project
    review, repository = service(project, MembershipRole.REVIEWER, fact)

    result = review.verify_entity(fact.id, "Evidence confirmed")

    assert result.trust_state is TrustState.TRUSTED
    assert result.validation_state is ValidationState.HUMAN_VERIFIED
    assert result.confidence == Decimal("0.850")
    assert len(repository.validations) == len(repository.audits) == 1


def test_correction_creates_a_distinct_trusted_fact_and_preserves_candidate() -> None:
    project = uuid4()
    original = candidate(project)
    review, repository = service(project, MembershipRole.REVIEWER, original)

    corrected = review.correct_entity(
        original.id, "BrakeControl", "SOFTWARE_COMPONENT", "Correct official name"
    )

    assert corrected.id != original.id
    assert corrected.trust_state is TrustState.TRUSTED
    assert corrected.validation_state is ValidationState.HUMAN_CORRECTED
    assert corrected.extraction_metadata["corrected_from_entity_id"] == str(original.id)
    assert original.canonical_name == "BrakeController"
    assert original.extraction_metadata == {"raw_mention": "Brake Controller"}
    assert original.trust_state is TrustState.CANDIDATE
    assert original.validation_state is ValidationState.HUMAN_CORRECTED
    assert len(repository.validations) == len(repository.audits) == 2
    assert len(review.entity_validation_history(original.id)) == 2
    assert len(review.audit_history(original.id)) == 2


def test_rejection_and_queue_history_are_project_scoped() -> None:
    project = uuid4()
    fact = candidate(project)
    review, repository = service(project, MembershipRole.ADMIN, fact)

    assert len(review.review_queue()) == 1
    rejected = review.reject_entity(fact.id, "Not supported by source")

    assert rejected.validation_state is ValidationState.REJECTED
    assert rejected.trust_state is TrustState.CANDIDATE
    assert not review.review_queue()
    assert repository.validations[0].reason == "Not supported by source"  # type: ignore[union-attr]
    assert repository.audits[0].action == "REVIEW_REJECTED"  # type: ignore[union-attr]


@pytest.mark.parametrize("role", [MembershipRole.VIEWER, MembershipRole.ENGINEER])
def test_non_reviewers_cannot_change_candidates(role: MembershipRole) -> None:
    project = uuid4()
    fact = candidate(project)
    review, _ = service(project, role, fact)

    with pytest.raises(ReviewPermissionError):
        review.verify_entity(fact.id)


def test_cross_project_actor_and_repository_are_rejected() -> None:
    project, other_project = uuid4(), uuid4()
    repository = FakeReviewRepository(project, [candidate(project)])

    with pytest.raises(ReviewPermissionError):
        ReviewService(
            repository,
            ReviewActor("reviewer-1", other_project, MembershipRole.REVIEWER),
        )  # type: ignore[arg-type]
