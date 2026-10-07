"""Worker boundary for explicit document-ingestion jobs; no extraction work is registered here."""

from typing import Protocol


class IngestionJobRunner(Protocol):
    """Durable job runner contract; a queue implementation is selected in a later deployment phase."""

    def run_next_ingestion_job(self) -> None:
        """Claim and execute one explicitly persisted ingestion job."""
