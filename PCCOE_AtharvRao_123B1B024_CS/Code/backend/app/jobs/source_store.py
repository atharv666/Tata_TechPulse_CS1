"""Private local source handoff for workers; filenames never determine filesystem paths."""

from pathlib import Path
from uuid import UUID


class SourceStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def write(self, job_id: UUID, content: bytes) -> UUID:
        self._root.mkdir(parents=True, exist_ok=True)
        path = (self._root / f"{job_id}.source").resolve()
        if self._root not in path.parents:
            raise ValueError("Source storage path is outside the configured root.")
        path.write_bytes(content)
        return job_id

    def read(self, source_key: UUID) -> bytes:
        path = (self._root / f"{source_key}.source").resolve()
        if self._root not in path.parents:
            raise ValueError("Source path is outside the configured root.")
        return path.read_bytes()
