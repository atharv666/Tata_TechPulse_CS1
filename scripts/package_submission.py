"""Copy a clean source snapshot of the repository into a submission folder.

    python scripts/package_submission.py --dest PCCOE_AtharvRao_123B1B024_CS/Code

Only delivery-relevant files are copied: no secrets (``.env``), caches, dependency directories,
uploaded source files, build output, archives or other submission folders. The destination is
replaced, so run it on an empty or disposable directory. ``scripts/check_no_secrets.py`` should be
run on the result.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Top-level entries that make up the source snapshot (everything else is left out).
INCLUDE_TOP = (
    ".env.example",
    ".gitignore",
    ".github",
    "AGENTS.md",
    "README.md",
    "docker-compose.yml",
    "pytest.ini",
    "ruff.toml",
    "backend",
    "frontend",
    "scripts",
    "tests",
    "worker",
    "sample_data",
    "docs",
)

EXCLUDED_DIRS = {
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".vite",
    "coverage",
    "htmlcov",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".zip", ".source", ".log", ".tsbuildinfo"}
EXCLUDED_NAMES = {".env", ".env.local", ".coverage", ".DS_Store"}


def should_include(relative: Path) -> bool:
    """Whether a path (relative to the repository root) belongs in the snapshot."""
    parts = relative.parts
    if not parts or parts[0] not in INCLUDE_TOP:
        return False
    if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in parts):
        return False
    # Uploaded source documents and local runtime data never ship.
    if "data" in parts[:-1] and relative.suffix not in {".md", ".json"}:
        return False
    name = parts[-1]
    if name in EXCLUDED_NAMES or (name.startswith(".env.") and name != ".env.example"):
        return False
    return relative.suffix not in EXCLUDED_SUFFIXES


def is_unsafe_destination(destination: Path, root: Path = ROOT) -> bool:
    """The destination is replaced, so it must never be the repository or one of its parents."""
    destination, root = destination.resolve(), root.resolve()
    return destination == root or destination in root.parents


def copy_snapshot(destination: Path, root: Path = ROOT) -> list[Path]:
    if is_unsafe_destination(destination, root):
        raise ValueError(
            f"Refusing to replace {destination}: it contains the source repository"
        )
    if destination.exists():
        # Empty the folder instead of removing it: on Windows another process may hold it open.
        for child in destination.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    copied: list[Path] = []
    for source in sorted(root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(root)
        if not should_include(relative):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    destination = args.dest.resolve()
    if is_unsafe_destination(destination):
        print(
            "The destination must not be the repository root or one of its parents.",
            file=sys.stderr,
        )
        return 2
    copied = copy_snapshot(destination)
    print(f"Copied {len(copied)} files to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
