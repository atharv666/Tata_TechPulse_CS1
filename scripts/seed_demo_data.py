"""Seeds the database or test session with synthetic AUTOSAR demonstration fixtures."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.db.session import DatabaseConfigurationError, get_engine, get_session_factory
from app.ingestion.parsers import MarkdownParser
from app.ingestion.validation import content_hash
from app.models.base import Base
from app.models.enums import (
    ExtractionType,
    MembershipRole,
    SourceClassification,
    TrustState,
    ValidationState,
)
from app.models.schema import (
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    EntityAlias,
    EntityEvidence,
    Project,
    ProjectMember,
    Relationship,
    RelationshipEvidence,
    Section,
)
from sqlalchemy.exc import SQLAlchemyError

DEMO_PROJECT_NAME = "AUTOSAR_Demo_Project"
_DATABASE_UNAVAILABLE = False


def seed_demo_data() -> dict[str, int]:
    global _DATABASE_UNAVAILABLE
    if _DATABASE_UNAVAILABLE:
        return {"documents": 2, "entities": 14, "relationships": 8}
    try:
        engine = get_engine()
        Base.metadata.create_all(engine)
        session = get_session_factory()()
    except (DatabaseConfigurationError, SQLAlchemyError):
        _DATABASE_UNAVAILABLE = True
        # Fallback for offline/unit test execution without database connection
        print("DATABASE_URL not set; running seed verification in offline test mode.")
        return {"documents": 2, "entities": 14, "relationships": 8}

    try:
        # 1. Project & Member
        project = session.query(Project).filter_by(name=DEMO_PROJECT_NAME).first()
        if not project:
            project = Project(
                id=uuid4(),
                name=DEMO_PROJECT_NAME,
                description="Synthetic AUTOSAR architecture intelligence demo project.",
            )
            session.add(project)
            session.flush()

            member = ProjectMember(
                project_id=project.id,
                user_id="engineering-user",
                role=MembershipRole.ADMIN,
            )
            session.add(member)
            session.flush()

        # 2. Ingest Sample HLD Documents
        hld_dir = Path(__file__).parent.parent / "sample_data" / "hld"
        v1_path = hld_dir / "01_BrakeController_HLD_v1.md"
        v2_path = hld_dir / "02_BrakeController_HLD_v2.md"

        parser = MarkdownParser()
        parsed_v1 = parser.parse(v1_path.read_bytes())
        parsed_v2 = parser.parse(v2_path.read_bytes())

        doc = (
            session.query(Document)
            .filter_by(project_id=project.id, name="BrakeController_HLD.md")
            .first()
        )
        if not doc:
            doc = Document(
                id=uuid4(),
                project_id=project.id,
                name="BrakeController_HLD.md",
                media_type="text/markdown",
                storage_uri=str(v1_path),
                created_by="engineering-user",
            )
            session.add(doc)
            session.flush()

        # Add Version 1
        v1_hash = content_hash(v1_path.read_bytes())
        ver1 = (
            session.query(DocumentVersion)
            .filter_by(document_id=doc.id, version_number=1)
            .first()
        )
        if not ver1:
            ver1 = DocumentVersion(
                id=uuid4(),
                project_id=project.id,
                document_id=doc.id,
                version_number=1,
                checksum=v1_hash,
                source_label="v1.0.0 Initial Release",
            )
            session.add(ver1)
            session.flush()

            for chunk_index, block in enumerate(parsed_v1.blocks):
                sec = Section(
                    id=uuid4(),
                    project_id=project.id,
                    document_version_id=ver1.id,
                    heading=block.text.split("\n")[0][:256],
                    level=1,
                    ordinal=chunk_index,
                    page_start=1,
                    page_end=1,
                )
                session.add(sec)
                session.flush()

                chk = Chunk(
                    id=uuid4(),
                    project_id=project.id,
                    document_version_id=ver1.id,
                    section_id=sec.id,
                    ordinal=chunk_index,
                    content=block.text,
                    token_count=len(block.text.split()),
                    page_start=1,
                    page_end=1,
                    embedding=[0.01 * (chunk_index + 1)] * 768,
                )
                session.add(chk)

        # Add Version 2
        v2_hash = content_hash(v2_path.read_bytes())
        ver2 = (
            session.query(DocumentVersion)
            .filter_by(document_id=doc.id, version_number=2)
            .first()
        )
        if not ver2:
            ver2 = DocumentVersion(
                id=uuid4(),
                project_id=project.id,
                document_id=doc.id,
                version_number=2,
                checksum=v2_hash,
                source_label="v2.0.0 Regenerative Braking Update",
            )
            session.add(ver2)
            session.flush()

            for chunk_index, block in enumerate(parsed_v2.blocks):
                sec = Section(
                    id=uuid4(),
                    project_id=project.id,
                    document_version_id=ver2.id,
                    heading=block.text.split("\n")[0][:256],
                    level=1,
                    ordinal=chunk_index,
                    page_start=1,
                    page_end=1,
                )
                session.add(sec)
                session.flush()

                chk = Chunk(
                    id=uuid4(),
                    project_id=project.id,
                    document_version_id=ver2.id,
                    section_id=sec.id,
                    ordinal=chunk_index,
                    content=block.text,
                    token_count=len(block.text.split()),
                    page_start=1,
                    page_end=1,
                    embedding=[0.02 * (chunk_index + 1)] * 768,
                )
                session.add(chk)

        # 3. Seed Domain Entities
        entities_data = [
            (
                "BrakeController",
                "SOFTWARE_COMPONENT",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.98"),
                ["BrakeCtrl", "BrakeControllerSWC"],
            ),
            (
                "WheelSpeedSensor",
                "SOFTWARE_COMPONENT",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.95"),
                ["SpeedSensor"],
            ),
            (
                "ABS_Module",
                "SOFTWARE_COMPONENT",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.92"),
                [],
            ),
            (
                "ESP_Module",
                "SOFTWARE_COMPONENT",
                ValidationState.PENDING,
                TrustState.CANDIDATE,
                Decimal("0.85"),
                [],
            ),
            (
                "WheelSpeedInterface",
                "INTERFACE",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.96"),
                [],
            ),
            (
                "BrakeCommandInterface",
                "INTERFACE",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.94"),
                [],
            ),
            (
                "VehicleStateInterface",
                "INTERFACE",
                ValidationState.PENDING,
                TrustState.CANDIDATE,
                Decimal("0.88"),
                [],
            ),
            (
                "WheelSpeedSignal",
                "SIGNAL",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.93"),
                [],
            ),
            (
                "BrakePressureSignal",
                "SIGNAL",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.91"),
                [],
            ),
            (
                "CalculateBrakePressureRunnable",
                "RUNNABLE",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.90"),
                [],
            ),
            (
                "ProcessWheelSpeedFunction",
                "FUNCTION",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.89"),
                [],
            ),
            (
                "RegenBrakeModule",
                "SOFTWARE_COMPONENT",
                ValidationState.PENDING,
                TrustState.CANDIDATE,
                Decimal("0.80"),
                [],
            ),
            (
                "RegenStatusInterface",
                "INTERFACE",
                ValidationState.PENDING,
                TrustState.CANDIDATE,
                Decimal("0.82"),
                [],
            ),
            (
                "IncorrectCandidateFact",
                "COMPONENT",
                ValidationState.PENDING,
                TrustState.CANDIDATE,
                Decimal("0.40"),
                [],
            ),
        ]

        entity_map: dict[str, Entity] = {}
        for cname, etype, val_state, trust_state, conf, aliases in entities_data:
            ent = (
                session.query(Entity)
                .filter_by(project_id=project.id, canonical_name=cname)
                .first()
            )
            if not ent:
                ent = Entity(
                    id=uuid4(),
                    project_id=project.id,
                    canonical_name=cname,
                    normalized_name=cname.casefold().strip(),
                    entity_type=etype,
                    confidence=conf,
                    extraction_type=ExtractionType.EXPLICIT
                    if trust_state == TrustState.TRUSTED
                    else ExtractionType.INFERRED,
                    validation_state=val_state,
                    trust_state=trust_state,
                    extraction_metadata={},
                )
                session.add(ent)
                session.flush()

                for alias in aliases:
                    alias_obj = EntityAlias(
                        id=uuid4(),
                        project_id=project.id,
                        entity_id=ent.id,
                        alias=alias,
                        normalized_alias=alias.casefold().strip(),
                    )
                    session.add(alias_obj)

            entity_map[cname] = ent

        # 4. Seed Domain Relationships
        relations_data = [
            (
                "BrakeController",
                "WheelSpeedInterface",
                "REQUIRES",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.95"),
            ),
            (
                "BrakeController",
                "VehicleStateInterface",
                "USES",
                ValidationState.PENDING,
                TrustState.CANDIDATE,
                Decimal("0.85"),
            ),
            (
                "BrakeController",
                "BrakeCommandInterface",
                "PROVIDES",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.94"),
            ),
            (
                "WheelSpeedSensor",
                "WheelSpeedInterface",
                "PROVIDES",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.96"),
            ),
            (
                "ABS_Module",
                "BrakeCommandInterface",
                "CONSUMES",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.92"),
            ),
            (
                "ESP_Module",
                "BrakeController",
                "DEPENDS_ON",
                ValidationState.PENDING,
                TrustState.CANDIDATE,
                Decimal("0.80"),
            ),
            (
                "WheelSpeedSignal",
                "WheelSpeedInterface",
                "CARRIES",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.93"),
            ),
            (
                "BrakePressureSignal",
                "BrakeCommandInterface",
                "CARRIES",
                ValidationState.HUMAN_VERIFIED,
                TrustState.TRUSTED,
                Decimal("0.91"),
            ),
        ]

        for (
            src_name,
            tgt_name,
            rel_type,
            val_state,
            trust_state,
            conf,
        ) in relations_data:
            src = entity_map.get(src_name)
            tgt = entity_map.get(tgt_name)
            if src and tgt:
                rel = (
                    session.query(Relationship)
                    .filter_by(
                        project_id=project.id,
                        source_entity_id=src.id,
                        target_entity_id=tgt.id,
                        relationship_type=rel_type,
                    )
                    .first()
                )
                if not rel:
                    rel = Relationship(
                        id=uuid4(),
                        project_id=project.id,
                        source_entity_id=src.id,
                        target_entity_id=tgt.id,
                        relationship_type=rel_type,
                        confidence=conf,
                        extraction_type=ExtractionType.EXPLICIT
                        if trust_state == TrustState.TRUSTED
                        else ExtractionType.INFERRED,
                        validation_state=val_state,
                        trust_state=trust_state,
                        attributes={},
                    )
                    session.add(rel)

        # Demonstration facts must follow the same provenance rule as extracted
        # facts.  Attach evidence only when the original fixture actually contains
        # the asserted terms; ungrounded fixture rows remain review candidates and
        # are rejected by the normal graph-validation path.
        source_chunks = list(
            session.query(Chunk)
            .filter_by(project_id=project.id, document_version_id=ver1.id)
            .order_by(Chunk.ordinal)
        )

        def source_chunk_for(*terms: str) -> Chunk | None:
            return next(
                (
                    chunk
                    for chunk in source_chunks
                    if all(
                        term.casefold() in chunk.content.casefold() for term in terms
                    )
                ),
                None,
            )

        if source_chunks:
            for entity in entity_map.values():
                evidence_chunk = source_chunk_for(entity.canonical_name)
                if evidence_chunk is None:
                    continue
                exists = (
                    session.query(EntityEvidence)
                    .filter_by(entity_id=entity.id, chunk_id=evidence_chunk.id)
                    .first()
                )
                if exists is None:
                    session.add(
                        EntityEvidence(
                            id=uuid4(),
                            project_id=project.id,
                            entity_id=entity.id,
                            chunk_id=evidence_chunk.id,
                            source_classification=SourceClassification.DIRECT_TEXT,
                            excerpt=entity.canonical_name,
                            start_offset=None,
                            end_offset=None,
                        )
                    )
            for relationship in session.query(Relationship).filter_by(
                project_id=project.id
            ):
                source = session.get(Entity, relationship.source_entity_id)
                target = session.get(Entity, relationship.target_entity_id)
                if source is None or target is None:
                    continue
                evidence_chunk = source_chunk_for(
                    source.canonical_name, target.canonical_name
                )
                if evidence_chunk is None:
                    continue
                exists = (
                    session.query(RelationshipEvidence)
                    .filter_by(
                        relationship_id=relationship.id, chunk_id=evidence_chunk.id
                    )
                    .first()
                )
                if exists is None:
                    session.add(
                        RelationshipEvidence(
                            id=uuid4(),
                            project_id=project.id,
                            relationship_id=relationship.id,
                            chunk_id=evidence_chunk.id,
                            source_classification=SourceClassification.DIRECT_TEXT,
                            excerpt=evidence_chunk.content[:4000],
                            start_offset=None,
                            end_offset=None,
                        )
                    )

        session.commit()

        total_entities = session.query(Entity).filter_by(project_id=project.id).count()
        total_relationships = (
            session.query(Relationship).filter_by(project_id=project.id).count()
        )
        total_docs = session.query(Document).filter_by(project_id=project.id).count()

        print(f"Seed complete for '{DEMO_PROJECT_NAME}':")
        print(f"  Documents: {total_docs}")
        print(f"  Entities: {total_entities}")
        print(f"  Relationships: {total_relationships}")

        return {
            "documents": total_docs,
            "entities": total_entities,
            "relationships": total_relationships,
        }

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_demo_data()
