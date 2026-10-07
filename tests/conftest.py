"""Shared test configuration for the backend foundation."""

import sys
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIRECTORY))
