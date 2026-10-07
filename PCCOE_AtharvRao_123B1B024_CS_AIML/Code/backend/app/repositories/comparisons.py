"""Project-scoped persistence for explicit revision-comparison jobs and findings."""

from uuid import UUID

from sqlalchemy import select

from app.models.schema import Comparison, ComparisonFinding, DocumentVersion, Job
from app.repositories.base import ProjectScopedRepository


class ComparisonRepository(ProjectScopedRepository):
    def require_version(self, version_id: UUID) -> DocumentVersion:
        version = self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.project_id == self.project_id,
                DocumentVersion.id == version_id,
            )
        )
        if version is None:
            raise ValueError("Document version is not available in this project.")
        return version

    def add_comparison(self, comparison: Comparison) -> Comparison:
        self._require_project(comparison.project_id)
        self.session.add(comparison)
        return comparison

    def add_job(self, job: Job) -> Job:
        self._require_project(job.project_id)
        self.session.add(job)
        return job

    def add_finding(self, finding: ComparisonFinding) -> ComparisonFinding:
        self._require_project(finding.project_id)
        self.session.add(finding)
        return finding

    def findings(self, comparison_id: UUID) -> list[ComparisonFinding]:
        return list(
            self.session.scalars(
                select(ComparisonFinding).where(
                    ComparisonFinding.project_id == self.project_id,
                    ComparisonFinding.comparison_id == comparison_id,
                )
            )
        )

    def _require_project(self, resource_project_id: UUID) -> None:
        if resource_project_id != self.project_id:
            raise ValueError("Resource project_id does not match repository project scope.")
