"""Worker process entry point (``python -m worker_runner.main``).

The shared application package lives in ``backend/``. Docker supplies PYTHONPATH; mirror that when
the
worker is started from a source checkout.
"""

import sys
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.jobs.runner import main

if __name__ == "__main__":
    main()
