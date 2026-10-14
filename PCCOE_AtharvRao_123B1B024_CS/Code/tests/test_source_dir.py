"""Uploads are found by the worker no matter which folder each process was started from."""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings


def test_a_relative_upload_directory_is_anchored_to_the_repository(
    tmp_path: Path,
) -> None:
    here = Path.cwd()
    try:
        os.chdir(tmp_path)
        relative = Settings(document_source_dir="data/sources").document_source_dir
        os.chdir(PROJECT_ROOT / "backend")
        from_backend = Settings(document_source_dir="data/sources").document_source_dir
    finally:
        os.chdir(here)
    assert (
        relative == from_backend == str((PROJECT_ROOT / "data" / "sources").resolve())
    )


def test_an_absolute_upload_directory_is_left_alone(tmp_path: Path) -> None:
    assert Settings(document_source_dir=str(tmp_path)).document_source_dir == str(
        tmp_path
    )
